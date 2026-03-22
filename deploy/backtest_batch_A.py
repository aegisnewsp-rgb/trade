#!/usr/bin/env python3
"""
Batch A Backtest — 10 stocks (GROWW strategy)
Period: 6 months yfinance
Entry LONG:  price > VWAP*1.005 AND RSI>55 AND vol>1.2x avg AND NOT DOWNTREND
Entry SHORT: price < VWAP*0.995 AND RSI<45 AND vol>1.2x avg
Exit: SL at 0.8%ATR, TGT at 4xATR, TSL after 1.5xATR profit
Position: Rs10,000 per trade
"""
import yfinance as yf
import json
import time
import math
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
OUTFILE   = WORKSPACE / "research" / "backtest_results" / "batch_A.json"
OUTFILE.parent.mkdir(parents=True, exist_ok=True)

STOCKS = [
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "RELIANCE", "TCS",
    "SBIN", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA",
]

POSITION   = 10_000.0
RISK_PCT   = 0.008   # 0.8% ATR stop loss
TGT_MULT   = 4.0     # 4x ATR target
TSL_ARM    = 1.5     # activate TSL after 1.5x ATR profit
TSL_DIST   = 0.3     # TSL trailing distance in ATR units after arm

# ── helpers ──────────────────────────────────────────────────────────────────

def to_ohlcv(df):
    return [[float(r.Open), float(r.High), float(r.Low),
             float(r.Close), float(r.Volume)] for _, r in df.iterrows()]

def calc_vwap(ohlcv):
    cum_tp, cum_v = 0.0, 0.0
    vwaps = []
    for o, h, l, c, v in ohlcv:
        cum_tp += (o + h + l + c) / 4.0 * v
        cum_v  += v
        vwaps.append(cum_tp / cum_v if cum_v else c)
    return vwaps

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    rsis = [50.0] * period
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    for i in range(period, len(closes)):
        gains  = sum(d for d in deltas[i-period:i] if d > 0) / period
        losses = sum(-d for d in deltas[i-period:i] if d < 0) / period
        rsis.append(50.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses))
    return rsis

def calc_atr(ohlcv, period=14):
    if len(ohlcv) < period + 1:
        return [0.0] * len(ohlcv)
    trs = [0.0] * (period + 1)
    for i in range(2, len(ohlcv)):
        h, l  = ohlcv[i][1], ohlcv[i][2]
        prev  = ohlcv[i-1][3]
        trs.append(max(h - l, abs(h - prev), abs(l - prev)))
    atr  = sum(trs[-period:]) / period
    atrs = [atr] * (period + 1)
    for i in range(period + 1, len(ohlcv)):
        atr  = (atr * (period - 1) + trs[i]) / period
        atrs.append(atr)
    return atrs

def avg_vol(ohlcv, period=20):
    avgs = []
    for i in range(len(ohlcv)):
        if i < period:
            avgs.append(ohlcv[i][4])
        else:
            avgs.append(sum(ohlcv[i-period:i][j][4] for j in range(period)) / period)
    return avgs

def sma20(closes):
    if len(closes) < 20:
        return [None] * len(closes)
    out = [None] * 19
    for i in range(19, len(closes)):
        out.append(sum(closes[i-19:i+1]) / 20)
    return out

def regime(closes):
    """'UPTREND' if price > SMA20*1.02, 'DOWNTREND' if < SMA20*0.98, else 'RANGE'"""
    if len(closes) < 20:
        return "RANGE"
    s = sum(closes[-20:]) / 20
    r = closes[-1] / s if s else 1.0
    if r > 1.02:   return "UPTREND"
    if r < 0.98:   return "DOWNTREND"
    return "RANGE"

# ── single-symbol backtest ────────────────────────────────────────────────────

