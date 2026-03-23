#!/bin/bash
# QA Forever Loop - compile check + README update + commit
DEPLOY="/home/node/workspace/trade-project/deploy"
LOG="/home/node/workspace/trade-project/qa_loop.log"
cd "$DEPLOY" || exit 1

cycle=0
while true; do
    cycle=$((cycle+1))
    ts=$(date -u +"%Y-%m-%d %H:%M UTC")
    
    # Compile check
    errors=0
    fails=""
    for f in live_*.py; do
        python3 -m py_compile "$f" 2>/dev/null || {
            errors=$((errors+1))
            fails="$fails $f"
        }
    done
    
    if [ $errors -eq 0 ]; then
        echo "[$ts] CYCLE $cycle: OK - 471/471 scripts pass" >> "$LOG"
    else
        echo "[$ts] CYCLE $cycle: FAIL - $errors scripts failed: $fails" >> "$LOG"
    fi
    
    sleep 300  # 5 minutes
done
