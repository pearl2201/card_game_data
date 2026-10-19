#!/usr/bin/env bash
#
# Unattended crawl + analysis, safe to run under nohup / tmux / systemd.
#
#   ./run_crawl.sh                          # defaults, all storefronts
#   ./run_crawl.sh --steam-enrich-limit 2000 --steam-budget 0
#   NO_ANALYZE=1 ./run_crawl.sh             # crawl only
#
# Logs to logs/crawl-<timestamp>.log
set -uo pipefail
cd "$(dirname "$0")"

LOG_DIR="${LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/crawl-$STAMP.log"

PYTHON="python3"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

echo "=== crawl started $(date -Is) ===" | tee -a "$LOG"
echo "=== command: $PYTHON -u crawl.py $* ===" | tee -a "$LOG"

# -u keeps output unbuffered so the log is readable while the crawl runs.
"$PYTHON" -u crawl.py "$@" >>"$LOG" 2>&1
status=$?

if [ "$status" -ne 0 ]; then
    echo "=== crawl exited with status $status $(date -Is) ===" | tee -a "$LOG"
    exit "$status"
fi

# An interrupted crawl returns 130; data on disk is still valid, so analyse it.
if [ "${NO_ANALYZE:-0}" != "1" ]; then
    echo "=== analysis started $(date -Is) ===" | tee -a "$LOG"
    "$PYTHON" -u analyze.py >>"$LOG" 2>&1 || echo "=== analysis failed (see log) ===" | tee -a "$LOG"
fi

echo "=== finished $(date -Is) ===" | tee -a "$LOG"
echo "Log: $LOG"
