#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

mkdir -p .autoteam-hook/logs .autoteam-hook/runtime

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

CRON_CMD="*/10 * * * * cd $ROOT_DIR && $PYTHON_BIN tools/codex-hook/check_and_invoke.py >> $ROOT_DIR/.autoteam-hook/logs/cron.stdout.log 2>&1 # AUTOTEAM_CODEX_MONITOR"
TMP_FILE="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'AUTOTEAM_CODEX_MONITOR' > "$TMP_FILE" || true
printf '%s\n' "$CRON_CMD" >> "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"

$PYTHON_BIN - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path("src").resolve()))
from autoteam.codex_hook import INSTALL_LOG, log_line, update_campaign_config

update_campaign_config(cron_installed=True)
update_campaign_config(interval_minutes=10)
log_line(INSTALL_LOG, "cron installed: every 10 minutes")
PY

echo "installed cron monitor"
