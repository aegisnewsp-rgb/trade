#!/usr/bin/env python3
"""
Live Trading Script - SANGAM.BO
Strategy: VWAP (Volume Weighted Average Price)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_SANGAM.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SANGAM")

SYMBOL         = "SANGAM.BO"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
IST_TZ_OFFSET    = 5.5

def ist_now():
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open():
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market():
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days=60, retries=3):
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty: raise ValueError("Empty dataframe")
            ohlcv = [{"date": str(idx.date()), "open": float(row["Open"]),
                      "high": float(row["High"]), "low": float(row["Low"]),
                      "close": float(row["Close"]), "volume": int(row["Volume"])}
                     for idx, row in df.iterrows()]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt+1, retries, e)
            time.sleep(2**attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv, period=14):
    atr, prev_close = [], None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_vwap(ohlcv, period=14):
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1: vwap.append(None)
        else:
            tp_sum  = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                          for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i