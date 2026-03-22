#!/usr/bin/env python3
"""
Distributed Backtester — 50 competition stocks, rolling 99-stock window
Spawns 20 parallel subagents, each backtesting a batch of stocks.
Uses exact Groww-cached strategy: VWAP + RSI + Volume + ATR exits
"""
import sys, json, time, subprocess, os
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
RESULTS_DIR = WORKSPACE / "research" / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# All 50 competition stocks
COMPETITION_STOCKS = [
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "RELIANCE", "TCS",
    "SBIN", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA",
    "CIPLA", "SRF", "IGL", "BANKINDIA", "NESTLEIND",
    "MARUTI", "HINDALCO", "HCLTECH", "HEROMOTOCO", "M&M",
    "KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
    "NTPC", "POWERGRID", "ONGC", "GAIL", "BPCL",
    "ITC", "HINDUNILVR", "BRITANNIA", "DMART", "VEDL",
    "INFY", "WIPRO", "TECHM", "SUNPHARMA", "DRREDDY",
    "LT", "SHREECEM", "ULTRACEMCO", "BAJAJFINSV", "HDFCLIFE",
    "COFORGE", "DABUR", "APOLLOHOSP", "BLUEDART", "GAEL",
]

# Full pool of 99 stocks (for rolling window)
POOL_99 = [
    # Top performers + reserve pool
    "BPCL", "POWERGRID", "BANKINDIA", "HINDALCO", "TECHM", "SBIN", "INFY",
    "RELIANCE", "TCS", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA", "CIPLA",
    "SRF", "IGL", "NESTLEIND", "MARUTI", "HCLTECH", "HEROMOTOCO", "M&M",
    "KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
    "NTPC", "ONGC", "GAIL", "ITC", "HINDUNILVR", "BRITANNIA", "DMART", "VEDL",
    "WIPRO", "SUNPHARMA", "DRREDDY", "LT", "SHREECEM", "ULTRACEMCO",
    "BAJAJFINSV", "HDFCLIFE", "COFORGE", "DABUR", "APOLLOHOSP", "BLUEDART", "GAEL",
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "ADANIENT", "ADANIGREEN",
    "ASHOKLEY", "AUTOAXLES", "BOSCHLTD", "CRISIL", "CROMPTON", "DEEPAKNTR",
    "FORTIS", "GLENMARK", "GODREJPROP", "GODREJCP", "GRASIM", "HAVELLS",
    "HINDPETRO", "HINDZINC", "HONAUT", "IGIL", "JKCEMENT", "JUBLFOOD",
    "KOLTEPAT", "LUMAXIND", "MFSL", "MUTHOOTMF", "NATIONALUM", "NAVINFLUOR",
    "NESTLEIND", "NIITLTD", "NMDC", "NTPC", "OBEROI", "PAGEIND", "PERSISTENT",
    "PIIND", "POLYCAB", "PRESTIGE", "RECLTD", "SAIL", "SBIN", "SHRIRAMFIN",
    "SIEMENS", "SRF", "SUNTV", "TANLA", "TATACONSUM", "TATAELXSI", "TATAMOTORS",
    "TATAPOWER", "TCS", "TECHM", "TIINDIA", "TITAN", "TORNTPOWER", "TRENT",
    "TRITURBINE", "UNITECH", "UPL", "VEDL", "VINATIORGA", "VOLTAS", "WHIRLPOOL",
    "WIPRO", "ZEEL", "ZYDUSLIFE",
]

POSITION_SIZE = 10000
RISK_PER_TRADE = 0.008   # 0.8% stop loss
TARGET_MULT = 4.0         # 4x ATR target
TSL_TRIGGER = 1.5        # Activate trailing stop after 1.5x ATR profit
TSL_DIST = 0.3           # 0.3x ATR trailing distance


def calc_vwap(ohlcv):
    if not ohlcv:
        return [], []
    cum_tp_vol, cum_vol = 0.0, 0.0
    vwaps = []
    for row in ohlcv:
        o, h, l, c, v = row
        tp = (o + h + l + c) / 4.0 * v
        cum_tp_vol += tp
        cum_vol += v
        vwaps.append(cum_tp_vol / cum_vol if cum_vol > 0 else c)
    return vwaps[-1], vwaps


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
    if len(ohlcv) < period + 2:
        return [0.0] * len(ohlcv)
    trs = [0.0] * len(ohlcv)
    for i in range(2, len(ohlcv)):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs[i] = tr
    atrs = [0.0] * len(ohlcv)
    atrs[period] = sum(trs[1:period+1]) / period
    for i in range(period + 1, len(ohlcv)):
        atrs[i] = (atrs[i-1] * (period - 1) + trs[i]) / period
    return atrs


