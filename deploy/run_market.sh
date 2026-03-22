#!/bin/bash
# run_market.sh — Run all scripts at market open (9:15 AM IST)
# Usage: ./run_market.sh [strategy]

DEPLOY_DIR="$(dirname "$0")"
LOG_DIR="$DEPLOY_DIR/logs"
mkdir -p "$LOG_DIR"

STRATEGY="${1:-all}"

echo "🚀 Starting market session at $(date)"
echo "📊 Strategy filter: $STRATEGY"

if [ "$STRATEGY" = "all" ]; then
    echo "Running ALL scripts..."
    for f in "$DEPLOY_DIR"/live_*.py; do
        SYMBOL=$(basename "$f" .py | sed 's/live_//; s/_NS//; s/_BO//')
        LOGFILE="$LOG_DIR/run_${SYMBOL}_$(date +%Y%m%d_%H%M%S).log"
        echo "  → $SYMBOL"
        python3 "$f" > "$LOGFILE" 2>&1 &
    done
elif [ "$STRATEGY" = "top5" ]; then
    echo "Running TOP 5 scripts..."
    for SYMBOL in RELIANCE TCS SBIN TITAN HDFCBANK; do
        f="$DEPLOY_DIR/live_${SYMBOL}.py"
        [ -f "$f" ] && python3 "$f" &
    done
elif [ "$STRATEGY" = "vwap" ]; then
    echo "Running VWAP strategies only..."
    for f in "$DEPLOY_DIR"/live_*.py; do
        grep -q 'STRATEGY.*=.*"VWAP"' "$f" && python3 "$f" &
    done
fi

wait
echo "✅ All scripts completed at $(date)"
