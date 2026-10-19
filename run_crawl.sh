#!/usr/bin/env bash
#
# Unattended crawl + analysis, safe to run under nohup / screen / tmux / systemd.
#
#   ./run_crawl.sh                                  # defaults, all storefronts
#   ./run_crawl.sh --steam-enrich-limit 2000 --steam-budget 0
#   PYTHON=/opt/venv/bin/python ./run_crawl.sh      # force an interpreter
#   NO_ANALYZE=1 ./run_crawl.sh                     # crawl only
#
# Logs to logs/crawl-<timestamp>.log
set -uo pipefail
cd "$(dirname "$0")" || exit 1

LOG_DIR="${LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/crawl-$STAMP.log"

# Interpreter selection: $PYTHON wins, then a local .venv, then python3.
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

say() { echo "$*" | tee -a "$LOG"; }

say "=== started $(date -Is) ==="
say "=== interpreter: $PY ($("$PY" -V 2>&1)) ==="
say "=== command: $PY -u crawl.py $* ==="

# Fail fast with an actionable message rather than a bare traceback.
if ! "$PY" -c "import requests, pandas, google_play_scraper, steamspypi" 2>>"$LOG"; then
    say "=== ERROR: dependencies are missing for $PY ==="
    say "  Install them:      $PY -m pip install -r requirements.txt"
    say "  Or pick another:   PYTHON=/path/to/python ./run_crawl.sh"
    say "  If .venv is stale: rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 3
fi

"$PY" -u crawl.py "$@" >>"$LOG" 2>&1
status=$?

if [ "$status" -ne 0 ]; then
    say "=== crawl failed with status $status $(date -Is) ==="
    echo "--- last 30 lines of the log ---"
    tail -n 30 "$LOG" | sed "s/^/  /"
    echo "--------------------------------"
    say "Full log: $LOG"
    exit "$status"
fi

if [ "${NO_ANALYZE:-0}" != "1" ]; then
    say "=== analysis started $(date -Is) ==="
    if ! "$PY" -u analyze.py >>"$LOG" 2>&1; then
        say "=== analysis failed, see $LOG ==="
        exit 2
    fi
fi

say "=== finished $(date -Is) ==="
say "Log: $LOG"