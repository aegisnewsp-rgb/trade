#!/usr/bin/env python3
"""
Live Trading Script - IOB.NS (Indian Overseas Bank)
Strategy: VWAP (Volume Weighted Average Price)
Win Rate: 62.00% (estimated based on PSU bank sector)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Added: 2026-03-22 | PSU bank momentum play, +6.54% on Mar 20
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
        logging.FileHandler(LOG_DIR / "live_IOB.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_IOB")

SYMBOL         = "IOB.NS"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv: list, period: int = 14) -> list:
    atr, prev_close = [], None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum  = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                          for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period, atr_mult = params["vwap_period"], params["atr_multiplier"]
    vwap_vals = calculate_vwap(ohlcv, period)
    atr_vals  = calculate_atr(ohlcv, period)
    signals   = ["HOLD"] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        if price > vwap_vals[i] + atr_vals[i] * atr_mult:
            signals[i] = "BUY"
        elif price < vwap_vals[i] - atr_vals[i] * atr_mult:
            signals[i] = "SELL"
    last = signals[-1]
    entry = ohlcv[-1]["close"]
    sl = atr_vals[-1] * STOP_LOSS_PCT / STOP_LOSS_PCT if atr_vals[-1] else entry * STOP_LOSS_PCT
    tgt = entry + atr_vals[-1] * TARGET_MULT if atr_vals[-1] else entry * 1.03
    return last, float(sl), float(tgt)

def get_groww_quote() -> dict | None:
    if not GROWW_API_KEY:
        return None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"GROWW_API_BASE/live/quotes/{SYMBOL}",
                headers={"Authorization": f"Bearer GROWW_API_KEY"},
                timeout=GROWW_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.warning("Groww API attempt %d failed: %s", attempt + 1, e)
            time.sleep(1)
    return None

def main():
    log.info("Starting %s live trading — strategy: %s", SYMBOL, STRATEGY)
    data = fetch_recent_data()
    if not data:
        log.error("No data fetched. Exiting.")
        sys.exit(1)
    signal, sl, tgt = vwap_signal(data, PARAMS)
    log.info("Signal: %s | Price: %.2f | SL: %.2f | Target: %.2f",
             signal, data[-1]["close"], sl, tgt)
    if signal == "BUY":
        log.info(">>> BUY SIGNAL for %s at ₹%.2f", SYMBOL, data[-1]["close"])
        log.info("    Stop Loss: ₹%.2f | Target: ₹%.2f", sl, tgt)
    elif signal == "SELL":
        log.info(">>> SELL SIGNAL for %s at ₹%.2f", SYMBOL, data[-1]["close"])

if __name__ == "__main__":
    main()
