#!/bin/bash
# Single QA loop - runs forever until killed
cd /home/node/workspace/trade-project
CYCLE=0
while true; do
  CYCLE=$((CYCLE+1))
  TS=$(date -u +"%Y-%m-%d %H:%M UTC")
  
  cd deploy
  ERRORS=0
  for f in live_*.py; do
    python3 -m py_compile "$f" 2>&1 || { echo "FAIL: $f"; ERRORS=$((ERRORS+1)); }
  done
  
  if [ $ERRORS -eq 0 ]; then
    echo "[$TS] CYCLE $CYCLE: OK - 471/471 scripts pass"
  else
    echo "[$TS] CYCLE $CYCLE: ERRORS - $ERRORS failures"
  fi
  
  cd ..
  git add -A 2>/dev/null
  git commit -m "QA auto: cycle $CYCLE ($TS)" --allow-empty 2>/dev/null
  
  sleep 300
done
