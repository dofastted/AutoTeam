#!/usr/bin/env bash
# Sequentially backfill OAuth RT for accounts that only have a session.json on disk.
# Reads .tmp/session_only_emails.json (JSON array of emails) and POSTs each to
# /api/accounts/<email>/cpa-auth, then polls /api/tasks/<task_id> until the
# task settles. Server enforces a global playwright lock, so requests must be
# strictly serial.
#
# Usage:
#   scripts/backfill_session_only_oauth.sh                # use defaults
#   API_BASE=http://127.0.0.1:8788 scripts/backfill_session_only_oauth.sh
#
# Inputs:
#   .tmp/session_only_emails.json   -- JSON array of emails to process
#   .env                            -- API_KEY=...
#
# Outputs:
#   .tmp/session-only-oauth/run-YYYYmmdd-HHMMSS.log    -- master log
#   .tmp/session-only-oauth/<email>.json               -- per-account result
#   .tmp/session-only-oauth/summary.json               -- final tally

set -u -o pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8788}"
EMAILS_FILE="${EMAILS_FILE:-.tmp/session_only_emails.json}"
OUT_DIR="${OUT_DIR:-.tmp/session-only-oauth}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_TIMEOUT="${POLL_TIMEOUT:-300}"   # per-account 5 min cap

if [[ ! -f .env ]]; then
  echo "error: .env not found" >&2
  exit 1
fi
API_KEY=$(grep -E '^API_KEY=' .env | cut -d= -f2-)
if [[ -z "$API_KEY" ]]; then
  echo "error: API_KEY not set in .env" >&2
  exit 1
fi
if [[ ! -f "$EMAILS_FILE" ]]; then
  echo "error: $EMAILS_FILE not found" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
RUN_ID=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$OUT_DIR/run-$RUN_ID.log"

mapfile -t EMAILS < <(python3 -c "
import json,sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for e in data:
    if isinstance(e,str) and e.strip():
        print(e.strip().lower())
" "$EMAILS_FILE")

TOTAL=${#EMAILS[@]}
if [[ $TOTAL -eq 0 ]]; then
  echo "no emails to process" | tee -a "$LOG_FILE"
  exit 0
fi

echo "[$(date +%H:%M:%S)] backfill start total=$TOTAL api=$API_BASE log=$LOG_FILE" | tee -a "$LOG_FILE"

OK=0
FAIL=0
SKIP=0
INDEX=0
for EMAIL in "${EMAILS[@]}"; do
  INDEX=$((INDEX + 1))
  PER_FILE="$OUT_DIR/$EMAIL.json"
  printf -- "----------------\n[%s] (%d/%d) %s\n" "$(date +%H:%M:%S)" "$INDEX" "$TOTAL" "$EMAIL" | tee -a "$LOG_FILE"

  POST_RESP=$(curl -s -X POST -H "Authorization: Bearer $API_KEY" \
    --max-time 30 \
    "$API_BASE/api/accounts/$EMAIL/cpa-auth")
  TASK_ID=$(printf '%s' "$POST_RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('task_id','') or '')
except Exception:
    pass
")
  if [[ -z "$TASK_ID" ]]; then
    echo "  POST failed -> $POST_RESP" | tee -a "$LOG_FILE"
    printf '%s' "$POST_RESP" > "$PER_FILE"
    FAIL=$((FAIL + 1))
    continue
  fi
  echo "  task_id=$TASK_ID; polling..." | tee -a "$LOG_FILE"

  WAITED=0
  STATUS="pending"
  TASK_JSON="{}"
  while (( WAITED < POLL_TIMEOUT )); do
    sleep "$POLL_INTERVAL"
    WAITED=$((WAITED + POLL_INTERVAL))
    TASK_JSON=$(curl -s -H "Authorization: Bearer $API_KEY" --max-time 15 \
      "$API_BASE/api/tasks/$TASK_ID")
    STATUS=$(printf '%s' "$TASK_JSON" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get('status') or '').strip())
except Exception:
    pass
")
    if [[ "$STATUS" == "success" || "$STATUS" == "completed" || "$STATUS" == "failed" || "$STATUS" == "error" ]]; then
      break
    fi
  done

  printf '%s' "$TASK_JSON" > "$PER_FILE"
  if [[ "$STATUS" == "success" || "$STATUS" == "completed" ]]; then
    echo "  -> success ($WAITED s)" | tee -a "$LOG_FILE"
    OK=$((OK + 1))
  elif [[ "$STATUS" == "failed" || "$STATUS" == "error" ]]; then
    ERR=$(printf '%s' "$TASK_JSON" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get('error') or '')[:200])
except Exception:
    pass
")
    echo "  -> failed: $ERR" | tee -a "$LOG_FILE"
    FAIL=$((FAIL + 1))
  else
    echo "  -> timeout after $POLL_TIMEOUT s, status=$STATUS" | tee -a "$LOG_FILE"
    FAIL=$((FAIL + 1))
  fi

  # tiny breath between accounts so server can settle the playwright lock
  sleep 2
done

SUMMARY=$(python3 -c "
import json
print(json.dumps({
    'total': $TOTAL,
    'success': $OK,
    'failed_or_timeout': $FAIL,
    'skipped': $SKIP,
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
