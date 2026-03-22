#!/usr/bin/env python3
"""
Live Trading Script for MARUTI.NS
Strategy: VWAP (Volume Weighted Average Price)
Enhanced with: Fuel Price Correlation, NIFTY AUTO Index Check, Entry Window 10am-1pm
Win Rate: 59.26%
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
from datetime import datetime, date, time as dtime
from typing import Optional, List, Dict
from pathlib import Path

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
SYMBOL = "MARUTI.NS"
STRATEGY = "VWAP_AUTOMOBILE"
BENCHMARK_WIN_RATE = 0.5926

POSITION_SIZE = 7000
DAILY_LOSS_CAP = 0.003
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 0.8
TARGET_ATR_MULT = 4.0

VWAP_PERIOD = 14
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5

# Entry window: 10:00 AM to 1:00 PM IST
ENTRY_START = dtime(10, 0)
ENTRY_END = dtime(13, 0)

# Sector symbols
NIFTY_AUTO_SYMBOL = "^CNXAUTO"  # NIFTY Auto Index

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

LOG_DIR = Path("/tmp")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_MARUTI.json")

def setup_logging():
    log_file = LOG_DIR / f"trades_MARUTI.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)

def is_within_entry_window() -> bool:
    """Check if current time is within the 10am-1pm entry window"""
    now = ist_now()
    return now.weekday() < 5 and ENTRY_START <= now.time() <= ENTRY_END

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

def get_fuel_price() -> Optional[float]:
    """Fetch crude oil price (proxy for fuel costs)"""
    try:
        oil = yf.Ticker("CL=F").history(period="5d")
        if not oil.empty:
            return float(oil["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"Failed to fetch fuel price: {e}")
    return None

def get_nifty_auto_status() -> Optional[str]:
    """Fetch NIFTY AUTO index and determine trend direction"""
    try:
        auto_index = yf.Ticker(NIFTY_AUTO_SYMBOL).history(period="10d")
        if len(auto_index) >= 2:
            current = float(auto_index["Close"].iloc[-1])
            previous = float(auto_index["Close"].iloc[-2])
            if current > previous * 1.005:
                return "BULLISH"
            elif current < previous * 0.995:
                return "BEARISH"
            return "NEUTRAL"
    except Exception as e:
        logger.warning(f"Failed to fetch NIFTY AUTO: {e}")
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

def calculate_vwap(ohlcv: List[Dict], period: int = 14) -> List[float]:
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            typical_prices = []
            volumes = []
            for j in range(i - period + 1, i + 1):
                tp = (ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                typical_prices.append(tp)
                volumes.append(ohlcv[j]["volume"])
            tp_sum = sum(typical_prices)
            vol_sum = sum(volumes)
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0)
    return vwap

def generate_signal(ohlcv: List[Dict], vwap: List[float], atr: List[float], 
                    fuel_price: Optional[float], auto_trend: Optional[str]) -> str:
    if len(ohlcv) < VWAP_PERIOD or len(vwap) < VWAP_PERIOD or len(atr) < VWAP_PERIOD:
        return "HOLD"
    i = -1
    current_price = ohlcv[i]["close"]
    vwap_value = vwap[i]
    atr_value = atr[i]
    if vwap_value is None or atr_value is None or atr_value == 0:
        return "HOLD"
    if current_price > vwap_value + atr_value * ATR_MULTIPLIER:
        return "BUY"
    elif current_price < vwap_value - atr_value * ATR_MULTIPLIER:
        return "SELL"
    return "HOLD"

def apply_sector_filters(signal: str, fuel_price: Optional[float], 
                         auto_trend: Optional[str], prev_fuel: Optional[float] = None) -> str:
    """Apply automobile sector-specific filters"""
    if signal == "HOLD":
        return "HOLD"
    
    # Fuel price filter: Rising fuel prices hurt auto stocks (negative correlation)
    if fuel_price is not None and prev_fuel is not None:
        fuel_change_pct = (fuel_price - prev_fuel) / prev_fuel * 100
        if fuel_change_pct > 2.0:
            logger.info(f"Fuel price spike: {fuel_change_pct:.2f}% - bearish for auto")
            if signal == "BUY":
                return "HOLD"
        elif fuel_change_pct < -1.5:
            logger.info(f"Fuel price drop: {fuel_change_pct:.2f}% - bullish for auto")
            if signal == "SELL":
                return "HOLD"
    
    # NIFTY AUTO index trend filter
    if auto_trend is not None:
        if signal == "BUY" and auto_trend == "BEARISH":
            logger.info(f"NIFTY AUTO bearish - blocking BUY")
            return "HOLD"
        if signal == "SELL" and auto_trend == "BULLISH":
            logger.info(f"NIFTY AUTO bullish - blocking SELL")
            return "HOLD"
    
    return signal

def calculate_stop_loss(entry_price: float, atr: float) -> float:
    return entry_price - (atr * STOP_LOSS_ATR_MULT)

def calculate_target(entry_price: float, atr: float) -> float:
    return entry_price + (atr * TARGET_ATR_MULT)

def check_daily_loss_limit(state: Dict, capital: float) -> bool:
    daily_loss_cap_amount = capital * DAILY_LOSS_CAP
    if abs(state.get("daily_loss", 0)) >= daily_loss_cap_amount:
        logger.warning(f"Daily loss limit reached")
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
        response = requests.post(f"{GROWW_API_BASE}/v1/orders", headers=headers, json=payload, timeout=GROWW_API_TIMEOUT)
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Order placed successfully: {result}")
            return result
        else:
            logger.error(f"Order failed: {response.status_code}")
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
        return result
    if signal == "BUY":
        stop_loss = calculate_stop_loss(current_price, atr)
        target = calculate_target(current_price, atr)
        logger.info(f"🟢 BUY: ₹{current_price:.2f} | Qty:{quantity} | SL:₹{stop_loss:.2f} | TGT:₹{target:.2f}")
        order = groww_place_order(SYMBOL, "BUY", quantity, current_price)
        result = {"action": "BUY", "signal": signal, "price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "order": order}
        state["trades_today"] += 1
        state["position"] = {"entry_price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "entry_time": datetime.now().isoformat()}
    elif signal == "SELL":
        if not state.get("position"):
            logger.info(f"🔴 SELL: ₹{current_price:.2f} (No position)")
            return result
        pos = state["position"]
        quantity = pos["quantity"]
        pnl = (current_price - pos["entry_price"]) * quantity
        logger.info(f"🔴 SELL: ₹{current_price:.2f} | P&L: ₹{pnl:.2f}")
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
    logger.info("=" * 60)
    logger.info(f"LIVE TRADING - {SYMBOL} | {STRATEGY}")
    logger.info(f"Win Rate: {BENCHMARK_WIN_RATE * 100:.2f}% | Pos: ₹{POSITION_SIZE:,} | SL: {STOP_LOSS_ATR_MULT*100:.1f}% ATR | TGT: {TARGET_ATR_MULT}x ATR")
    logger.info("=" * 60)
    
    state = load_state()
    state = reset_daily_state(state)
    CAPITAL = 100000
    
    if check_daily_loss_limit(state, CAPITAL):
        sys.exit(0)
    
    # Check entry window
    if not is_within_entry_window():
        now = ist_now()
        logger.info(f"Outside entry window (10am-1pm IST). Current time: {now.strftime('%H:%M:%S')}")
    
    ohlcv = fetch_recent_data(SYMBOL, 90)
    if not ohlcv:
        sys.exit(1)
    
    atr = calculate_atr(ohlcv, ATR_PERIOD)
    vwap = calculate_vwap(ohlcv, VWAP_PERIOD)
    current_price = ohlcv[-1]["close"]
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)
    
    # Fetch sector indicators
    fuel_price = get_fuel_price()
    prev_fuel = get_fuel_price()  # approx previous day
    auto_trend = get_nifty_auto_status()
    
    logger.info(f"Sector Check | Fuel: ${fuel_price:.2f} | NIFTY AUTO: {auto_trend}")
    
    signal = generate_signal(ohlcv, vwap, atr, fuel_price, auto_trend)
    filtered_signal = apply_sector_filters(signal, fuel_price, auto_trend, prev_fuel)
    
    logger.info(f"Price: ₹{current_price:.2f} | ATR: ₹{current_atr:.2f} | VWAP: ₹{vwap[-1]:.2f} | Signal: {signal} -> {filtered_signal}")
    
    # Only execute within entry window
    if filtered_signal != "HOLD" and is_within_entry_window():
        result = execute_trade(filtered_signal, current_price, current_atr, state, CAPITAL)
        state["last_signal"] = filtered_signal
        if result["action"] != "NONE":
            logger.info(f"Trade executed: {result}")
    else:
        if filtered_signal != "HOLD":
            logger.info(f"HOLD - Outside entry window (10am-1pm)")
        else:
            logger.info("HOLD signal - no trade")
    
    if state.get("position"):
        pos = state["position"]
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
        logger.info(f"Position: Entry ₹{pos['entry_price']:.2f} | Curr ₹{current_price:.2f} | P&L: {pnl_pct:.2f}%")
    logger.info("=" * 60)
    return 0


def place_groww_order(symbol, signal, quantity, price):
    """Place order via Groww API or paper trade."""
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008
    
    if signal == "BUY":
        stop_loss = price - (atr * 1.0)
        target = price + (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="BUY",
            quantity=quantity, target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = price + (atr * 1.0)
        target = price - (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="SELL",
            quantity=quantity, target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("Order placed: {} {} {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
    return result


if __name__ == "__main__":
    sys.exit(main())
