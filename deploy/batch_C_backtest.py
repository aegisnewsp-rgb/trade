#!/usr/bin/env python3
"""
Batch C Backtest — GROWW Strategy
10 stocks: KOTAKBANK AXISBANK ICICIBANK BAJFINANCE SBILIFE NTPC POWERGRID ONGC GAIL BPCL
Period: 6 months | Position: Rs10,000 per trade
"""
import yfinance as yf
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
RESULTS_FILE = WORKSPACE / "research" / "backtest_results" / "batch_C.json"
RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

STOCKS = ["KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
          "NTPC", "POWERGRID", "ONGC", "GAIL", "BPCL"]

POSITION_SIZE = 10000
SL_ATR   = 0.008   # 0.8% ATR stop loss
TGT_MULT = 4.0     # 4× ATR target
TSL_PROFIT = 1.5  # activate TSL after 1.5× ATR profit
TSL_DIST   = 0.3   # TSL distance in ATR units

def ticker_sym(s):
    # Try .NS (NSE) first, fall back to .BO (BSE)
    return f"{s}.NS"

def calc_vwap(ohlcv):
    """Cumulative VWAP."""
    cum_tp_vol, cum_vol = 0.0, 0.0
    vwaps = []
    for (o, h, l, c, v) in ohlcv:
        tp = (o + h + l + c) / 4.0 * v
        cum_tp_vol += tp
        cum_vol += v
        vwaps.append(cum_tp_vol / cum_vol if cum_vol > 0 else c)
    return vwaps

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    rsis = [50.0] * period
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    for i in range(period, len(deltas) + 1):
        window = deltas[i-period:i]
        gains  = [d for d in window if d > 0]
        losses = [-d for d in window if d < 0]
        ag = sum(gains) / period
        al = sum(losses) / period
        rsis.append(50.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al)))
    return rsis

