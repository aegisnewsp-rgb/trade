#!/usr/bin/env python3
"""
Proper Multi-Factor Backtester
- Fetches 6mo historical OHLCV from yfinance
- Simulates exact strategy: VWAP + RSI + Volume + ATR stops
- Computes: win rate, Sharpe ratio, max drawdown, total return
- Runs on all 40 stocks in pool
"""
import yfinance as yf
import json
import time
import math
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
RESULTS_DIR = WORKSPACE / "research" / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

POOL = [
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "RELIANCE", "TCS",
    "SBIN", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA",
    "CIPLA", "SRF", "IGL", "BANKINDIA", "NESTLEIND",
    "MARUTI", "HINDALCO", "HCLTECH", "HEROMOTOCO", "M&M",
    "KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
    "NTPC", "POWERGRID", "ONGC", "GAIL", "BPCL",
    "ITC", "HINDUNILVR", "BRITANNIA", "DMART", "VEDL",
    "INFY", "WIPRO", "TECHM", "SUNPHARMA", "DRREDDY",
]

POSITION_SIZE = 10000
RISK_PER_TRADE = 0.008   # 0.8% stop loss
TARGET_MULT = 4.0         # 4x ATR target
TSL_TRIGGER = 1.5        # Activate trailing stop after 1.5x ATR profit
TSL_DIST = 0.3           # 0.3x ATR trailing distance

def calc_vwap(ohlcv):
    if not ohlcv:
        return 0, []
    cum_tp_vol, cum_vol = 0.0, 0.0
    vwaps = []
    for row in ohlcv:
        o, h, l, c, v = row
        tp = (o + h + l + c) / 4.0 * v
        cum_tp_vol += tp
        cum_vol += v
        vwaps.append(cum_tp_vol / cum_vol if cum_vol > 0 else c)
    return vwaps[-1] if vwaps else 0, vwaps

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    rsis = [50.0] * period
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    for i in range(period, len(closes)):
        gains = [d for d in deltas[i-period:i] if d > 0]
        losses = [-d for d in deltas[i-period:i] if d < 0]
        ag = sum(gains) / period
        al = sum(losses) / period
        rsis.append(50.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al)))
    return rsis

def calc_atr(ohlcv, period=14):
    if len(ohlcv) < period + 1:
        return [0.0] * len(ohlcv)
    trs = [0.0] * (period + 1)
    for i in range(2, len(ohlcv)):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # EMA-style ATR
    atr = sum(trs[-period:]) / period
    atrs = [atr] * len(ohlcv)
    for i in range(period + 1, len(ohlcv)):
        atr = (atr * (period - 1) + trs[i]) / period
        atrs[i] = atr
    return atrs

def sma(closes, period):
    if len(closes) < period:
        return [None] * len(closes)
    smas = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        smas.append(sum(closes[i-period+1:i+1]) / period)
    return smas

def vol_ratio(ohlcv, period=20):
    if len(ohlcv) < period + 1:
        return [1.0] * len(ohlcv)
    vrs = [1.0] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        avg = sum(row[4] for row in ohlcv[i-period:i]) / period
        vrs[i] = ohlcv[i][4] / avg if avg > 0 else 1.0
    return vrs

def market_regime(closes, period=20):
    """Returns "UPTREND", "DOWNTREND", or "RANGE" based on price vs SMA20"""
    if len(closes) < period + 1:
        return "RANGE"
    sma20 = sum(closes[-period:]) / period
    ratio = closes[-1] / sma20 if sma20 > 0 else 1.0
    if ratio > 1.02:
        return "UPTREND"
    elif ratio < 0.98:
        return "DOWNTREND"
    return "RANGE"

