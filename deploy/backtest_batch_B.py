#!/usr/bin/env python3
"""
Batch B Backtest — 10 Stocks (GROWW Strategy)
- Period: 6 months yfinance
- Entry LONG: price > VWAP * 1.005 AND RSI > 55 AND volume > 1.2× avg AND not DOWNTREND
- Entry SHORT: price < VWAP * 0.995 AND RSI < 45 AND volume > 1.2× avg
- Exit: SL at 0.8% ATR, TGT at 4× ATR, TSL after 1.5× ATR profit
- Position: Rs10,000 per trade
"""
import yfinance as yf
import json
import math
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
RESULTS_DIR = WORKSPACE / "research" / "backtest_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

STOCKS = ["CIPLA", "SRF", "IGL", "BANKINDIA", "NESTLEIND",
          "MARUTI", "HINDALCO", "HCLTECH", "HEROMOTOCO", "M&M"]

POSITION_SIZE = 10000
RISK_PER_TRADE = 0.008   # 0.8% ATR stop loss
TARGET_MULT = 4.0        # 4x ATR target
TSL_TRIGGER_MULT = 1.5   # Activate trailing stop after 1.5x ATR profit
TSL_DIST = 0.3           # Trailing distance in ATR units after trigger


def calc_vwap(ohlcv):
    cum_tp_vol, cum_vol = 0.0, 0.0
    vwaps = []
    for row in ohlcv:
        o, h, l, c, v = row
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
    atr = sum(trs[-period:]) / period
    atrs = [atr] * len(ohlcv)
    for i in range(period + 1, len(ohlcv)):
        atr = (atr * (period - 1) + trs[i]) / period
        atrs[i] = atr
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


def backtest_symbol(symbol):
    try:
        ticker = yf.Ticker(symbol + ".NS")
        d = ticker.history(period="6mo")
        if len(d) < 60:
            return {"symbol": symbol, "error": "Insufficient data"}
        
        ohlcv = [[float(r['Open']), float(r['High']), float(r['Low']),
                  float(r['Close']), float(r['Volume'])] for _, r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        
        vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        atrs = calc_atr(ohlcv)
        vrs = vol_ratio(ohlcv)
        regime = market_regime(closes)
        
        trades = []
        position = None
        daily_returns = []
        
        # Warmup: need ATR to be reliable
        for i in range(20, len(closes) - 5):
            date = d.index[i].date()
            price = closes[i]
            vwap = vwaps[i]
            rsi = rsis[i]
            atr = atrs[i]
            vr = vrs[i]
            reg = market_regime(closes[:i+1])
            
            if position is None:
                # Entry logic
                if reg != "DOWNTREND":
                    if (price > vwap * 1.005 and rsi > 55.0 and vr > 1.2):
                        qty = max(1, POSITION_SIZE // price)
                        sl = price - atr * RISK_PER_TRADE
                        position = {
                            "side": "BUY", "entry": price, "atr": atr,
                            "qty": qty, "peak": price, "sl": sl,
                            "tsl_active": False, "entry_date": str(date)
                        }
                    elif (price < vwap * 0.995 and rsi < 45.0 and vr > 1.2):
                        qty = max(1, POSITION_SIZE // price)
                        sl = price + atr * RISK_PER_TRADE
                        position = {
                            "side": "SELL", "entry": price, "atr": atr,
                            "qty": qty, "peak": price, "sl": sl,
                            "tsl_active": False, "entry_date": str(date)
                        }
            else:
                exited = False
                reason = ""
                pnl = 0
                
                if position["side"] == "BUY":
                    position["peak"] = max(position["peak"], price)
                    
                    # Check TSL trigger first (1.5x ATR profit)
                    profit_atr = (position["peak"] - position["entry"]) / position["atr"]
                    if not position["tsl_active"] and profit_atr >= TSL_TRIGGER_MULT:
                        position["tsl_active"] = True
                    
                    # Target
                    target_price = position["entry"] + position["atr"] * TARGET_MULT
                    if price >= target_price:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "TGT"
                    # Stop loss
                    elif price <= position["sl"]:
                        pnl = (price - position["entry"]) * position["qty"]
                        exited, reason = True, "SL"
                    # Trailing stop (active after 1.5x ATR profit)
                    elif position["tsl_active"]:
                        trail = position["peak"] - position["atr"] * TSL_DIST
                        if price <= trail:
                            pnl = (price - position["entry"]) * position["qty"]
                            exited, reason = True, "TSL"
                            
                else:  # SELL
                    position["peak"] = min(position["peak"], price)
                    
                    profit_atr = (position["entry"] - position["peak"]) / position["atr"]
                    if not position["tsl_active"] and profit_atr >= TSL_TRIGGER_MULT:
                        position["tsl_active"] = True
                    
                    target_price = position["entry"] - position["atr"] * TARGET_MULT
                    if price <= target_price:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "TGT"
                    elif price >= position["sl"]:
                        pnl = (position["entry"] - price) * position["qty"]
                        exited, reason = True, "SL"
                    elif position["tsl_active"]:
                        trail = position["peak"] + position["atr"] * TSL_DIST
                        if price >= trail:
                            pnl = (position["entry"] - price) * position["qty"]
                            exited, reason = True, "TSL"
                
                if exited:
                    ret_pct = pnl / (position["entry"] * position["qty"]) * 100
                    daily_returns.append(ret_pct)
                    trades.append({
                        "date": str(date),
                        "side": position["side"],
                        "entry": round(position["entry"], 2),
                        "exit": round(price, 2),
                        "pnl": round(pnl, 0),
                        "return_pct": round(ret_pct, 3),
                        "reason": reason,
                        "atr_at_entry": round(position["atr"], 4),
                    })
                    position = None
        
        if not trades:
            return {
                "symbol": symbol, "trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_return": 0.0, "avg_return_pct": 0.0,
                "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0,
                "best_trade": 0.0, "worst_trade": 0.0, "regime": regime,
                "data_points": len(closes), "error": None
            }
        
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
        
        # Sharpe
        if daily_returns and len(daily_returns) > 1:
            mean_ret = sum(daily_returns) / len(daily_returns)
            std_ret = math.sqrt(sum((r - mean_ret)**2 for r in daily_returns) / len(daily_returns))
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
            "error": None,
        }
        
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


if __name__ == "__main__":
    print(f"[{datetime.now()}] Starting Batch B backtest — 10 stocks")
    results = []
    for i, stock in enumerate(STOCKS):
        print(f"  [{i+1}/10] {stock}...", end=" ", flush=True)
        res = backtest_symbol(stock)
        print(f"trades={res.get('trades','?')}, ret={res.get('total_return','?')}, wr={res.get('win_rate','?')}%")
        results.append(res)
    
    out_path = RESULTS_DIR / "batch_B.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDone! Saved to {out_path}")
    total_ret = sum(r.get("total_return", 0) for r in results if "error" not in r)
    total_trades = sum(r.get("trades", 0) for r in results if "error" not in r)
    print(f"Summary: {total_trades} total trades, net P&L: ₹{total_ret:.0f}")
