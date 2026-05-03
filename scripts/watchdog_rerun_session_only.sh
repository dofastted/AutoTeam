#!/usr/bin/env bash
# Watch cpa-batch run 6cd96d6df18a; once it leaves running/pending,
# launch codex exec to re-run scripts/backfill_session_only_oauth.sh.
# Single-shot: runs the trigger at most once, then exits.
#
# Logs: .tmp/watchdog-rerun-A.log
# State: .tmp/watchdog-rerun-A.pid, .tmp/watchdog-rerun-A.state
#
# Hard cap: 24h (POLL_MAX_SECONDS). Override via env if needed.

set -u -o pipefail

cd "$(dirname "$0")/.."

RUN_ID="${RUN_ID:-6cd96d6df18a}"
API_BASE="${API_BASE:-http://127.0.0.1:8788}"
POLL_INTERVAL="${POLL_INTERVAL:-60}"
POLL_MAX_SECONDS="${POLL_MAX_SECONDS:-86400}"
LOG=".tmp/watchdog-rerun-A.log"
STATE=".tmp/watchdog-rerun-A.state"
A_PROMPT=".tmp/codex-runs/rerun-A-only.prompt.md"

if [[ ! -f .env ]]; then
  echo "error: .env not found" >&2
  exit 1
fi
API_KEY=$(grep -E '^API_KEY=' .env | cut -d= -f2-)
if [[ -z "$API_KEY" ]]; then
  echo "error: API_KEY missing" >&2
  exit 1
fi

mkdir -p .tmp/codex-runs
echo "[$(date +%F\ %T)] watchdog start run_id=$RUN_ID poll=${POLL_INTERVAL}s cap=${POLL_MAX_SECONDS}s" | tee -a "$LOG"

WAITED=0
LAST_STATUS=""
while (( WAITED < POLL_MAX_SECONDS )); do
  RESP=$(curl -sS --max-time 15 -H "Authorization: Bearer $API_KEY" \
    "$API_BASE/api/cpa-batch/runs/$RUN_ID" 2>/dev/null || echo '{}')
  STATUS=$(printf '%s' "$RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get('status') or '').strip())
except Exception:
    pass
" 2>/dev/null)

  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    echo "[$(date +%F\ %T)] status=$STATUS waited=${WAITED}s" | tee -a "$LOG"
    LAST_STATUS="$STATUS"
    printf '%s' "$STATUS" > "$STATE"
  fi

  case "$STATUS" in
    running|pending|"")
      sleep "$POLL_INTERVAL"
      WAITED=$((WAITED + POLL_INTERVAL))
      continue
      ;;
    *)
      echo "[$(date +%F\ %T)] B left running with status=$STATUS, launching A" | tee -a "$LOG"
      break
      ;;
  esac
done

if (( WAITED >= POLL_MAX_SECONDS )); then
  echo "[$(date +%F\ %T)] watchdog cap reached, B still in $LAST_STATUS, NOT launching A" | tee -a "$LOG"
  exit 2
fi

# Double-check no running cpa-batch task remains
TASKS=$(curl -sS --max-time 15 -H "Authorization: Bearer $API_KEY" "$API_BASE/api/tasks" 2>/dev/null || echo '[]')
RUNNING=$(printf '%s' "$TASKS" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    blockers=[t for t in d if (t.get('status')=='running' and (t.get('command') or '').startswith(('cpa-batch','cpa-auth')))]
    print(len(blockers))
except Exception:
    print(0)
" 2>/dev/null)
if [[ "$RUNNING" != "0" ]]; then
  echo "[$(date +%F\ %T)] still $RUNNING blocker tasks running; aborting A launch" | tee -a "$LOG"
  exit 3
fi

TS=$(date +%Y%m%d-%H%M%S)
CODEX_LOG=".tmp/codex-runs/rerun-A-only-${TS}.log"
CODEX_LAST=".tmp/codex-runs/rerun-A-only-${TS}.last_message"
echo "[$(date +%F\ %T)] codex exec → $CODEX_LOG" | tee -a "$LOG"

nohup codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  -C /mnt/x/project/AutoTeam \
  -o "$CODEX_LAST" \
  - < "$A_PROMPT" \
  > "$CODEX_LOG" 2>&1 &
CODEX_PID=$!
echo "[$(date +%F\ %T)] codex pid=$CODEX_PID" | tee -a "$LOG"
echo "$CODEX_PID" > .tmp/codex-runs/rerun-A-only.pid

# Wait for codex to finish, propagate exit code
wait $CODEX_PID
RC=$?
echo "[$(date +%F\ %T)] codex exit=$RC" | tee -a "$LOG"
exit "$RC"
