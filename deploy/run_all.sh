#!/bin/bash
# run_all.sh - Deploy all live trading scripts
# Usage: ./run_all.sh [symbol] (no args = run all)

DEPLOY_DIR="$(dirname "$0")"
LOG_DIR="$DEPLOY_DIR/logs"
mkdir -p "$LOG_DIR"

STOCKS="RELIANCE TCS SBIN TITAN HDFCBANK"

run_one() {
    SYMBOL=$1
    LOGFILE="$LOG_DIR/run_${SYMBOL}_$(date +%Y%m%d_%H%M%S).log"
    echo "🚀 Starting live_$SYMBOL.py at $(date)"
    python3 "$DEPLOY_DIR/live_${SYMBOL}.py" 2>&1 | tee "$LOGFILE"
    echo "✅ Finished live_$SYMBOL.py at $(date)"
}

if [ $# -gt 0 ]; then
    run_one "$1"
else
    for STOCK in $STOCKS; do
        if [ -f "$DEPLOY_DIR/live_${STOCK}.py" ]; then
            run_one "$STOCK" &
        else
            echo "⚠️ live_${STOCK}.py not found, skipping"
        fi
    done
    wait
fi

echo "🏁 All scripts completed at $(date)"
