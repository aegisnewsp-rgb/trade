#!/usr/bin/env python3
"""
Live Trading Script - SG.BO
Strategy: VWAP (Volume Weighted Average Price)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_SG.BO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SG.BO")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "SG.BO"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP =