#!/usr/bin/env python3
"""
Live Trading Script - GRASIM.NS
Strategy: FIBONACCI
Win Rate: 57.36%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_GRASIM.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_GRASIM")

SYMBOL         = "GRASIM.NS"
STRATEGY       = "FIBONACCI"
POSITION       = 7000
STOP_LOSS_PCT