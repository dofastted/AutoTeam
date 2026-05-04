#!/usr/bin/env bash
# Sequentially DELETE accounts from .tmp/standby_to_delete.json via the AutoTeam API.
# Each request triggers full cleanup: Team member removal + invite cancel +
# local auth files + CPA/Sub2API remote + accounts.json record. The endpoint
# holds _playwright_lock, so calls MUST be strictly serial.
set -u -o pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8788}"
EMAILS_FILE="${EMAILS_FILE:-.tmp/standby_to_delete.json}"
OUT_DIR="${OUT_DIR:-.tmp/standby-delete}"

if [[ ! -f .env ]]; then echo "error: .env not found" >&2; exit 1; fi
API_KEY=$(grep -E '^API_KEY=' .env | cut -d= -f2-)
if [[ -z "$API_KEY" ]]; then echo "error: API_KEY missing" >&2; exit 1; fi
if [[ ! -f "$EMAILS_FILE" ]]; then echo "error: $EMAILS_FILE not found" >&2; exit 1; fi

mkdir -p "$OUT_DIR"
RUN_ID=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$OUT_DIR/run-$RUN_ID.log"

mapfile -t EMAILS < <(python3 -c "
import json,sys
for e in json.load(open(sys.argv[1])):
    if isinstance(e,str) and e.strip():
        print(e.strip().lower())
" "$EMAILS_FILE")

TOTAL=${#EMAILS[@]}
echo "[$(date +%H:%M:%S)] delete start total=$TOTAL api=$API_BASE log=$LOG_FILE" | tee -a "$LOG_FILE"

OK=0; FAIL=0; INDEX=0
for EMAIL in "${EMAILS[@]}"; do
  INDEX=$((INDEX + 1))
  PER_FILE="$OUT_DIR/$EMAIL.json"
  printf -- "----------------\n[%s] (%d/%d) DELETE %s\n" "$(date +%H:%M:%S)" "$INDEX" "$TOTAL" "$EMAIL" | tee -a "$LOG_FILE"

  HTTP_CODE=$(curl -s -o "$PER_FILE" -w "%{http_code}" \
    --noproxy '*' \
    -X DELETE -H "Authorization: Bearer $API_KEY" \
    --max-time 120 \
    "$API_BASE/api/accounts/$EMAIL?sync_cpa_after=false")

  if [[ "$HTTP_CODE" == "200" ]]; then
    SUMMARY=$(python3 -c "
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    c=d.get('cleanup',{}) or {}
    print(f\"team={c.get('team_member_removed')} invite={c.get('invite_removed')} auth={len(c.get('local_auth_files',[]))} cpa={len(c.get('cpa_files',[]))} sub2api={len(c.get('sub2api_accounts',[]))}\")
except Exception as e:
    print(f'parse-error: {e}')
" "$PER_FILE" 2>&1)
    echo "  -> OK $SUMMARY" | tee -a "$LOG_FILE"
    OK=$((OK + 1))
  else
    BODY=$(head -c 300 "$PER_FILE" 2>/dev/null)
    echo "  -> FAIL HTTP=$HTTP_CODE body=$BODY" | tee -a "$LOG_FILE"
    FAIL=$((FAIL + 1))
  fi

  sleep 2  # let _playwright_lock settle
done

SUMMARY=$(python3 -c "
import json
print(json.dumps({
    'total': $TOTAL,
    'success': $OK,
    'failed': $FAIL,
    'log': '$LOG_FILE',
    'run_id': '$RUN_ID',
}, indent=2, ensure_ascii=False))
")
echo "$SUMMARY" > "$OUT_DIR/summary.json"
{
  echo "----------------"
  echo "[$(date +%H:%M:%S)] DONE"
  echo "$SUMMARY"
} | tee -a "$LOG_FILE"