def calc_atr(ohlcv, period=14):
    if len(ohlcv) < period + 2:
        return [1.0] * len(ohlcv)
    trs = []
    for i in range(1, len(ohlcv)):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc   = ohlcv[i-1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # First ATR: simple mean of first `period` TRs
    first_atr = sum(trs[:period]) / period
    atrs = [first_atr] * (period + 1)
    for i in range(period + 1, len(trs) + 1):
        atr = (atrs[-1] * (period - 1) + trs[i - 1]) / period
        atrs.append(atr)
    return atrs

def is_downtrend(closes, lookback=20):
    """Price below 20-day SMA → downtrend."""
    if len(closes) < lookback:
        return False
    sma = sum(closes[-lookback:]) / lookback
    return closes[-1] < sma

def detect_trend(closes, lookback=20):
    """Return 'down' if below SMA, 'up' if above, else 'neutral'."""
    if len(closes) < lookback:
        return "neutral"
    sma = sum(closes[-lookback:]) / lookback
    if closes[-1] < sma:
        return "down"
    elif closes[-1] > sma * 1.005:
        return "up"
    return "neutral"

def run_backtest(symbol, ohlcv):
    if len(ohlcv) < 30:
        return None

    closes = [row[3] for row in ohlcv]
    vwaps  = calc_vwap(ohlcv)
    rsis   = calc_rsi(closes)
    atrs   = calc_atr(ohlcv)

    # Volume SMA (20-day)
    vols = [row[4] for row in ohlcv]
    vol_sma = [sum(vols[max(0,i-19):i+1]) / min(20, i+1) for i in range(len(vols))]
    avg_vols = vol_sma[19:]  # from index 19 onward
    offset   = 19

    trades = []
    active = None   # {'side': 'LONG'|'SHORT', 'entry_idx': int, 'entry_price': float,
                    #  'atr_at_entry': float, 'tsl_activated': bool, 'tsl_price': float}

    for i in range(offset, len(closes)):
        c   = closes[i]
        v   = vwaps[i]
        r   = rsis[i]
        atr = atrs[i]
        vol_ratio = vols[i] / avg_vols[i - offset] if avg_vols[i - offset] > 0 else 0
        trend = detect_trend(closes[:i+1])

        if active is None:
            # LONG entry
            long_cond = (c > v * 1.005) and (r > 55) and (vol_ratio > 1.2) and (trend != "down")
            # SHORT entry
            short_cond = (c < v * 0.995) and (r < 45) and (vol_ratio > 1.2)

            if long_cond:
                active = {
                    'side': 'LONG',
                    'entry_idx': i,
                    'entry_price': c,
                    'atr_at_entry': atr,
                    'tsl_activated': False,
                    'tsl_price': 0.0,
                }
            elif short_cond:
                active = {
                    'side': 'SHORT',
                    'entry_idx': i,
                    'entry_price': c,
                    'atr_at_entry': atr,
                    'tsl_activated': False,
                    'tsl_price': 0.0,
                }
        else:
            entry  = active['entry_price']
            sl_pct = SL_ATR          # 0.008
            tgt_pct = TGT_MULT       # 4.0
            tsl_trigger_pct = TSL_PROFIT  # 1.5
            tsl_dist_pct   = TSL_DIST     # 0.3

            if active['side'] == 'LONG':
                sl  = entry * (1 - sl_pct)
                tgt = entry * (1 + tgt_pct * sl_pct)   # entry + 4*ATR
                # TSL activation level
                tsl_activate_price = entry * (1 + tsl_trigger_pct * sl_pct)
                # TSL trailing price (below price by 0.3 ATR)
                if not active['tsl_activated'] and c >= tsl_activate_price:
                    active['tsl_activated'] = True
                    active['tsl_price'] = c - tsl_dist_pct * atr
                if active['tsl_activated']:
                    active['tsl_price'] = max(active['tsl_price'], c - tsl_dist_pct * atr)

                exit_price = None
                exit_reason = None
                if c <= sl:
                    exit_price, exit_reason = sl, "SL"
                elif c >= tgt:
                    exit_price, exit_reason = tgt, "TGT"
                elif active['tsl_activated'] and c <= active['tsl_price']:
                    exit_price, exit_reason = c, "TSL"
            else:  # SHORT
                sl  = entry * (1 + sl_pct)
                tgt = entry * (1 - tgt_pct * sl_pct)
                tsl_activate_price = entry * (1 - tsl_trigger_pct * sl_pct)
                if not active['tsl_activated'] and c <= tsl_activate_price:
                    active['tsl_activated'] = True
                    active['tsl_price'] = c + tsl_dist_pct * atr
                if active['tsl_activated']:
                    active['tsl_price'] = min(active['tsl_price'], c + tsl_dist_pct * atr)

                exit_price = None
                exit_reason = None
                if c >= sl:
                    exit_price, exit_reason = sl, "SL"
                elif c <= tgt:
                    exit_price, exit_reason = tgt, "TGT"
                elif active['tsl_activated'] and c >= active['tsl_price']:
                    exit_price, exit_reason = c, "TSL"

            if exit_price is not None:
                qty  = POSITION_SIZE / entry
                pnl  = (exit_price - entry) * qty if active['side'] == 'LONG' else (entry - exit_price) * qty
                trades.append({
                    'entry_date':   i,
                    'entry_price': entry,
                    'exit_price':  exit_price,
                    'exit_reason': exit_reason,
                    'side':        active['side'],
                    'pnl':         round(pnl, 2),
                    'atr':         round(atr, 4),
                })
                active = None

    return trades

def fetch_data(symbol, period="6mo"):
    sym = ticker_sym(symbol)
    try:
        t = yf.Ticker(sym)
        df = t.history(period=period, auto_adjust=True)
        if df.empty or len(df) < 30:
            # try .BO
            sym2 = f"{symbol}.BO"
            t2 = yf.Ticker(sym2)
            df = t2.history(period=period, auto_adjust=True)
        if df.empty:
            return None
        # [(O, H, L, C, V)]
        ohlcv = [(float(df['Open'].iloc[i]), float(df['High'].iloc[i]),
                  float(df['Low'].iloc[i]),  float(df['Close'].iloc[i]),
                  float(df['Volume'].iloc[i])) for i in range(len(df))]
        return ohlcv
    except Exception as e:
        print(f"  [!] {symbol}: {e}")
        return None

def main():
    results = {
        "batch": "C",
        "strategy": "GROWW",
        "period": "6mo",
        "position_size": POSITION_SIZE,
        "stocks": {},
        "summary": {}
    }

    for stock in STOCKS:
        print(f"  Processing {stock}...")
        ohlcv = fetch_data(stock)
        if ohlcv is None:
            print(f"    -> skipped (no data)")
            results["stocks"][stock] = {"error": "no data"}
            continue

        trades = run_backtest(stock, ohlcv)
        if trades is None:
            results["stocks"][stock] = {"error": "insufficient data"}
            continue

        wins  = [t for t in trades if t['pnl'] > 0]
        loss  = [t for t in trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in trades)
        wr  = len(wins) / len(trades) * 100 if trades else 0

        # Max drawdown (running peak)
        peak = 0
        dd   = 0
        for t in trades:
            peak += t['pnl']
            dd = min(dd, peak - peak)  # just track cumulative
            # Actually track drawdown from peak
        cum = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cum += t['pnl']
            if cum > peak:
                peak = cum
            drawdown = peak - cum
            if drawdown > max_dd:
                max_dd = drawdown

        results["stocks"][stock] = {
            "trades":      trades,
            "num_trades":  len(trades),
            "wins":        len(wins),
            "losses":      len(loss),
            "win_rate":    round(wr, 2),
            "total_pnl":   round(total_pnl, 2),
            "max_drawdown": round(max_dd, 2),
        }
        print(f"    -> {len(trades)} trades | PnL: {total_pnl:.2f} | WR: {wr:.1f}%")

    # Aggregate summary
    all_pnls = [s["total_pnl"] for s in results["stocks"].values() if "total_pnl" in s]
    all_trades = sum(s.get("num_trades", 0) for s in results["stocks"].values() if "num_trades" in s)
    total_wins = sum(s.get("wins", 0) for s in results["stocks"].values() if "wins" in s)
    results["summary"] = {
        "total_trades": all_trades,
        "total_wins":   total_wins,
        "overall_wr":  round(total_wins / all_trades * 100, 2) if all_trades else 0,
        "total_pnl":    round(sum(all_pnls), 2),
        "stocks_processed": len(all_pnls),
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {RESULTS_FILE}")

if __name__ == "__main__":
    main()