def backtest(symbol):
    try:
        tk  = yf.Ticker(symbol + ".NS")
        df  = tk.history(period="6mo")
        if len(df) < 60:
            return {"symbol": symbol, "error": "insufficient data"}

        ohlcv  = to_ohlcv(df)
        closes = [row[3] for row in ohlcv]
        vols   = [row[4] for row in ohlcv]

        vwaps  = calc_vwap(ohlcv)
        rsis   = calc_rsi(closes)
        atrs   = calc_atr(ohlcv)
        avgs   = avg_vol(ohlcv)
        smas   = sma20(closes)

        # warm-up: need SMA20, ATR, RSI
        warm = 25

        trades       = []
        position     = None
        portfolio    = 100_000.0

        for i in range(warm, len(closes) - 5):
            date   = str(df.index[i].date())
            price  = closes[i]
            vwap   = vwaps[i]
            rsi    = rsis[i]
            atr    = atrs[i]
            vol    = vols[i]
            avgv   = avgs[i]
            vr     = vol / avgv if avgv else 1.0
            reg    = regime(closes[:i+1])

            sl_dist = atr * RISK_PCT          # absolute SL distance
            tgt_dist = atr * TGT_MULT          # absolute target distance

            if position is None:
                # ── ENTRY ──────────────────────────────────────────────────
                if reg != "DOWNTREND":
                    if (price > vwap * 1.005 and rsi > 55.0 and vr > 1.2):
                        qty    = max(1, int(POSITION / price))
                        entry  = price
                        sl     = entry - sl_dist
                        tsl_arm = entry + atr * TSL_ARM
                        position = {
                            "side": "LONG", "entry": entry,
                            "atr": atr, "qty": qty,
                            "peak": price, "tsl_arm": tsl_arm,
                            "sl": sl, "entry_date": date,
                        }

                if (price < vwap * 0.995 and rsi < 45.0 and vr > 1.2):
                    qty    = max(1, int(POSITION / price))
                    entry  = price
                    sl     = entry + sl_dist
                    tsl_arm = entry - atr * TSL_ARM
                    position = {
                        "side": "SHORT", "entry": entry,
                        "atr": atr, "qty": qty,
                        "peak": price, "tsl_arm": tsl_arm,
                        "sl": sl, "entry_date": date,
                    }
            else:
                # ── EXIT CHECKS ────────────────────────────────────────────
                pnl    = 0.0
                exit_r = None

                if position["side"] == "LONG":
                    position["peak"] = max(position["peak"], price)
                    unlocked = position["peak"] - position["entry"] >= atr * TSL_ARM

                    # Stop loss
                    if price <= position["sl"]:
                        pnl, exit_r = (price - position["entry"]) * position["qty"], "SL"
                    # Target
                    elif price >= position["entry"] + tgt_dist:
                        pnl, exit_r = (price - position["entry"]) * position["qty"], "TGT"
                    # Trailing stop (only after TSL arm is hit)
                    elif unlocked:
                        trail = position["peak"] - atr * TSL_DIST
                        if price <= trail:
                            pnl, exit_r = (price - position["entry"]) * position["qty"], "TSL"

                else:  # SHORT
                    position["peak"] = min(position["peak"], price)
                    unlocked = position["entry"] - position["peak"] >= atr * TSL_ARM

                    if price >= position["sl"]:
                        pnl, exit_r = (position["entry"] - price) * position["qty"], "SL"
                    elif price <= position["entry"] - tgt_dist:
                        pnl, exit_r = (position["entry"] - price) * position["qty"], "TGT"
                    elif unlocked:
                        trail = position["peak"] + atr * TSL_DIST
                        if price >= trail:
                            pnl, exit_r = (position["entry"] - price) * position["qty"], "TSL"

                if exit_r:
                    portfolio += pnl
                    ret_pct = pnl / (position["entry"] * position["qty"]) * 100
                    trades.append({
                        "entry_date": position["entry_date"],
                        "exit_date":  date,
                        "side":       position["side"],
                        "entry":      round(position["entry"], 2),
                        "exit":       round(price, 2),
                        "pnl":        round(pnl, 2),
                        "return_pct": round(ret_pct, 3),
                        "reason":     exit_r,
                        "atr_at_entry": round(position["atr"], 4),
                    })
                    position = None

        # ── summary ─────────────────────────────────────────────────────────
        if not trades:
            return {"symbol": symbol, "error": "no trades generated"}

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        pnls   = [t["pnl"] for t in trades]
        rets   = [t["return_pct"] for t in trades]

        total_inv = POSITION * len(trades)
        total_ret = sum(pnls)

        # Max drawdown
        running, peak, max_dd = 100_000.0, 100_000.0, 0.0
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
            dd   = (peak - running) / peak * 100
            max_dd = max(max_dd, dd)

        # Sharpe
        if len(rets) > 1:
            mu  = sum(rets) / len(rets)
            sd  = math.sqrt(sum((r - mu)**2 for r in rets) / (len(rets) - 1))
            sharpe = (mu / sd * math.sqrt(252)) if sd else 0.0
        else:
            sharpe = 0.0

        return {
            "symbol":           symbol,
            "trades":           len(trades),
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate":         round(len(wins) / len(trades) * 100, 1),
            "total_return_rs":  round(total_ret, 0),
            "total_return_pct": round(total_ret / 100_000 * 100, 2),
            "avg_return_pct":   round(sum(rets) / len(rets), 3),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio":     round(sharpe, 2),
            "best_trade_rs":    round(max(pnls), 2),
            "worst_trade_rs":   round(min(pnls), 2),
            "final_portfolio":  round(portfolio, 0),
            "regime":           regime(closes),
            "data_points":      len(closes),
            "trade_log":        trades,
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== BATCH A BACKTEST — 10 stocks ===")
    print(f"Strategy: GROWW (VWAP+RSI+Vol, 0.8%SL/4xTGT/TSL1.5x)")
    print(f"Position: Rs{ int(POSITION):,}/trade | Period: 6 months\n")

    results = []
    for i, sym in enumerate(STOCKS):
        t0 = time.time()
        print(f"[{i+1:02d}/10] {sym:<15} ... ", end="", flush=True)
        r   = backtest(sym)
        dt  = time.time() - t0
        if "error" in r:
            print(f"ERROR: {r['error']}")
        else:
            print(f"WR={r['win_rate']}% | trades={r['trades']} | "
                  f"sharpe={r['sharpe_ratio']} | dd={r['max_drawdown_pct']}% | "
                  f"ret={r['total_return_pct']}% | {dt:.1f}s")
        results.append(r)
        time.sleep(0.15)

    # summary table
    print("\n── SUMMARY ──────────────────────────────────────────────────")
    print(f"{'Symbol':<15} {'Trades':>6} {'WR%':>5} {'Ret%':>6} {'Sharpe':>6} {'DD%':>5} {'Best':>8} {'Worst':>8}")
    print("─" * 65)
    for r in results:
        if "error" not in r:
            print(f"{r['symbol']:<15} {r['trades']:>6} {r['win_rate']:>5} "
                  f"{r['total_return_pct']:>6} {r['sharpe_ratio']:>6} "
                  f"{r['max_drawdown_pct']:>5} {r['best_trade_rs']:>8} {r['worst_trade_rs']:>8}")

    with open(OUTFILE, "w") as f:
        json.dump({"batch": "A", "strategy": "GROWW", "stocks": STOCKS,
                    "params": {"position_rs": POSITION, "sl_pct_atr": RISK_PCT,
                               "tgt_mult_atr": TGT_MULT, "tsl_arm_atr": TSL_ARM,
                               "tsl_dist_atr": TSL_DIST},
                    "results": results,
                    "timestamp": datetime.utcnow().isoformat() + "Z"},
                  f, indent=2)

    print(f"\n✅ Saved → {OUTFILE}")
