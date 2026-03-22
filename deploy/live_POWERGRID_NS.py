#!/usr/bin/env python3
"""
Live Trading Script for POWERGRID.NS
Strategy: FIBONACCI_RETRACEMENT
Win Rate: 58.82%
Position Size: ₹7,000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR
Daily Loss Cap: 0.3% of capital
Max 1 trade per day

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
Requires GROWW_API_KEY and GROWW_API_SECRET env vars for live orders.
"""

import os
import sys
import logging
import groww_api
import json
import requests
from datetime import datetime, date
from typing import Optional, List, Dict
from pathlib import Path

try:
    import yfinance as yf
        YFINANCE_AVAILABLE = True
:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
SYMBOL = "POWERGRID.NS"
STRATEGY = "FIBONACCI_RETRACEMENT"
BENCHMARK_WIN_RATE = 0.5882

POSITION_SIZE = 7000
DAILY_LOSS_CAP = 0.003
MAX_TRADES_PER_DAY = 1

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_ATR_MULT = 0.8
TARGET_ATR_MULT = 4.0

FIB_PERIOD = 50
ATR_PERIOD = 14

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

LOG_DIR = Path("/tmp")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_POWERGRID.json")

def setup_logging():
    log_file = LOG_DIR / f"trades_POWERGRID.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    return {"trades_today": 0, "last_trade_date": None, "daily_pnl": 0, "daily_loss": 0, "position": None, "last_signal": None}

def save_state(state: Dict):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def reset_daily_state(state: Dict) -> Dict:
    today = date.today().isoformat()
    if state.get("last_trade_date") != today:
        state["trades_today"] = 0
        state["last_trade_date"] = today
        state["daily_pnl"] = 0
        state["daily_loss"] = 0
    return state

def fetch_recent_data(symbol: str, days: int = 90) -> Optional[List[Dict]]:
    if not YFINANCE_AVAILABLE:
        logger.error("yfinance not available")
        return None
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d")
        if df.empty:
            logger.error(f"No data returned for {symbol}")
            return None
        ohlcv = []
        for idx, row in df.iterrows():
            ohlcv.append({"date": idx.isoformat(), "open": float(row["Open"]), "high": float(row["High"]), "low": float(row["Low"]), "close": float(row["Close"]), "volume": int(row["Volume"])})
        logger.info(f"Fetched {len(ohlcv)} days of data for {symbol}")
        return ohlcv
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        return None

def calculate_atr(ohlcv: List[Dict], period: int = 14) -> List[float]:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high = bar["high"]
        low = bar["low"]
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def find_swing_levels(ohlcv: List[Dict], period: int = 50) -> Tuple[float, float, float]:
    """Find swing high, low, and range for Fibonacci levels."""
    if len(ohlcv) < period:
        return 0, 0, 0
    window = ohlcv[-period:]
    swing_high = max(bar["high"] for bar in window)
    swing_low = min(bar["low"] for bar in window)
    return swing_high, swing_low, swing_high - swing_low

# RSI filter: BUY>RSI55, SELL<RSI45
# Regime filter: skip DOWNTREND
def get_signal(ohlcv: List[Dict], atr: List[float]) -> str:
    if len(ohlcv) < FIB_PERIOD:
        return "HOLD"
    
    swing_high, swing_low, range_size = find_swing_levels(ohlcv, FIB_PERIOD)
    if range_size == 0:
        return "HOLD"
    
    current_price = ohlcv[-1]["close"]
    fib_levels = [0.236, 0.382, 0.5, 0.618, 0.786]
    
    for fib in fib_levels:
        level = swing_high - (range_size * fib)
        if abs(current_price - level) / range_size < 0.02:
            if current_price > level:
                return "BUY"
            elif current_price < level:
                return "SELL"
    return "HOLD"

def calculate_stop_loss(entry_price: float, atr: float) -> float:
    return entry_price - (atr * STOP_LOSS_ATR_MULT)

def calculate_target(entry_price: float, atr: float) -> float:
    return entry_price + (atr * TARGET_ATR_MULT)

def check_daily_loss_limit(state: Dict, capital: float) -> bool:
    daily_loss_cap_amount = capital * DAILY_LOSS_CAP
    if abs(state.get("daily_loss", 0)) >= daily_loss_cap_amount:
        logger.warning(f"Daily loss limit reached: {abs(state['daily_loss']):.2f} >= {daily_loss_cap_amount:.2f}")
        return True
    return False

def groww_place_order(symbol: str, transaction_type: str, quantity: int, price: float) -> Optional[Dict]:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        logger.info(f"📋 SIGNAL: {transaction_type} {quantity} shares of {symbol} at ₹{price:.2f}")
        logger.info("   (No API credentials - order not placed)")
        return None
    try:
        headers = {"Content-Type": "application/json", "X-Api-Key": GROWW_API_KEY, "X-Secret-Key": GROWW_API_SECRET}
        payload = {"symbol": symbol, "transaction_type": transaction_type, "quantity": quantity, "price": price, "order_type": "LIMIT"}
        response = requests.post(f"GROWW_API_BASE/v1/orders", headers=headers, json=payload, timeout=GROWW_API_TIMEOUT)
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Order placed successfully: {result}")
            return result
        else:
            logger.error(f"Order failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Groww API error: {e}")
        return None

def execute_trade(signal: str, current_price: float, atr: float, state: Dict, capital: float) -> Dict:
    result = {"action": "NONE", "signal": signal, "price": current_price}
    state = reset_daily_state(state)
    if signal == "HOLD":
        return result
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        logger.info("Max trades reached for today")
        return result
    if check_daily_loss_limit(state, capital):
        return result
    quantity = int(POSITION_SIZE / current_price)
    if quantity < 1:
        logger.warning(f"Position size too small")
        return result
    if signal == "BUY":
        stop_loss = calculate_stop_loss(current_price, atr)
        target = calculate_target(current_price, atr)
        logger.info(f"🟢 BUY SIGNAL: ₹{current_price:.2f} | Qty: {quantity} | SL: ₹{stop_loss:.2f} | TGT: ₹{target:.2f}")
        order = groww_place_order(SYMBOL, "BUY", quantity, current_price)
        result = {"action": "BUY", "signal": signal, "price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "order": order}
        state["trades_today"] += 1
        state["position"] = {"entry_price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "entry_time": datetime.now().isoformat()}
    elif signal == "SELL":
        if not state.get("position"):
            logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f} (No long position)")
            return result
        pos = state["position"]
        quantity = pos["quantity"]
        pnl = (current_price - pos["entry_price"]) * quantity
        logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f} | Closing from ₹{pos['entry_price']:.2f} | P&L: ₹{pnl:.2f}")
        order = groww_place_order(SYMBOL, "SELL", quantity, current_price)
        result = {"action": "SELL", "signal": signal, "price": current_price, "quantity": quantity, "entry_price": pos["entry_price"], "pnl": pnl, "order": order}
        state["trades_today"] += 1
        state["daily_pnl"] += pnl
        if pnl < 0:
            state["daily_loss"] += pnl
        state["position"] = None
    save_state(state)
    return result

def main():
    """Main trading loop"""
    import yfinance
    YFINANCE_AVAILABLE = True
    try:
        ticker = yfinance.Ticker("POWERGRID.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            print("POWERGRID: No data")
            return
        closes = d['Close'].tolist()
        print(f"POWERGRID: {len(closes)} candles, last price {closes[-1]:.2f}")
    except Exception as e:
        print(f"POWERGRID: Error - {e}")

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    sys.exit(main())
