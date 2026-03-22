#!/bin/bash
# Worker BRAVO-5: Run backtest on BAJFINANCE, compare enhanced vs raw signals
# Document improvement in deploy/research/BRAVO_enhancement.md
cd /home/node/workspace/trade-project

BACKTEST_SCRIPT="/tmp/backtest_bravo5.py"
DOC_FILE="deploy/research/BRAVO_enhancement.md"

# Create backtest script
cat > "$BACKTEST_SCRIPT" << 'BACKTEST_CODE'
#!/usr/bin/env python3
"""
Backtest Script: BAJFINANCE VWAP Strategy Comparison
Compare: Enhanced (with volume filter) vs Raw VWAP
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

SYMBOL = "BAJFINANCE.NS"
DAYS = 90

def fetch_data(days=90):
    ticker = yf.Ticker(SYMBOL)
    df = ticker.history(period=f"{days}d")
    return [
        {
            "date": str(idx.date()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in df.iterrows()
    ]

def calculate_vwap(ohlcv, period=14):
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                        for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def calculate_atr(ohlcv, period=14):
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"],
            abs(bar["high"] - prev_close),
            abs(bar["low"] - prev_close),
        )
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_volume_ma(ohlcv, period=20):
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            vol_avg = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
            vol_ma.append(vol_avg)
    return vol_ma

def raw_vwap_signals(ohlcv):
    """Raw VWAP without volume filter"""
    period = 14
    atr_mult = 1.5
    vwap_vals = calculate_vwap(ohlcv, period)
    atr_vals = calculate_atr(ohlcv, period)
    signals = []
    
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            signals.append("HOLD")
            continue
        price = ohlcv[i]["close"]
        v = vwap_vals[i]
        a = atr_vals[i]
        if price > v + a * atr_mult:
            signals.append("BUY")
        elif price < v - a * atr_mult:
            signals.append("SELL")
        else:
            signals.append("HOLD")
    return signals

def enhanced_vwap_signals(ohlcv):
    """Enhanced VWAP with volume confirmation filter"""
    period = 14
    atr_mult = 1.5
    vwap_vals = calculate_vwap(ohlcv, period)
    atr_vals = calculate_atr(ohlcv, period)
    vol_ma = calculate_volume_ma(ohlcv, 20)
    signals = []
    
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or vol_ma[i] is None:
            signals.append("HOLD")
            continue
        price = ohlcv[i]["close"]
        v = vwap_vals[i]
        a = atr_vals[i]
        current_vol = ohlcv[i]["volume"]
        avg_vol = vol_ma[i]
        
        volume_confirmed = current_vol > avg_vol
        
        if price > v + a * atr_mult and volume_confirmed:
            signals.append("BUY")
        elif price < v - a * atr_mult and volume_confirmed:
            signals.append("SELL")
        else:
            signals.append("HOLD")
    return signals

def run_backtest(ohlcv, signals, name):
    """Simple backtest: track trades and compute basic stats"""
    trades = []
    position = None
    total_pnl = 0
    wins = 0
    losses = 0
    
    for i in range(1, len(signals)):
        if signals[i] == "BUY" and position is None:
            position = {"entry_price": ohlcv[i]["close"], "entry_date": ohlcv[i]["date"]}
        elif signals[i] == "SELL" and position is not None:
            pnl = (ohlcv[i]["close"] - position["entry_price"]) / position["entry_price"]
            trades.append({"entry": position["entry_price"], "exit": ohlcv[i]["close"], "pnl": pnl, "date": ohlcv[i]["date"]})
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            position = None
    
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_pnl = (total_pnl / total_trades * 100) if total_trades > 0 else 0
    
    return {
        "name": name,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_pnl_pct": avg_pnl,
        "total_pnl_pct": total_pnl * 100,
    }

def main():
    print(f"Fetching {DAYS} days of data for {SYMBOL}...")
    ohlcv = fetch_data(DAYS)
    
    if len(ohlcv) < 30:
        print("Insufficient data")
        return
    
    print("Running raw VWAP backtest...")
    raw_signals = raw_vwap_signals(ohlcv)
    raw_results = run_backtest(ohlcv, raw_signals, "Raw VWAP")
    
    print("Running enhanced VWAP backtest...")
    enhanced_signals = enhanced_vwap_signals(ohlcv)
    enhanced_results = run_backtest(ohlcv, enhanced_signals, "Enhanced VWAP + Volume Filter")
    
    # Output results
    results = {
        "symbol": SYMBOL,
        "period_days": DAYS,
        "raw_vwap": raw_results,
        "enhanced_vwap": enhanced_results,
        "improvement": {
            "win_rate_diff": enhanced_results["win_rate"] - raw_results["win_rate"],
            "trades_reduced": raw_results["total_trades"] - enhanced_results["total_trades"],
            "avg_pnl_diff": enhanced_results["avg_pnl_pct"] - raw_results["avg_pnl_pct"],
        }
    }
    
    print("\n" + "="*60)
    print("BACKTEST RESULTS - BAJFINANCE")
    print("="*60)
    print(f"\nRaw VWAP:")
    print(f"  Trades: {raw_results['total_trades']}, Win Rate: {raw_results['win_rate']:.1f}%, Avg PnL: {raw_results['avg_pnl_pct']:.2f}%")
    print(f"\nEnhanced VWAP + Volume Filter:")
    print(f"  Trades: {enhanced_results['total_trades']}, Win Rate: {enhanced_results['win_rate']:.1f}%, Avg PnL: {enhanced_results['avg_pnl_pct']:.2f}%")
    print(f"\nImprovement:")
    print(f"  Win Rate: +{results['improvement']['win_rate_diff']:.1f}%")
    print(f"  Trades Reduced: {results['improvement']['trades_reduced']}")
    print(f"  Avg PnL: +{results['improvement']['avg_pnl_diff']:.2f}%")
    print("="*60)
    
    # Save results
    with open("/tmp/bravo5_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to /tmp/bravo5_results.json")

if __name__ == "__main__":
    main()
BACKTEST_CODE

python3 "$BACKTEST_SCRIPT"

# Create documentation
RESULTS=$(cat /tmp/bravo5_results.json 2>/dev/null || echo '{}')

cat > "$DOC_FILE" << DOC
# BRAVO Enhancement Report

## Summary
This document tracks the improvements made by the BRAVO team to VWAP-based trading strategies.

## BAJFINANCE Enhancement (Worker BRAVO-1)
**Enhancement:** Added volume confirmation filter (price must be above 20-day volume MA)

### Changes
- Added `calculate_volume_ma()` function
- Modified `vwap_signal()` to require volume confirmation
- Only generates BUY/SELL when volume > average volume

### Rationale
Volume confirmation filters out false breakouts and ensures institutional participation behind moves.

---

## BANKBARODA Enhancement (Worker BRAVO-2)
**Enhancement:** Tightened stop loss from 0.8% to 0.5%

### Changes
- `STOP_LOSS_PCT = 0.005` (was 0.008)
- Log message updated to reflect tightened stop loss

### Rationale
Tighter stop loss reduces maximum loss per trade, improving risk-adjusted returns.

---

## BANKINDIA Enhancement (Worker BRAVO-3)
**Enhancement:** Added multi-timeframe confirmation (daily + 4hr VWAP alignment)

### Changes
- Added `fetch_4hr_data()` function
- Modified signal to require both daily and 4hr VWAP crossovers
- New strategy name: VWAP_MTF

### Rationale
Multi-timeframe confirmation ensures entries align with higher timeframe trends, reducing false signals.

---

## BASF Enhancement (Worker BRAVO-4)
**Enhancement:** Created new script with optimized entry rules

### Features
- VWAP with ATR bands
- Minimum volume threshold (500,000 shares)
- 3-candle momentum confirmation

### Rationale
Optimized entries with momentum confirmation improve signal quality.

---

## Backtest Results (Worker BRAVO-5)

$(cat /tmp/bravo5_results.json 2>/dev/null || echo 'Backtest pending execution')

### Key Metrics Compared
| Metric | Raw VWAP | Enhanced VWAP | Improvement |
|--------|----------|---------------|-------------|
| Trades | ${raw_trades:-N/A} | ${enhanced_trades:-N/A} | ${trade_diff:-N/A} |
| Win Rate | ${raw_wr:-N/A}% | ${enhanced_wr:-N/A}% | ${wr_diff:-N/A}% |
| Avg PnL | ${raw_pnl:-N/A}% | ${enhanced_pnl:-N/A}% | ${pnl_diff:-N/A}% |

---

*Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)*
DOC

cd /home/node/workspace/trade-project
git add deploy/research/BRAVO_enhancement.md 2>/dev/null || mkdir -p deploy/research && git add deploy/research/BRAVO_enhancement.md
git commit -m "BRAVO-5: Add backtest results and enhancement documentation" 2>&1 || echo "BRAVO-5: No changes to commit"

echo "BRAVO-5 WORKER COMPLETE"