#!/bin/bash
# test_top5.sh — Test run top 5 scripts with ₹7K position
# Safe to run anytime (paper mode without API credentials)

DEPLOY_DIR="$(dirname "$0")"

echo "🧪 Testing Top 5 Trading Scripts"
echo "================================"
echo "Time: $(date)"
echo "Note: Without GROWW_API_KEY/SECRET, scripts will output signals only"
echo ""

for SYMBOL in RELIANCE TCS SBIN TITAN HDFCBANK; do
    f="$DEPLOY_DIR/live_${SYMBOL}.py"
    if [ -f "$f" ]; then
        echo "--- Testing $SYMBOL ---"
        python3 "$f" 2>&1 | tail -20
        echo ""
    else
        echo "⚠️  $SYMBOL script not found"
    fi
done

echo "✅ Test complete"
