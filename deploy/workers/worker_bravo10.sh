#!/bin/bash
# Worker BRAVO-10: Enhance BRAINBEES VWAP strategy
cd /home/node/workspace/trade-project

SCRIPT="deploy/live_BRAINBEES.py"

cat > "$SCRIPT.enhanced" << 'ENHANCED_SCRIPT'
#!/usr/bin/env python3
"""
Live Trading Script - BRAINBEES.NS
Strategy: VWAP + Volume Confirmation
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Volume MA confirmation filter
"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "live_BRAINBEES.log"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("live_BRAINBEES")

SYMBOL = "BRAINBEES.NS"
STRATEGY = "VWAP+Volume"
POSITION = 7000
STOP_LOSS_PCT = 0.008
TARGET_MULT = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5, "volume_ma_period": 20}

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

def calc_vol_ma(ohlcv, period=20):
    return [None]*period + [sum(ohlcv[j]["volume"] for j in range(i-period+1,i+1))/period for i in range(period-1,len(ohlcv))]

def signal(ohlcv, params):
    vwap = calc_vwap(ohlcv, params["vwap_period"])
    atr = calc_atr(ohlcv, 14)
    vol_ma = calc_vol_ma(ohlcv, params["volume_ma_period"])
    p = params["atr_multiplier"]
    price = ohlcv[-1]["close"]
    v = vwap[-1]; a = atr[-1]; vol = ohlcv[-1]["volume"]; avg_vol = vol_ma[-1]
    if v is None or a is None or avg_vol is None: return "HOLD", price, a or 0
    if price > v+a*p and vol > avg_vol: return "BUY", price, a
    if price < v-a*p and vol > avg_vol: return "SELL", price, a
    return "HOLD", price, a or 0

def main():
    log.info("=== %s | %s ===", SYMBOL, STRATEGY)
    if not is_market_open(): return
    ohlcv = fetch_data(90)
    if not ohlcv or len(ohlcv) < 30: return
    sig, price, atr = signal(ohlcv, PARAMS)
    sl = round(price*(1-STOP_LOSS_PCT), 2) if sig=="BUY" else round(price*(1+STOP_LOSS_PCT), 2) if sig=="SELL" else 0
    tp = round(price+TARGET_MULT*atr, 2) if sig=="BUY" else round(price-TARGET_MULT*atr, 2) if sig=="SELL" else 0
    log.info("Signal: %s @ ₹%.2f | SL: %.2f | TP: %.2f", sig, price, sl, tp)

if __name__ == "__main__": main()
ENHANCED_SCRIPT

mv "$SCRIPT.enhanced" "$SCRIPT"
python3 -m py_compile "$SCRIPT" && echo "BRAVO-10: BRAINBEES OK" || echo "BRAVO-10: FAILED"
cd /home/node/workspace/trade-project
git add deploy/live_BRAINBEES.py && git commit -m "BRAVO-10: Enhance BRAINBEES with volume confirmation" 2>&1 || echo "No changes"
echo "BRAVO-10 COMPLETE"