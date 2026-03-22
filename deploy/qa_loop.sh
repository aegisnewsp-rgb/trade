#!/bin/bash
# QA Forever Loop - runs until stopped
DEPLOY_DIR="/home/node/workspace/trade-project/deploy"
cd "$DEPLOY_DIR"
LOG_FILE="$DEPLOY_DIR/logs/qa_loop.log"
ITER=0

echo "🚀 QA LOOP STARTED at $(date -u)" >> "$LOG_FILE"

while true; do
  ITER=$((ITER + 1))
  TS=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
  
  # Count scripts
  SCRIPT_COUNT=$(ls live_*.py 2>/dev/null | wc -l)
  
  # Compile check
  FAIL=0
  for f in live_*.py; do
    python3 -m py_compile "$f" 2>&1 >> "$DEPLOY_DIR/logs/qa_compile.log" || FAIL=$((FAIL+1))
  done
  
  # Check for new scripts needing README update
  README_SCRIPT_COUNT=$(grep -c "live_" "$DEPLOY_DIR/README.md" 2>/dev/null || echo 0)
  
  # Update README if script count changed
  if [ "$SCRIPT_COUNT" != "$README_SCRIPT_COUNT" ]; then
    cat > "$DEPLOY_DIR/README.md" << README_EOF
# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (\`live_*.py\`) for automated trade execution.

**⚠️ NOTE:** The \`live_*.py\` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **$SCRIPT_COUNT live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked:** $TS
- **All $SCRIPT_COUNT scripts:** $([ $FAIL -eq 0 ] && echo "✅ Compiled successfully" || echo "❌ $FAIL failures")
- **Iteration:** #$ITER

## Enhancement Notes
Low win-rate scripts (benchmark data from manifest):
• ICICIBANK.NS: 57.30% (ADX_TREND)
• DABUR.NS: 57.32% (ADX_TREND)
• GRASIM.NS: 57.36% (FIBONACCI_RETRACEMENT)
• CHOLAFIN.NS: 57.49% (FIBONACCI_RETRACEMENT)
• BPCL.NS: 57.50% (VWAP)

Target: 70%+ win rate for all scripts
README_EOF
    echo "[$TS] README updated: $SCRIPT_COUNT scripts" >> "$LOG_FILE"
  fi
  
  # Commit README changes if any
  cd /home/node/workspace/trade-project
  git add deploy/README.md 2>/dev/null
  git commit -m "qa: auto-update README [$TS] - $SCRIPT_COUNT scripts, $FAIL failures" 2>/dev/null
  
  echo "[$TS] Iter #$ITER | Scripts: $SCRIPT_COUNT | Compile failures: $FAIL" >> "$LOG_FILE"
  
  # Sleep 5 minutes before next iteration
  sleep 300
done
