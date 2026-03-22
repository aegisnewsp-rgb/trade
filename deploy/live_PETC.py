#!/usr/bin/env python3
"""
Live Trading Script - PETC.BO
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
        logging.FileHandler(LOG_DIR / "live_PETC.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_PETC")

SYMBOL         = "PETC.BO"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"
IST_TZ_OFFSET    = 5.5

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(row["Open"]),
                 "high": float(row["High"]), "low": float(row["Low"]),
