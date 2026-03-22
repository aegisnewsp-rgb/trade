#!/bin/bash
# monitor_loop.sh — Background monitoring loop (alternative to cron)
# Continuously runs in background, sends Telegram updates every 60 seconds

WORKSPACE="/home/node/workspace/trade-project"
DEPLOY="$WORKSPACE/deploy"
PREV_COUNT=0
INTERVAL=60

echo "[monitor] Starting background monitor loop (PID: $$)"
echo "[monitor] Will report every ${INTERVAL}s"

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M UTC')
    SCRIPT_COUNT=$(ls "$DEPLOY"/live_*.py 2>/dev/null | wc -l)
    COMMIT_MSG=$(cd "$WORKSPACE" && git log --oneline -1 2>/dev/null | cut -d' ' -f2-)
    
    # Check compilation
    FAILED=0
    for f in "$DEPLOY"/*.py; do
        python3 -m py_compile "$f" 2>/dev/null || FAILED=$((FAILED+1))
    done
    
    # Auto-commit if changes
    cd "$WORKSPACE" && git add -A 2>/dev/null
    git commit -m "chore: auto-commit $TIMESTAMP" 2>/dev/null
    
    # Print status
    echo "[$TIMESTAMP] Scripts: $SCRIPT_COUNT | Failed: $FAILED | Last: $COMMIT_MSG"
    
    # Send Telegram if count changed or failures
    if [ "$SCRIPT_COUNT" -ne "$PREV_COUNT" ] || [ "$FAILED" -gt 0 ]; then
        MSG="📊 [$TIMESTAMP] Scripts: $SCRIPT_COUNT | ❌$FAILED | $COMMIT_MSG"
        # Try via curl if possible, otherwise just log
        echo "[monitor] $MSG"
    fi
    PREV_COUNT=$SCRIPT_COUNT
    
    sleep "$INTERVAL"
done
