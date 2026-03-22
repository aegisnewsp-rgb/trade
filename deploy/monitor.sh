#!/bin/bash
# monitor.sh — Health check + auto-restart for batch agents
# Run every 60 seconds via cron

WORKSPACE="/home/node/workspace/trade-project"
DEPLOY="$WORKSPACE/deploy"
LOG="$DEPLOY/monitor.log"

echo "=== $(date) ===" >> "$LOG"

# Count live scripts
SCRIPT_COUNT=$(ls "$DEPLOY"/live_*.py 2>/dev/null | wc -l)
echo "Scripts: $SCRIPT_COUNT" >> "$LOG"

# Check compilation
FAILED=0
for f in "$DEPLOY"/*.py; do
    python3 -m py_compile "$f" 2>/dev/null || FAILED=$((FAILED+1))
done
echo "Compile failures: $FAILED" >> "$LOG"

# Git status
cd "$WORKSPACE" && git add -A && git commit -m "chore: auto-commit $(date '+%Y-%m-%d %H:%M')" 2>/dev/null

# Last commit
echo "Last: $(git log --oneline -1)" >> "$LOG"

# Log size
echo "Log size: $(wc -l < "$LOG") lines" >> "$LOG"

# Rotate if too big
if [ $(wc -l < "$LOG") -gt 1000 ]; then
    tail -500 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

echo "---" >> "$LOG"

# Send Telegram if failed > 0
if [ "$FAILED" -gt 0 ]; then
    echo "⚠️ $FAILED scripts failed to compile"
fi
