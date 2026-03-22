#!/usr/bin/env bash
# run_market.sh — Master Orchestrator for Live Trading
# 
# Architecture:
#   1. Sub-agents generate signals → write to signals/pending/
#   2. This orchestrator runs every 60s via cron
#   3. Reads all pending signals (coalesced — 1 per symbol)
#   4. Places orders via Groww API (single connection = no rate limits)
#   5. Marks signals processed
#
# Cron setup:
#   crontab -e
#   * * * * * cd /home/node/workspace/trade-project/deploy && python3 run_market.sh >> logs/market.log 2>&1

set -e

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"

LOG_DIR="$DEPLOY_DIR/logs"
SIGNAL_DIR="$DEPLOY_DIR/signals/pending"
MARKET_LOG="$LOG_DIR/market.log"

# Ensure directories exist
mkdir -p "$LOG_DIR" "$SIGNAL_DIR"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$MARKET_LOG"
}

log "========================================="
log "MARKET ORCHESTRATOR — $(date '+%Y-%m-%d %H:%M:%S %Z')"
log "========================================="

# Check if market is open (9:15 AM - 3:30 PM IST, Mon-Fri)
HOUR=$(date -u '+%H')
MINUTE=$(date -u '+%M')
DAY=$(date -u '+%u')  # 1=Mon ... 7=Sun

# Convert to IST approximate (UTC+5:30)
IST_HOUR=$((10#$HOUR + 5))
IST_MIN=$((10#$MINUTE + 30))
if [ $IST_MIN -ge 60 ]; then
    IST_HOUR=$((IST_HOUR + 1))
    IST_MIN=$((IST_MIN - 60))
fi

log "IST time: ${IST_HOUR}:${IST_MIN}"

# Market hours: 9:15 to 15:30 IST
MARKET_OPEN=false
if [ $IST_HOUR -ge 9 ]; then
    if [ $IST_HOUR -eq 9 ] && [ $IST_MIN -lt 15 ]; then
        MARKET_OPEN=false
    elif [ $IST_HOUR -lt 15 ]; then
        MARKET_OPEN=true
    elif [ $IST_HOUR -eq 15 ] && [ $IST_MIN -le 30 ]; then
        MARKET_OPEN=true
    fi
fi

# Weekend
if [ "$DAY" -ge 6 ]; then
    MARKET_OPEN=false
fi

if [ "$MARKET_OPEN" = false ]; then
    log "Market closed (IST: ${IST_HOUR}:${IST_MIN}, Day: $DAY) — skipping"
    exit 0
fi

log "Market OPEN — processing signals"

# Step 1: Run the orchestrator (signal processing + Groww API)
python3 run_master.sh

# Step 2: Log open positions
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from signals.orchestrator import GrowwAPI
    gw = GrowwAPI()
    if gw.key:
        pos = gw.positions()
        if pos:
            print('OPEN POSITIONS:')
            for p in pos:
                print(f'  {p.get(\"symbol\")} {p.get(\"quantity\")}x @ {p.get(\"price\")}')
        else:
            print('No open positions')
    else:
        print('Paper mode — no API key set')
except Exception as e:
    print(f'Position check: {e}')
" >> "$MARKET_LOG" 2>&1

# Step 3: Context compaction check (every 5 minutes)
CONTEXT_LOG="$LOG_DIR/context_log.jsonl"
if [ -f "$CONTEXT_LOG" ]; then
    SIZE=$(stat -c%s "$CONTEXT_LOG" 2>/dev/null || stat -f%z "$CONTEXT_LOG" 2>/dev/null || echo 0)
    SIZE_MB=$((SIZE / 1024 / 1024))
    if [ "$SIZE_MB" -ge 1 ]; then
        log "Context compaction needed ($SIZE_MB MB) — triggering..."
        python3 signals/context_compactor.py >> "$MARKET_LOG" 2>&1
    fi
fi

log "Orchestrator cycle complete"
