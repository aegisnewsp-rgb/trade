#!/bin/bash
# install.sh — Groww Cloud Deployment Setup
# Run this on your Groww Cloud VM

set -e

WORKSPACE="/home/node/trading-bot"
DEPLOY="$WORKSPACE/deploy"

echo "📦 Installing trading bot on Groww Cloud..."

# Create workspace
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# Clone or pull repo
if [ -d ".git" ]; then
    echo "📥 Pulling latest changes..."
    git pull
else
    echo "📥 Cloning repo..."
    git clone https://github.com/aegisnewsp-rgb/trade.git .
fi

cd "$DEPLOY"

# Install Python dependencies
echo "📚 Installing dependencies..."
pip3 install yfinance requests numpy scipy --quiet

# Create directories
mkdir -p logs state

# Set environment variables
if [ -z "$GROWW_API_KEY" ]; then
    echo "⚠️  Set GROWW_API_KEY and GROWW_API_SECRET environment variables:"
    echo "    export GROWW_API_KEY='your_key'"
    echo "    export GROWW_API_SECRET='your_secret'"
fi

# Add to crontab
CRON_COMMANDS="
# Pre-market scan (8:30 AM IST, weekdays)
30 8 * * 1-5 cd $DEPLOY && python3 premarket_check.py >> logs/premarket.log 2>&1

# Market open (9:00 AM IST, weekdays)
0 9 * * 1-5 cd $DEPLOY && ./run_market.sh top5 >> logs/market_open.log 2>&1

# Mid-day check (12:30 PM IST)
30 12 * * 1-5 cd $DEPLOY && python3 master_scanner.py --top 5 >> logs/scanner.log 2>&1

# Post-market (15:30 IST = 10:00 UTC, weekdays)
0 10 * * 1-5 cd $DEPLOY && python3 session_manager.py --mode post-market >> logs/postmarket.log 2>&1
"

# Install crontab (comment out existing, add new)
echo "⏰ Setting up cron jobs..."
(crontab -l 2>/dev/null | grep -v "trading-bot"; echo "$CRON_COMMANDS") | crontab -

echo "✅ Installation complete!"
echo ""
echo "Verify with: crontab -l"
echo "Check logs:  ls $DEPLOY/logs/"
echo "Run manually: cd $DEPLOY && python3 live_RELIANCE.py"
