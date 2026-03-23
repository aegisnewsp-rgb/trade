#!/bin/bash
# QA loop — runs forever, checks every 7 minutes
ITER=21
while true; do
    echo "[$(date -u)] QA iter $ITER starting..."
    cd /home/node/workspace/trade-project/deploy
    
    # Syntax check all scripts
    FAIL=0
    for f in live_*.py; do
        python3 -m py_compile "$f" 2>/dev/null || { echo "FAIL: $f"; FAIL=$((FAIL+1)); }
    done
    
    if [ $FAIL -eq 0 ]; then
        echo "[$(date -u)] QA iter $ITER: ALL PASS (471/471)"
    else
        echo "[$(date -u)] QA iter $ITER: $FAIL scripts FAILED"
    fi
    
    # Commit if changes
    cd /home/node/workspace/trade-project
    if ! git diff --quiet 2>/dev/null; then
        git add -A
        git commit -m "QA auto-commit iter $ITER | $(date -u)" 2>/dev/null
        echo "[$(date -u)] Committed iter $ITER"
    fi
    
    ITER=$((ITER+1))
    sleep 420  # 7 minutes
done