def vol_ratio(ohlcv, period=20):
    if len(ohlcv) < period + 1:
        return [1.0] * len(ohlcv)
    vrs = [1.0] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        avg = sum(row[4] for row in ohlcv[i-period:i]) / period
        vrs[i] = ohlcv[i][4] / avg if avg > 0 else 1.0
    return vrs


def market_regime(closes, period=20):
    if len(closes) < period + 1:
        return "RANGE"
    sma20 = sum(closes[-period:]) / period
    ratio = closes[-1] / sma20 if sma20 > 0 else 1.0
    if ratio > 1.02:
        return "UPTREND"
    elif ratio < 0.98:
        return "DOWNTREND"
    return "RANGE"


def backtest_symbol(symbol, pool_for_regime=None):
    """Backtest single symbol with full Groww strategy"""
    import yfinance as yf
    import math
    
    try:
        ticker = yf.Ticker(symbol + ".NS")
        d = ticker.history(period="3mo")
        if len(d) < 40:
            return None
        
        ohlcv = [[float(r['Open']), float(r['High']), float(r['Low']),
                  float(r['Close']), float(r['Volume'])] for _, r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        
        vwap_cur, vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        atrs = calc_atr(ohlcv)
        vrs = vol_ratio(ohlcv)
        
        trades = []
        position = None
        portfolio = 100000.0
        
        for i in range(25, len(closes) - 5):
            price = closes[i]
            vwap = vwaps[i]
            rsi = rsis[i]
            atr = atrs[i]
            vr = vrs[i]
            
            # Market regime check
            reg = market_regime(closes[:i+1])
            
            if position is None:
                if reg != "DOWNTREND":
                    vr_thresh = 1.5 if reg == "RANGE" else 1.2
                    if price > vwap * 1.005 and rsi > 55.0 and vr > vr_thresh:
                        qty = max(1, POSITION_SIZE // price)
                        sl = price - atr * RISK_PER_TRADE
                        position = {"side": "BUY", "entry": price, "atr": atr, "qty": qty, "peak": price, "sl": sl}
                    elif price < vwap * 0.995 and rsi < 45.0 and vr > vr_thresh:
                        qty = max(1, POSITION_SIZE // price)
                        sl = price + atr * RISK_PER_TRADE
                        position = {"side": "SELL", "entry": price, "atr": atr, "qty": qty, "peak": price, "sl": sl}
            else:
                pnl = 0
                exited = False
                reason = ""
                if position["side"] == "BUY":
                    position["peak"] = max(position["peak"], price)
                    target = position["entry"] + position["atr"] * TARGET_MULT
                    if price >= target:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "TGT"
                    elif price <= position["sl"]:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "SL"
                    elif (position["peak"] - position["entry"]) >= position["atr"] * TSL_TRIGGER:
                        trail = position["peak"] - position["atr"] * TSL_DIST
                        if price <= trail:
                            pnl = (price - position["entry"]) * position["qty"]
                            exited, reason = True, "TSL"
                else:
                    position["peak"] = min(position["peak"], price)
                    target = position["entry"] - position["atr"] * TARGET_MULT
                    if price <= target:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "TGT"
                    elif price >= position["sl"]:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "SL"
                
                if exited:
                    portfolio += pnl
                    trades.append({
                        "side": position["side"],
                        "entry": position["entry"],
                        "exit": price,
                        "pnl": pnl,
                        "reason": reason,
                    })
                    position = None
        
        if len(trades) < 2:
            return None
        
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        wr = len(wins) / len(trades) * 100
        
        total_return = sum(t["pnl"] for t in trades)
        returns_pct = [t["pnl"] / POSITION_SIZE * 100 for t in trades]
        avg_ret = sum(returns_pct) / len(returns_pct)
        
        # Max drawdown
        running = 100000.0
        peak = 100000.0
        max_dd = 0.0
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
            dd = (peak - running) / peak * 100
            max_dd = max(max_dd, dd)
        
        # Sharpe
        if len(returns_pct) > 1:
            mean_ret = sum(returns_pct) / len(returns_pct)
            std_ret = math.sqrt(sum((r - mean_ret)**2 for r in returns_pct) / len(returns_pct))
            sharpe = (mean_ret / std_ret * 15.9) if std_ret > 0 else 0.0  # ~sqrt(252)
        else:
            sharpe = 0.0
        
        return {
            "symbol": symbol,
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(wr, 1),
            "total_return": round(total_return, 0),
            "avg_return_pct": round(avg_ret, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "best_trade": round(max(t["pnl"] for t in trades), 0),
            "worst_trade": round(min(t["pnl"] for t in trades), 0),
            "regime_filtered": sum(1 for t in trades if "SL" not in t["reason"]),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def backtest_batch(batch):
    """Backtest a batch of symbols"""
    results = []
    for sym in batch:
        r = backtest_symbol(sym)
        if r:
            results.append(r)
        time.sleep(0.2)  # Rate limit
    return results


def main():
    print(f"=== DISTRIBUTED BACKTEST ===")
    print(f"Competition stocks: {len(COMPETITION_STOCKS)}")
    print(f"Pool: {len(POOL_99)} stocks")
    print(f"Strategy: VWAP+RSI+Volume+ATR exits (exact Groww strategy)")
    print(f"Parallel agents: 20")
    print()
    
    # Split into 20 batches
    batch_size = (len(COMPETITION_STOCKS) + 19) // 20
    batches = [COMPETITION_STOCKS[i:i+batch_size] for i in range(0, len(COMPETITION_STOCKS), batch_size)]
    
    print(f"Split into {len(batches)} batches")
    for i, b in enumerate(batches):
        print(f"  Batch {i+1}: {b}")
    
    all_results = []
    start = time.time()
    
    # Run batches in parallel (threaded — subprocess spawns separate processes)
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(backtest_batch, batch): i for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
                print(f"Batch {batch_idx+1} done: {len(results)} results")
            except Exception as e:
                print(f"Batch {batch_idx+1} error: {e}")
    
    elapsed = time.time() - start
    
    # Sort by win rate
    all_results.sort(key=lambda x: x.get("win_rate", 0), reverse=True)
    
    # Save
    out = RESULTS_DIR / "competition_backtest.json"
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2)
    
    # Also save ranked version
    ranked = RESULTS_DIR / "competition_ranked.json"
    with open(ranked, "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\n=== RESULTS ({len(all_results)} stocks, {elapsed:.1f}s) ===")
    print(f"{'Rank':<4} {'Symbol':<15} {'WR%':>5} {'Trades':>6} {'Sharpe':>7} {'MaxDD%':>8} {'AvgRet%':>8} {'Best':>8} {'Worst':>8}")
    print("-" * 90)
    for i, r in enumerate(all_results):
        print(f"{i+1:<4} {r['symbol']:<15} {r.get('win_rate',0):>5.1f} {r['trades']:>6} {r.get('sharpe_ratio',0):>7.2f} {r.get('max_drawdown_pct',0):>8.2f} {r.get('avg_return_pct',0):>8.3f} {r.get('best_trade',0):>8.0f} {r.get('worst_trade',0):>8.0f}")
    
    # Rolling window analysis: simulate 99-stock portfolio
    print(f"\n=== ROLLING 99-STOCK PORTFOLIO ===")
    top_99 = all_results[:99] if len(all_results) >= 99 else all_results
    avg_wr = sum(r.get('win_rate', 0) for r in top_99) / len(top_99)
    avg_sharpe = sum(r.get('sharpe_ratio', 0) for r in top_99) / len(top_99)
    total_return = sum(r.get('total_return', 0) for r in top_99)
    avg_dd = sum(r.get('max_drawdown_pct', 0) for r in top_99) / len(top_99)
    print(f"Top {len(top_99)} stocks avg WR: {avg_wr:.1f}%")
    print(f"Avg Sharpe: {avg_sharpe:.2f}")
    print(f"Total return: Rs{total_return:.0f}")
    print(f"Avg MaxDD: {avg_dd:.2f}%")
    
    print(f"\nSaved: {out}")
    return all_results


if __name__ == "__main__":
    main()
