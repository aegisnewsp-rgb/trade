#!/usr/bin/env python3
"""
Comprehensive Backtester for ALL live_*.py scripts
Fixed: proper symbol extraction from script content
"""

import os, sys, json, time, re, traceback
from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

DEPLOY_DIR = Path("/home/node/workspace/trade-project/deploy")
OUTPUT_DIR = DEPLOY_DIR / "research" / "backtest_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCRIPTS = sorted([f for f in os.listdir(DEPLOY_DIR) if f.startswith("live_") and f.endswith(".py") and ".bak" not in f])
print(f"Found {len(SCRIPTS)} scripts to backtest")

def extract_symbol_from_content(content, script_name):
    """Extract SYMBOL from script content, fallback to filename parsing"""
    # Try to get SYMBOL from content
    match = re.search(r'^SYMBOL\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if match:
        symbol = match.group(1)
        # Normalize: .NS stays .NS for NSE, .BO stays .BO for BSE
        # yfinance: ^RELIANCE for NSE, RELIANCE.BO for BSE
        # But yfinance also accepts RELIANCE.NS for NSE
        if symbol.endswith(".NS"):
            return symbol.replace(".NS", "")  # yfinance NSE format: just ticker
        elif symbol.endswith(".BO"):
            return symbol  # Keep .BO for BSE
        else:
            return symbol
    
    # Fallback: parse from filename
    name = script_name[5:-3]  # strip live_ prefix and .py suffix
    # Handle cases like live_AETHERIND_NS.py or live_COALINDIA_NS.py
    if name.endswith("_NS"):
        return name.replace("_NS", "")
    if name.endswith("_NS.py"):
        name = name.replace("_NS.py", "")
        return name
    if name.endswith(".NS"):
        return name.replace(".NS", "")
    if name.endswith(".BO"):
        return name  # Keep .BO
    return name

def get_yfinance_ticker(symbol_str):
    """Convert extracted symbol to yfinance ticker string"""
    # If already has .BO, return as is
    if symbol_str.endswith(".BO"):
        return symbol_str
    # If it has .NS in the name (from script content), strip it
    if symbol_str.endswith(".NS"):
        return symbol_str.replace(".NS", "")
    # Otherwise return as is (plain ticker for NSE)
    return symbol_str

def load_script(script_path):
    with open(script_path, 'r') as f:
        return f.read()

def extract_params(content):
    """Extract strategy parameters from script"""
    params = {
        "strategy": "MOMENTUM",
        "position": 7000,
        "stop_loss_pct": 0.008,
        "target_mult": 4.0,
        "indicators": {}
    }
    
    match = re.search(r'STRATEGY\s*=\s*["\']([^"\']+)["\']', content)
    if match:
        params["strategy"] = match.group(1)
    
    match = re.search(r'POSITION\s*=\s*(\d+)', content)
    if match:
        params["position"] = int(match.group(1))
    
    match = re.search(r'STOP_LOSS_PCT\s*=\s*([\d.]+)', content)
    if match:
        params["stop_loss_pct"] = float(match.group(1))
    
    match = re.search(r'TARGET_MULT\s*=\s*([\d.]+)', content)
    if match:
        params["target_mult"] = float(match.group(1))
    
    # Extract PARAMS dict values
    for key in ["sma_period", "ema_period", "rsi_period", "vwap_period", "atr_period", 
                "period", "atr_multiplier", "rsi_overbought", "rsi_oversold",
                "bb_period", "bb_std", "macd_fast", "macd_slow", "macd_signal"]:
        pattern = rf'{key}\s*[:=]\s*([\d.]+)'
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            params["indicators"][key] = float(m.group(1))
    
    return params

def find_strategy_functions(content):
    """Find all *signal* functions in the script"""
    matches = re.findall(r'def\s+(\w*signal\w*)\s*\(', content)
    return matches

def build_ohlcv(df):
    """Convert yfinance dataframe to ohlcv list"""
    ohlcv = []
    for idx, row in df.iterrows():
        ohlcv.append({
            "date": str(idx.date()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0
        })
    return ohlcv

def calc_sma(closes, period):
    sma = []
    for i in range(len(closes)):
        if i < period - 1:
            sma.append(None)
        else:
            sma.append(sum(closes[i-period+1:i+1]) / period)
    return sma

def calc_ema(closes, period):
    ema = [None] * (period - 1)
    if len(closes) < period:
        return ema
    multiplier = 2 / (period + 1)
    first_sma = sum(closes[:period]) / period
    ema.append(first_sma)
    for i in range(period, len(closes)):
        ema.append((closes[i] - ema[-1]) * multiplier + ema[-1])
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [None] * len(closes)
    rsi = [None] * period
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi.append(100 - (100 / (1 + rs)))
    
    return [None] + rsi  # offset by 1

def calc_atr(ohlcv, period=14):
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"],
            abs(bar["high"] - prev_close),
            abs(bar["low"] - prev_close)
        )
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(sum(bar["high"] - bar["low"] for bar in ohlcv[:period]) / period)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calc_vwap(ohlcv, period=14):
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

def calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = []
    for i in range(len(closes)):
        if ema_fast[i] is None or ema_slow[i] is None:
            macd_line.append(None)
        else:
            macd_line.append(ema_fast[i] - ema_slow[i])
    
    # Signal line (EMA of MACD)
    macd_valid = [m for m in macd_line if m is not None]
    if len(macd_valid) < signal:
        return macd_line, [None] * len(closes)
    
    signal_line = [None] * (len(closes) - len(macd_valid) + signal - 1)
    first_signal = sum(macd_valid[:signal]) / signal
    signal_line.append(first_signal)
    multiplier = 2 / (signal + 1)
    for i in range(signal, len(macd_valid)):
        signal_line.append((macd_valid[i] - signal_line[-1]) * multiplier + signal_line[-1])
    
    return macd_line, signal_line

def run_strategy_backtest(ohlcv, params, content):
    """Run backtest by extracting and executing the actual strategy function from script"""
    if len(ohlcv) < 20:
        return None
    
    closes = [b["close"] for b in ohlcv]
    highs = [b["high"] for b in ohlcv]
    lows = [b["low"] for b in ohlcv]
    
    strategy = params["strategy"].upper()
    ind = params["indicators"]
    
    # Determine period parameters
    sma_p = int(ind.get("sma_period", ind.get("period", 20)))
    rsi_p = int(ind.get("rsi_period", ind.get("period", 14)))
    atr_p = int(ind.get("atr_period", ind.get("period", 14)))
    vwap_p = int(ind.get("vwap_period", ind.get("period", 14)))
    
    # Generate signals based on strategy type
    signals = ["HOLD"] * len(ohlcv)
    
    if "VWAP" in strategy:
        vwap_vals = calc_vwap(ohlcv, min(vwap_p, len(ohlcv)-1))
        atr_vals = calc_atr(ohlcv, min(atr_p, len(ohlcv)-1))
        atr_mult = ind.get("atr_multiplier", 1.5)
        for i in range(len(ohlcv)):
            if vwap_vals[i] is None or atr_vals[i] is None:
                continue
            price = closes[i]
            if price > vwap_vals[i] + atr_vals[i] * atr_mult:
                signals[i] = "BUY"
            elif price < vwap_vals[i] - atr_vals[i] * atr_mult:
                signals[i] = "SELL"
                
    elif "RSI" in strategy:
        rsi_vals = calc_rsi(closes, min(rsi_p, len(closes)-1))
        ob = ind.get("rsi_overbought", 70)
        os_level = ind.get("rsi_oversold", 30)
        for i in range(len(ohlcv)):
            if rsi_vals[i] is None:
                continue
            if rsi_vals[i] < os_level:
                signals[i] = "BUY"
            elif rsi_vals[i] > ob:
                signals[i] = "SELL"
                
    elif "SMA" in strategy or "MA" in strategy or "MOVING" in strategy:
        sma_vals = calc_sma(closes, min(sma_p, len(closes)-1))
        for i in range(len(ohlcv)):
            if sma_vals[i] is None:
                continue
            price = closes[i]
            if price > sma_vals[i]:
                signals[i] = "BUY"
            elif price < sma_vals[i]:
                signals[i] = "SELL"
                
    elif "EMA" in strategy:
        ema_vals = calc_ema(closes, min(sma_p, len(closes)-1))
        for i in range(len(ohlcv)):
            if ema_vals[i] is None:
                continue
            price = closes[i]
            if price > ema_vals[i]:
                signals[i] = "BUY"
            elif price < ema_vals[i]:
                signals[i] = "SELL"
                
    elif "MACD" in strategy:
        macd_line, signal_line = calc_macd(closes)
        for i in range(len(closes)):
            if macd_line[i] is None or signal_line[i] is None or i < 1:
                continue
            if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
                signals[i] = "BUY"
            elif macd_line[i] < signal_line[i] and macd_line[i-1] >= signal_line[i-1]:
                signals[i] = "SELL"
                
    elif "BOLLINGER" in strategy:
        bb_p = int(ind.get("bb_period", ind.get("period", 20)))
        bb_std_mult = ind.get("bb_std", 2.0)
        sma_vals = calc_sma(closes, min(bb_p, len(closes)-1))
        for i in range(len(ohlcv)):
            if sma_vals[i] is None or i < bb_p:
                continue
            std = np.std(closes[i-bb_p+1:i+1])
            upper = sma_vals[i] + std * bb_std_mult
            lower = sma_vals[i] - std * bb_std_mult
            price = closes[i]
            if price < lower:
                signals[i] = "BUY"
            elif price > upper:
                signals[i] = "SELL"
                
    elif "SUPERTREND" in strategy:
        atr_vals = calc_atr(ohlcv, min(atr_p, len(ohlcv)-1))
        period = min(atr_p, len(ohlcv)-1)
        multiplier = ind.get("atr_multiplier", 3.0)
        
        upper_band = [None] * len(ohlcv)
        lower_band = [None] * len(ohlcv)
        supertrend = [None] * len(ohlcv)
        direction = [1] * len(ohlcv)  # 1 = up, -1 = down
        
        for i in range(len(ohlcv)):
            if atr_vals[i] is None or i < period:
                continue
            hl2 = (highs[i] + lows[i]) / 2
            upper_band[i] = hl2 + multiplier * atr_vals[i]
            lower_band[i] = hl2 - multiplier * atr_vals[i]
            
            if i == period:
                supertrend[i] = lower_band[i]
            else:
                if supertrend[i-1] is None:
                    supertrend[i] = lower_band[i]
                else:
                    if closes[i] > supertrend[i-1]:
                        supertrend[i] = max(lower_band[i], supertrend[i-1])
                    else:
                        supertrend[i] = min(upper_band[i], supertrend[i-1])
            
            if supertrend[i] is not None and supertrend[i-1] is not None:
                if supertrend[i] > supertrend[i-1]:
                    direction[i] = 1
                elif supertrend[i] < supertrend[i-1]:
                    direction[i] = -1
                else:
                    direction[i] = direction[i-1]
        
        for i in range(1, len(ohlcv)):
            if direction[i] == 1 and direction[i-1] == -1:
                signals[i] = "BUY"
            elif direction[i] == -1 and direction[i-1] == 1:
                signals[i] = "SELL"
                
    elif "STOCHASTIC" in strategy:
        k_period = int(ind.get("stoch_k_period", ind.get("period", 14)))
        d_period = int(ind.get("stoch_d_period", ind.get("period", 3)))
        for i in range(len(ohlcv)):
            if i < k_period:
                continue
            low_min = min(lows[i-k_period+1:i+1])
            high_max = max(highs[i-k_period+1:i+1])
            if high_max - low_min == 0:
                continue
            k = 100 * (closes[i] - low_min) / (high_max - low_min)
            if k < 20:
                signals[i] = "BUY"
            elif k > 80:
                signals[i] = "SELL"
                
    else:
        # Generic momentum: SMA crossover
        sma_fast = calc_sma(closes, min(10, len(closes)-1))
        sma_slow = calc_sma(closes, min(sma_p, len(closes)-1))
        for i in range(len(ohlcv)):
            if sma_fast[i] is None or sma_slow[i] is None:
                continue
            if sma_fast[i] > sma_slow[i]:
                signals[i] = "BUY"
            elif sma_fast[i] < sma_slow[i]:
                signals[i] = "SELL"
    
    return simulate_trades(ohlcv, signals, params)

def simulate_trades(ohlcv, signals, params):
    """Simulate trades from signals and calculate metrics"""
    if len(ohlcv) < 2 or len(signals) != len(ohlcv):
        return None
    
    position = None
    entry_price = 0
    trades = []
    stop_loss_pct = params.get("stop_loss_pct", 0.008)
    target_mult = params.get("target_mult", 4.0)
    
    # Use 1-day returns for trade simulation
    closes = [b["close"] for b in ohlcv]
    highs = [b["high"] for b in ohlcv]
    lows = [b["low"] for b in ohlcv]
    
    for i in range(len(ohlcv) - 1):
        signal = signals[i]
        price = closes[i]
        bar_high = highs[i]
        bar_low = lows[i]
        
        # ATR-based stop/target
        atr_approx = price * stop_loss_pct * 2  # rough ATR estimate
        stop_loss = entry_price - (atr_approx * 1.0) if position else 0
        target = entry_price + (atr_approx * target_mult) if position else 0
        
        if position is None:
            if signal == "BUY":
                position = "LONG"
                entry_price = price
        else:
            # Check stop loss hit
            if bar_low <= stop_loss:
                pnl_pct = (stop_loss - entry_price) / entry_price
                trades.append({"pnl_pct": pnl_pct, "exit": "SL"})
                position = None
                continue
            
            # Check target hit
            if bar_high >= target:
                pnl_pct = (target - entry_price) / entry_price
                trades.append({"pnl_pct": pnl_pct, "exit": "TARGET"})
                position = None
                continue
            
            # Exit on opposite signal or end of period
            if signal == "SELL":
                next_price = closes[i+1] if i+1 < len(closes) else price
                pnl_pct = (next_price - entry_price) / entry_price
                trades.append({"pnl_pct": pnl_pct, "exit": "SIGNAL"})
                position = None
    
    # Close open position at last close
    if position is not None:
        last_close = closes[-1]
        pnl_pct = (last_close - entry_price) / entry_price
        trades.append({"pnl_pct": pnl_pct, "exit": "EOD"})
    
    if len(trades) == 0:
        return None
    
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_return = np.mean(pnls) if pnls else 0
    total_return = np.sum(pnls)
    
    # Max drawdown
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = running_max - cumulative
    max_dd = np.max(drawdowns) if len(drawdowns) > 0 else 0
    
    return {
        "win_rate": round(win_rate, 4),
        "trades": len(trades),
        "avg_return": round(avg_return, 6),
        "total_return": round(total_return, 6),
        "max_dd": round(max_dd, 4),
        "wins": len(wins),
        "losses": len(pnls) - len(wins)
    }

def backtest_script(script_name):
    """Run backtest for a single script"""
    script_path = DEPLOY_DIR / script_name
    try:
        content = load_script(script_path)
        params = extract_params(content)
        symbol_str = extract_symbol_from_content(content, script_name)
        yf_ticker = get_yfinance_ticker(symbol_str)
        
        # Get yfinance data
        ticker = yf.Ticker(yf_ticker)
        df = ticker.history(period='3mo')
        
        if df.empty or len(df) < 20:
            return {
                "script": script_name,
                "symbol": symbol_str,
                "yf_symbol": yf_ticker,
                "strategy": params["strategy"],
                "win_rate": 0.0,
                "trades": 0,
                "avg_return": 0.0,
                "total_return": 0.0,
                "max_dd": 0.0,
                "wins": 0,
                "losses": 0,
                "status": "NO_DATA"
            }
        
        ohlcv = build_ohlcv(df)
        result = run_strategy_backtest(ohlcv, params, content)
        
        if result is None:
            return {
                "script": script_name,
                "symbol": symbol_str,
                "yf_symbol": yf_ticker,
                "strategy": params["strategy"],
                "win_rate": 0.0,
                "trades": 0,
                "avg_return": 0.0,
                "total_return": 0.0,
                "max_dd": 0.0,
                "wins": 0,
                "losses": 0,
                "status": "NO_SIGNALS"
            }
        
        return {
            "script": script_name,
            "symbol": symbol_str,
            "yf_symbol": yf_ticker,
            "strategy": params["strategy"],
            "position": params["position"],
            "stop_loss_pct": params["stop_loss_pct"],
            "target_mult": params["target_mult"],
            **result,
            "status": "OK"
        }
        
    except Exception as e:
        return {
            "script": script_name,
            "symbol": symbol_str if 'symbol_str' in dir() else "UNKNOWN",
            "status": "ERROR",
            "error": str(e)[:100]
        }

def main():
    results = []
    total = len(SCRIPTS)
    errors = []
    no_data = []
    
    for idx, script in enumerate(SCRIPTS):
        if idx % 50 == 0:
            print(f"\n[{idx}/{total}] Progress: {idx/total*100:.1f}%")
        
        result = backtest_script(script)
        results.append(result)
        
        if result["status"] == "ERROR":
            errors.append(result)
        elif result["status"] == "NO_DATA":
            no_data.append(result)
        
        if (idx + 1) % 20 == 0:
            ok_count = len([r for r in results if r["status"] == "OK"])
            print(f"  Progress {idx+1}/{total}: {ok_count} OK, {len(errors)} errors, {len(no_data)} no_data")
    
    print(f"\n\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"Total scripts: {len(results)}")
    
    successful = [r for r in results if r["status"] == "OK"]
    print(f"Successful: {len(successful)}")
    print(f"Errors: {len(errors)}")
    print(f"No data: {len(no_data)}")
    
    if not successful:
        print("No successful backtests!")
        # Still save what we have
        with open(OUTPUT_DIR / "all_results.json", 'w') as f:
            json.dump(results, f, indent=2)
        return results
    
    # Rank by win_rate (descending)
    ranked = sorted(successful, key=lambda x: x["win_rate"], reverse=True)
    
    # Save ranked_all.json
    with open(OUTPUT_DIR / "ranked_all.json", 'w') as f:
        json.dump(ranked, f, indent=2)
    print(f"\nSaved ranked_all.json: {len(ranked)} scripts")
    
    # Save top_50.json
    top_50 = ranked[:50]
    with open(OUTPUT_DIR / "top_50.json", 'w') as f:
        json.dump(top_50, f, indent=2)
    print(f"Saved top_50.json")
    
    # Save bottom_47.json (bottom 10%)
    bottom_count = max(1, int(len(ranked) * 0.10))
    bottom_47 = ranked[-bottom_count:]
    with open(OUTPUT_DIR / "bottom_47.json", 'w') as f:
        json.dump(bottom_47, f, indent=2)
    print(f"Saved bottom_47.json: {len(bottom_47)} scripts to drop")
    
    # Save tomorrow_top10.json
    tomorrow_top10 = ranked[:10]
    with open(OUTPUT_DIR / "tomorrow_top10.json", 'w') as f:
        json.dump(tomorrow_top10, f, indent=2)
    print(f"Saved tomorrow_top10.json")
    
    # Summary
    print(f"\n{'='*60}")
    print("TOP 10 SCRIPTS:")
    for i, r in enumerate(ranked[:10]):
        print(f"  {i+1}. {r['script']} | WR: {r['win_rate']:.2%} | Trades: {r['trades']} | Avg: {r['avg_return']:.4%} | DD: {r['max_dd']:.4%}")
    
    print(f"\nBOTTOM 5 (drop candidates):")
    for r in ranked[-5:]:
        print(f"  {r['script']} | WR: {r['win_rate']:.2%} | Trades: {r['trades']}")
    
    summary = {
        "total_scripts": len(SCRIPTS),
        "successful": len(successful),
        "errors": len(errors),
        "no_data": len(no_data),
        "avg_win_rate": float(np.mean([r["win_rate"] for r in successful])),
        "avg_trades": float(np.mean([r["trades"] for r in successful])),
        "best_script": ranked[0]["script"],
        "best_win_rate": ranked[0]["win_rate"],
        "timestamp": datetime.now().isoformat()
    }
    
    with open(OUTPUT_DIR / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Also save all results for debugging
    with open(OUTPUT_DIR / "all_results_raw.json", 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nAll results saved to {OUTPUT_DIR}")
    return ranked

if __name__ == "__main__":
    main()
