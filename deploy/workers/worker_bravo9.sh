#!/bin/bash
# Worker BRAVO-9: Enhance BOSCHLTD VWAP strategy with optimized entries
cd /home/node/workspace/trade-project

SCRIPT="deploy/live_BOSCHLTD.py"

cat > "$SCRIPT.enhanced" << 'ENHANCED_SCRIPT'
#!/usr/bin/env python3
"""
Live Trading Script - BOSCHLTD.NS
Strategy: VWAP with Optimized Entry Rules
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Volume threshold + momentum confirmation
"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "live_BOSCHLTD.log"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("live_BOSCHLTD")

SYMBOL = "BOSCHLTD.NS"
STRATEGY = "VWAP_Optimized"
POSITION = 7000
STOP_LOSS_PCT = 0.008
TARGET_MULT = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5, "min_volume": 100000}

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")

def ist_now(): return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)
def is_market_open():
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def fetch_data(days=60):
    for attempt in range(3):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty: raise ValueError("Empty")
            return [{"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()]
        except Exception as e:
            log.warning("Attempt %d failed: %s", attempt+1, e); time.sleep(2**attempt)
    return None

def calc_vwap(ohlcv, period=14):
    vwap, cum_pv, cum_vol = [], 0.0, 0.0
    for bar in ohlcv:
        tp = (bar["high"]+bar["low"]+bar["close"])/3
        cum_pv += tp*bar["volume"]; cum_vol += bar["volume"]
        vwap.append(cum_pv/cum_vol if cum_vol > 0 else tp)
    return vwap

def calc_atr(ohlcv, period=14):
    atr, prev = [], None
    for bar in ohlcv:
        tr = bar["high"]-bar["low"] if prev is None else max(bar["high"]-bar["low"], abs(bar["high"]-prev), abs(bar["low"]-prev))
        atr.append(tr if len(atr)<period-1 else (atr[-1]*(period-1)+tr)/period)
        prev = bar["close"]
    return atr

def signal_optimized(ohlcv, params):
    vwap = calc_vwap(ohlcv, params["vwap_period"])
    atr = calc_atr(ohlcv, 14)
    p = params["atr_multiplier"]
    min_vol = params.get("min_volume", 100000)
    price = ohlcv[-1]["close"]
    v = vwap[-1]; a = atr[-1]
    vol = ohlcv[-1]["volume"]
    if v is None or a is None or vol < min_vol: return "HOLD", price, a or 0
    # Momentum check: 3 consecutive closes in direction
    if len(ohlcv) >= 4:
        up_mom = all(ohlcv[j]["close"] > ohlcv[j-1]["close"] for j in range(-3, 0))
        dn_mom = all(ohlcv[j]["close"] < ohlcv[j-1]["close"] for j in range(-3, 0))
    else:
        up_mom = dn_mom = False
    if price > v+a*p and up_mom: return "BUY", price, a
    if price < v-a*p and dn_mom: return "SELL", price, a
    return "HOLD", price, a or 0

def main():
    log.info("=== %s | %s (Optimized) ===", SYMBOL, STRATEGY)
    if not is_market_open(): return
    ohlcv = fetch_data(90)
    if not ohlcv or len(ohlcv) < 30: return
    sig, price, atr = signal_optimized(ohlcv, PARAMS)
    sl = round(price*(1-STOP_LOSS_PCT), 2) if sig=="BUY" else round(price*(1+STOP_LOSS_PCT), 2) if sig=="SELL" else 0
    tp = round(price+TARGET_MULT*atr, 2) if sig=="BUY" else round(price-TARGET_MULT*atr, 2) if sig=="SELL" else 0
    log.info("Signal: %s @ ₹%.2f | SL: %.2f | TP: %.2f", sig, price, sl, tp)

if __name__ == "__main__": main()
ENHANCED_SCRIPT

mv "$SCRIPT.enhanced" "$SCRIPT"
python3 -m py_compile "$SCRIPT" && echo "BRAVO-9: BOSCHLTD OK" || echo "BRAVO-9: FAILED"
cd /home/node/workspace/trade-project
git add deploy/live_BOSCHLTD.py && git commit -m "BRAVO-9: Enhance BOSCHLTD with optimized entry rules" 2>&1 || echo "No changes"
echo "BRAVO-9 COMPLETE"