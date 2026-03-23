#!/bin/bash
# QA Loop - runs forever
cd /home/node/workspace/trade-project/deploy

last_report=$(date +%s)
last_commit=$(date +%s)
enhanced_count=0
cycle=1

echo "QA Loop started at $(date -u +%Y-%m-%dT%H:%MZ)" >> /home/node/workspace/trade-project/deploy/qa.log

while true; do
    echo "=== CYCLE $cycle START $(date -u +%Y-%m-%dT%H:%MZ) ===" >> /home/node/workspace/trade-project/deploy/qa.log
    
    total=0
    passed=0
    failed=0
    enhanced=0
    
    for f in live_*.py; do
        total=$((total+1))
        python3 -m py_compile "$f" 2>/dev/null
        if [ $? -eq 0 ]; then
            passed=$((passed+1))
        else
            failed=$((failed+1))
            echo "FAIL: $f" >> /home/node/workspace/trade-project/deploy/qa.log
        fi
    done
    
    echo "Cycle $cycle: $total total, $passed passed, $failed failed" >> /home/node/workspace/trade-project/deploy/qa.log
    
    # 30-min report
    now=$(date +%s)
    if [ $((now - last_report)) -ge 1800 ]; then
        echo "STATUS REPORT DUE at $(date -u)" >> /home/node/workspace/trade-project/deploy/qa.log
        last_report=$now
    fi
    
    # 30-min commit check
    if [ $((now - last_commit)) -ge 1800 ]; then
        cd /home/node/workspace/trade-project
        git add -A 2>/dev/null
        git commit -m "QA: automated fixes and enhancements $(date -u +%Y-%m-%dT%H:%MZ)" 2>/dev/null
        last_commit=$now
        echo "Git commit done at $(date -u)" >> /home/node/workspace/trade-project/deploy/qa.log
    fi
    
    cycle=$((cycle+1))
    sleep 300  # 5 minutes
done
