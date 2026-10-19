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

DEPS="import requests, pandas, google_play_scraper, steamspypi"
VENV="$PWD/.venv/bin/python"

can_run() { "$1" -c "$DEPS" >/dev/null 2>&1; }

say() { echo "$*" | tee -a "$LOG"; }

explain_broken() {
    # $1 = interpreter that cannot run the crawler
    say "=== ERROR: $1 cannot run the crawler ==="
    if ! "$1" -m pip --version >/dev/null 2>&1; then
        say ""
        say "This interpreter has no pip. On Debian/Ubuntu a venv is created"
        say "without pip unless python3-venv is installed:"
        say ""
        say "  sudo apt update && sudo apt install -y python3-venv python3-pip"
        say "  # Ubuntu 24.04+ : sudo apt install -y python3-venv python3-full"
        say ""
        say "  rm -rf .venv && python3 -m venv .venv"
        say "  .venv/bin/pip install -r requirements.txt"
        say ""
        say "Fallback without a venv:  python3 -m pip install --user -r requirements.txt"
        say "                          PYTHON=python3 ./run_crawl.sh"
    else
        say ""
        say "pip works but the dependencies are missing:"
        say ""
        say "  $1 -m pip install -r requirements.txt"
    fi
    say ""
    say "To use another interpreter:  PYTHON=/path/to/python ./run_crawl.sh"
    exit 3
}

# Interpreter selection: an explicit $PYTHON always wins, then the first
# candidate that can actually import the dependencies.
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
    can_run "$PY" || explain_broken "$PY"
elif [ -x "$VENV" ] && can_run "$VENV"; then
    PY="$VENV"
elif can_run "python3"; then
    PY="python3"
    if [ -x "$VENV" ]; then
        say "=== note: .venv/bin/python cannot import the dependencies, using python3 ==="
    fi
elif [ -x "$VENV" ]; then
    PY="$VENV"
    explain_broken "$PY"
else
    PY="python3"
    explain_broken "$PY"
fi

say "=== started $(date -Is) ==="
say "=== interpreter: $PY ($("$PY" -V 2>&1)) ==="
say "=== command: $PY -u crawl.py $* ==="

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