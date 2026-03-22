#!/bin/bash
# QA Loop - runs until stopped
DEPLOY="/home/node/workspace/trade-project/deploy"
cd "$DEPLOY"
echo "🔄 QA Loop started at $(date)"
while true; do
    echo "=== QA Run $(date) ==="
    
    # Compile check
    FAIL=0
    for f in live_*.py; do
        python3 -m py_compile "$f" 2>/dev/null || {
            echo "FAIL: $f"
            FAIL=$((FAIL+1))
        }
    done
    echo "Compile: $(ls live_*.py | wc -l) scripts, $FAIL failures"
    
    # Count scripts and update README if changed
    COUNT=$(ls live_*.py | wc -l)
    if ! grep -q "$COUNT live trading scripts" README.md 2>/dev/null; then
        sed -i "s/\*\*[0-9]* live trading scripts\*\*/\*\*$COUNT live trading scripts\*\*/" README.md
        git add -A && git commit -m "README: updated script count to $COUNT"
        echo "Updated README to $COUNT scripts"
    fi
    
    sleep 300  # 5 min between runs
done
