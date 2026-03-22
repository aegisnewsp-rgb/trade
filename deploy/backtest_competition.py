#!/usr/bin/env python3
"""
Distributed Backtester v2 — 50 stocks, 6mo data, rolling 99-stock window
20 parallel subagents processing batches.
Uses GROWW LIVE STRATEGY: VWAP + RSI + Volume + ATR exits
"""
import yfinance as yf
import json, time, math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
RESULTS_DIR = WORKSPACE / "research" / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

POSITION_SIZE = 10000
RISK_PCT = 0.008
TARGET_MULT = 4.0
TSL_TRIGGER = 1.5
TSL_DIST = 0.3

STOCKS_50 = [
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


def calc_vwap(ohlcv):
    cum_tp, cum_v = 0.0, 0.0
    vwaps = []
    for o, h, l, c, v in ohlcv:
        cum_tp += (o + h + l + c) / 4.0 * v
        cum_v += v
        vwaps.append(cum_tp / cum_v if cum_v > 0 else c)
    return vwaps


def calc_rsi(closes, p=14):
    if len(closes) < p + 1:
        return [50.0] * len(closes)
    rsis = [50.0] * p
    ds = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    for i in range(p, len(closes)):
        g = sum(d for d in ds[i-p:i] if d > 0) / p
        l = sum(-d for d in ds[i-p:i] if d < 0) / p
        rsis.append(50.0 if l == 0 else 100.0 - (100.0 / (1.0 + g / l)))
    return rsis


def calc_atr(ohlcv, p=14):
    if len(ohlcv) < p + 2:
        return [1.0] * len(ohlcv)
    trs = [0.0] * len(ohlcv)
    for i in range(2, len(ohlcv)):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atrs = [0.0] * len(ohlcv)
    atrs[p] = sum(trs[1:p+1]) / p
    for i in range(p + 1, len(ohlcv)):
        atrs[i] = (atrs[i-1] * (p - 1) + trs[i]) / p
    return atrs


def vol_ratio(ohlcv, p=20):
    if len(ohlcv) < p + 1:
        return [1.0] * len(ohlcv)
    vrs = [1.0] * len(ohlcv)
    for i in range(p, len(ohlcv)):
        avg = sum(row[4] for row in ohlcv[i-p:i]) / p
        vrs[i] = ohlcv[i][4] / avg if avg > 0 else 1.0
    return vrs


def regime(closes, p=20):
    if len(closes) < p + 1:
        return "RANGE"
    sma = sum(closes[-p:]) / p
    r = closes[-1] / sma if sma > 0 else 1.0
    return "UPTREND" if r > 1.02 else "DOWNTREND" if r < 0.98 else "RANGE"


def backtest(sym):
    try:
        d = yf.Ticker(sym + ".NS").history(period="6mo")
        if len(d) < 40:
            return None
        ohlcv = [[float(r['Open']), float(r['High']), float(r['Low']),
                  float(r['Close']), float(r['Volume'])] for _, r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        atrs = calc_atr(ohlcv)
        vrs = vol_ratio(ohlcv)
        trades = []
        pos = None
        pf = 100000.0
        for i in range(25, len(closes) - 5):
            price = closes[i]
            rv = regime(closes[:i+1])
            if rv == "DOWNTREND":
                continue
            vwap = vwaps[i]
            rsi = rsis[i]
            atr = max(atrs[i], 0.5)
            vr = vrs[i]
            if pos is None:
                vt = 1.5 if rv == "RANGE" else 1.2
                if price > vwap * 1.005 and rsi > 55 and vr > vt:
                    qty = max(1, POSITION_SIZE // price)
                    pos = {"side": "BUY", "entry": price, "atr": atr,
                           "qty": qty, "peak": price, "sl": price - atr * RISK_PCT}
                elif price < vwap * 0.995 and rsi < 45 and vr > vt:
                    qty = max(1, POSITION_SIZE // price)
                    pos = {"side": "SELL", "entry": price, "atr": atr,
                           "qty": qty, "peak": price, "sl": price + atr * RISK_PCT}
            else:
                pnl = 0
                ex, reason = False, ""
                if pos["side"] == "BUY":
                    pos["peak"] = max(pos["peak"], price)
                    if price >= pos["entry"] + pos["atr"] * TARGET_MULT:
                        pnl = (price - pos["entry"]) * pos["qty"]
                        ex, reason = True, "TGT"
                    elif price <= pos["sl"]:
                        pnl = (price - pos["entry"]) * pos["qty"]
                        ex, reason = True, "SL"
                    elif (pos["peak"] - pos["entry"]) >= pos["atr"] * TSL_TRIGGER:
                        trail = pos["peak"] - pos["atr"] * TSL_DIST
                        if price <= trail:
                            pnl = (price - pos["entry"]) * pos["qty"]
                            ex, reason = True, "TSL"
                else:
                    pos["peak"] = min(pos["peak"], price)
                    if price <= pos["entry"] - pos["atr"] * TARGET_MULT:
                        pnl = (pos["entry"] - price) * pos["qty"]
                        ex, reason = True, "TGT"
                    elif price >= pos["sl"]:
                        pnl = (pos["entry"] - price) * pos["qty"]
                        ex, reason = True, "SL"
                if ex:
                    pf += pnl
                    trades.append({"side": pos["side"], "entry": pos["entry"],
                                   "exit": price, "pnl": pnl, "reason": reason})
                    pos = None
        if len(trades) < 3:
            return None
        wins = [t for t in trades if t["pnl"] > 0]
        wr = len(wins) / len(trades) * 100
        rets = [t["pnl"] / POSITION_SIZE * 100 for t in trades]
        total_ret = sum(t["pnl"] for t in trades)
        running, peak, max_dd = 100000.0, 100000.0, 0.0
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
            dd = (peak - running) / peak * 100
            max_dd = max(max_dd, dd)
        if len(rets) > 1:
            m, s = sum(rets) / len(rets), math.sqrt(sum((r - sum(rets)/len(rets))**2 for r in rets) / len(rets))
            sharpe = m / s * 15.9 if s > 0 else 0.0
        else:
            sharpe = 0.0
        return {
            "symbol": sym, "trades": len(trades), "wins": len(wins),
            "losses": len(trades) - len(wins), "win_rate": round(wr, 1),
            "total_return": round(total_ret, 0),
            "avg_return_pct": round(sum(rets) / len(rets), 3),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "best_trade": round(max(t["pnl"] for t in trades), 0),
            "worst_trade": round(min(t["pnl"] for t in trades), 0),
        }
    except Exception as e:
        return {"symbol": sym, "error": str(e)}


def batch_backtest(batch):
    results = []
    for sym in batch:
        r = backtest(sym)
        if r and "error" not in r:
            results.append(r)
        time.sleep(0.15)
    return results


def main():
    n_workers = 20
    batch_size = max(1, len(STOCKS_50) // n_workers)
    batches = [STOCKS_50[i:i+batch_size] for i in range(0, len(STOCKS_50), batch_size)]
    
    print(f"=== DISTRIBUTED BACKTEST v2 ===")
    print(f"Stocks: {len(STOCKS_50)} | Batches: {len(batches)} | Workers: {n_workers}")
    print(f"Period: 6mo | Strategy: VWAP+RSI+Vol+ATR | Min trades: 3")
    print()
    
    all_results = []
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(batch_backtest, b): i for i, b in enumerate(batches)}
        for f in as_completed(futures):
            idx = futures[f]
            try:
                rs = f.result()
                all_results.extend(rs)
                print(f"  Batch {idx+1}/{len(batches)}: +{len(rs)} stocks")
            except Exception as e:
                print(f"  Batch {idx+1} error: {e}")
    
    elapsed = time.time() - start
    all_results.sort(key=lambda x: x["win_rate"], reverse=True)
    
    out = RESULTS_DIR / "competition_backtest.json"
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\n=== RESULTS ({len(all_results)} stocks, {elapsed:.1f}s) ===")
    print(f"{'Rk':<3} {'Symbol':<14} {'WR%':>5} {'Trds':>5} {'Sharpe':>7} {'MaxDD%':>7} {'AvgRet%':>8} {'Best':>8} {'Worst':>8}")
    print("-" * 80)
    for i, r in enumerate(all_results):
        print(f"{i+1:<3} {r['symbol']:<14} {r['win_rate']:>5.1f} {r['trades']:>5} "
              f"{r['sharpe_ratio']:>7.2f} {r['max_drawdown_pct']:>7.2f} "
              f"{r['avg_return_pct']:>8.3f} {r['best_trade']:>8.0f} {r['worst_trade']:>8.0f}")
    
    # Rolling 99 analysis
    n = min(99, len(all_results))
    top = all_results[:n]
    avg_wr = sum(r['win_rate'] for r in top) / n
    avg_sh = sum(r['sharpe_ratio'] for r in top) / n
    tot_ret = sum(r['total_return'] for r in top)
    avg_dd = sum(r['max_drawdown_pct'] for r in top) / n
    avg_trades = sum(r['trades'] for r in top) / n
    
    print(f"\n=== ROLLING {n}-STOCK PORTFOLIO ===")
    print(f"Avg WR: {avg_wr:.1f}% | Avg Sharpe: {avg_sh:.2f} | Total Return: Rs{tot_ret:.0f}")
    print(f"Avg MaxDD: {avg_dd:.2f}% | Avg Trades/stock: {avg_trades:.1f}")
    print(f"\nTOP 10: {[r['symbol'] for r in all_results[:10]]}")
    print(f"Dropped: {[r['symbol'] for r in all_results[n:]][:10]}")
    print(f"\nSaved: {out}")
    
    # Save top 99 for rolling portfolio
    with open(RESULTS_DIR / "top99_rolling.json", "w") as f:
        json.dump(top, f, indent=2)
    return all_results


if __name__ == "__main__":
    main()
