#!/bin/bash
# QA Monitor - Continuous monitoring for trade-project
# Run forever until stopped

WORKSPACE="/home/node/workspace/trade-project"
DEPLOY="$WORKSPACE/deploy"
LOG="$DEPLOY/qa_monitor.log"
TELEGRAM_CHAT_ID="-1002381931352"

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

send_telegram() {
    # Try to send Telegram if configured
    :
}

log_msg "=== QA Monitor Started ==="
log_msg "Script count: $(ls "$DEPLOY"/live_*.py 2>/dev/null | wc -l)"

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Compile check
    FAILED=0
    for f in "$DEPLOY"/live_*.py; do
        python3 -m py_compile "$f" 2>/dev/null || FAILED=$((FAILED+1))
    done
    
    # Git commit
    cd "$WORKSPACE"
    git add -A 2>/dev/null
    git commit -m "chore: auto-commit $TIMESTAMP" 2>/dev/null
    
    # Log status
    log_msg "Compilation: failed=$FAILED, scripts=$(ls "$DEPLOY"/live_*.py 2>/dev/null | wc -l)"
    
    # Check last commit
    LAST_COMMIT=$(git log --oneline -1)
    log_msg "Last commit: $LAST_COMMIT"
    
    # Rotate log if too big
    if [ -f "$LOG" ] && [ $(wc -l < "$LOG") -gt 1000 ]; then
        tail -500 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
        log_msg "Log rotated"
    fi
    
    # Wait 5 minutes before next check
    sleep 300
done