def backtest_symbol(symbol, print_progress=False):
    try:
        ticker = yf.Ticker(symbol + ".NS")
        d = ticker.history(period="6mo")
        if len(d) < 60:
            return None
        
        ohlcv = [[float(r['Open']), float(r['High']), float(r['Low']),
                  float(r['Close']), float(r['Volume'])] for _, r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        
        vwap_cur, vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        atrs = calc_atr(ohlcv)
        vrs = vol_ratio(ohlcv)
        closes_sma = sma(closes, 20)
        regime = market_regime(closes)
        
        # Trading simulation
        trades = []
        position = None  # None or {"side": "BUY"/"SELL", "entry": float, "atr": float, "qty": int, "peak": float}
        daily_returns = []
        portfolio = 100000.0
        
        for i in range(25, len(closes) - 5):
            date = d.index[i].date()
            price = closes[i]
            vwap = vwaps[i]
            rsi = rsis[i]
            atr = atrs[i]
            vr = vrs[i]
            reg = market_regime(closes[:i+1])
            
            if position is None:
                # Check entry
                if reg != "DOWNTREND":
                    vr_thresh = 1.5 if reg == "RANGE" else 1.2
                    if (price > vwap * 1.005 and rsi > 55.0 and vr > vr_thresh):
                        qty = max(1, POSITION_SIZE // price)
                        sl = price - atr * RISK_PER_TRADE * 100 if RISK_PER_TRADE < 1 else price - atr * RISK_PER_TRADE
                        position = {"side": "BUY", "entry": price, "atr": atr, "qty": qty, "peak": price, "sl": sl}
                    elif (price < vwap * 0.995 and rsi < 45.0 and vr > vr_thresh):
                        qty = max(1, POSITION_SIZE // price)
                        sl = price + atr * RISK_PER_TRADE * 100 if RISK_PER_TRADE < 1 else price + atr * RISK_PER_TRADE
                        position = {"side": "SELL", "entry": price, "atr": atr, "qty": qty, "peak": price, "sl": sl}
            else:
                # Check exit
                pnl = 0
                exited = False
                reason = ""
                if position["side"] == "BUY":
                    # Update peak
                    position["peak"] = max(position["peak"], price)
                    # Target check
                    target_price = position["entry"] + position["atr"] * TARGET_MULT
                    if price >= target_price:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "TGT"
                    # Stop loss
                    elif price <= position["sl"]:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "SL"
                    # Trailing stop
                    elif pnl == 0:
                        trail = position["peak"] - position["atr"] * TSL_DIST
                        if price <= trail:
                            pnl = (price - position["entry"]) * position["qty"]
                            exited, reason = True, "TSL"
                else:  # SELL
                    position["peak"] = min(position["peak"], price)
                    target_price = position["entry"] - position["atr"] * TARGET_MULT
                    if price <= target_price:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "TGT"
                    elif price >= position["sl"]:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "SL"
                    elif pnl == 0:
                        trail = position["peak"] + position["atr"] * TSL_DIST
                        if price >= trail:
                            pnl = (position["entry"] - price) * position["qty"]
                            exited, reason = True, "TSL"
                
                if exited:
                    portfolio += pnl
                    ret_pct = pnl / (position["entry"] * position["qty"]) * 100
                    daily_returns.append(ret_pct)
                    trades.append({
                        "date": str(date),
                        "side": position["side"],
                        "entry": position["entry"],
                        "exit": price,
                        "pnl": pnl,
                        "return_pct": ret_pct,
                        "reason": reason,
                    })
                    position = None
        
        if len(trades) < 3:
            return None
        
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        wr = len(wins) / len(trades) * 100
        
        total_return = sum(t["pnl"] for t in trades)
        total_invested = POSITION_SIZE * len(trades)
        avg_return = total_return / total_invested * 100
        
        # Max drawdown
        running = 100000.0
        peak = 100000.0
        max_dd = 0.0
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
            dd = (peak - running) / peak * 100
            max_dd = max(max_dd, dd)
        
        # Sharpe ratio (simplified)
        if daily_returns and len(daily_returns) > 1:
            mean_ret = sum(daily_returns) / len(daily_returns)
            std_ret = math.sqrt(sum((r - mean_ret)**2 for r in daily_returns) / len(daily_returns)) if len(daily_returns) > 1 else 1.0
            sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0
        
        return {
            "symbol": symbol,
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr, 1),
            "total_return": round(total_return, 0),
            "avg_return_pct": round(avg_return, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "best_trade": round(max(t["pnl"] for t in trades), 0),
            "worst_trade": round(min(t["pnl"] for t in trades), 0),
            "regime": regime,
            "data_points": len(closes),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

if __name__ == "__main__":
    print(f"=== PROPER BACKTEST ===")
    print(f"Stocks: {len(POOL)}")
    print(f"Period: 6 months OHLCV")
    print(f"Strategy: VWAP + RSI + Volume + ATR-based exits")
    print(f"Position: Rs{POSITION_SIZE:,} per trade")
    print()
    
    results = []
    for i, sym in enumerate(POOL):
        print(f"[{i+1}/{len(POOL)}] {sym}...", end=" ", flush=True)
        r = backtest_symbol(sym)
        if r:
            if "error" in r:
                print(f"ERROR: {r['error']}")
            else:
                print(f"WR={r['win_rate']}% trades={r['trades']} sharpe={r['sharpe_ratio']} dd={r['max_drawdown_pct']}%")
                results.append(r)
        else:
            print(f"No data")
        time.sleep(0.1)  # Be nice to yfinance
    
    # Sort by win rate
    results.sort(key=lambda x: x["win_rate"], reverse=True)
    
    # Save full results
    out = RESULTS_DIR / "proper_backtest.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n=== RESULTS ({len(results)} stocks with ≥3 trades) ===")
    print(f"{'Rank':<4} {'Symbol':<15} {'WR%':>5} {'Trades':>6} {'Sharpe':>6} {'MaxDD%':>7} {'Return%':>8} {'Best':>8} {'Worst':>8}")
    print("-" * 80)
    for i, r in enumerate(results):
        print(f"{i+1:<4} {r['symbol']:<15} {r['win_rate']:>5.1f} {r['trades']:>6} {r['sharpe_ratio']:>6.2f} {r['max_drawdown_pct']:>7.2f} {r['avg_return_pct']:>8.3f} {r['best_trade']:>8.0f} {r['worst_trade']:>8.0f}")
    
    print(f"\nSaved: {out}")
    
    # Summary
    top = results[:10]
    avg_wr = sum(r["win_rate"] for r in results) / len(results)
    print(f"\nTop 10: {[r['symbol'] for r in top]}")
    print(f"Average win rate: {avg_wr:.1f}%")
    print(f"Best: {results[0]['symbol']} ({results[0]['win_rate']}%)")
    print(f"Worst: {results[-1]['symbol']} ({results[-1]['win_rate']}%)")
