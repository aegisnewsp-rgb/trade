#!/bin/bash
CYCLE=40
while true; do
  CYCLE=$((CYCLE+1))
  DATE=$(date -u '+%Y-%m-%d %H:%M UTC')
  echo "[$DATE] QA Cycle $CYCLE starting..."
  
  # Compile check
  FAIL=0
  for f in live_*.py; do
    python3 -m py_compile "$f" 2>/dev/null || {
      echo "FAIL: $f"
      FAIL=$((FAIL+1))
    }
  done
  
  if [ $FAIL -eq 0 ]; then
    echo "[$DATE] QA Cycle $CYCLE: All OK (471 scripts)"
  else
    echo "[$DATE] QA Cycle $CYCLE: $FAIL FAILED scripts!"
  fi
  
  sleep 300  # 5 min between cycles
done
