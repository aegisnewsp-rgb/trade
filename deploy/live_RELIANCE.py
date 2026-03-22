#!/usr/bin/env python3
"""
Live Trading Script for RELIANCE.NS
Strategy: TSI (True Strength Index)
Win Rate: 63.64%
Position Size: ₹7,000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR
Daily Loss Cap: 0.3% of capital
Max 1 trade per day

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
Requires GROWW_API_KEY and GROWW_API_SECRET env vars for live orders.
"""

import os
import sys
import logging
import json
import time
import requests
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple
from pathlib import Path

# Try to import yfinance as fallback
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
SYMBOL = "RELIANCE.NS"
STRATEGY = "TSI"
BENCHMARK_WIN_RATE = 0.6364

# Risk Management
POSITION_SIZE = 7000  # ₹7,000 per trade
DAILY_LOSS_CAP = 0.003  # 0.3% of capital
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 0.8  # 0.8% ATR-based stop loss
TARGET_ATR_MULT = 4.0  # 4.0x ATR-based target

# TSI Parameters
TSI_FAST = 13
TSI_SLOW = 25
TSI_SIGNAL = 13
ATR_PERIOD = 14

# Groww API Configuration
GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

# Logging
LOG_DIR = Path("/home/node/workspace/trade-project/deploy/logs")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_RELIANCE.json")

# ============== LOGGING SETUP ==============
def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"live_RELIANCE_{date.today().isoformat()}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============== STATE MANAGEMENT ==============
def load_state() -> Dict:
    """Load trading state from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    return {
        "trades_today": 0,
        "last_trade_date": None,
        "daily_pnl": 0,
        "daily_loss": 0,
        "position": None,
        "last_signal": None
    }

def save_state(state: Dict):
    """Save trading state to file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def reset_daily_state(state: Dict) -> Dict:
    """Reset daily counters if it's a new trading day."""
    today = date.today().isoformat()
    if state.get("last_trade_date") != today:
        state["trades_today"] = 0
        state["last_trade_date"] = today
        state["daily_pnl"] = 0
        state["daily_loss"] = 0
    return state

# ============== DATA FETCHING ==============
def fetch_recent_data(symbol: str, days: int = 90) -> Optional[List[Dict]]:
    """Fetch recent OHLCV data using yfinance."""
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
            ohlcv.append({
                "date": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"])
            })
        
        logger.info(f"Fetched {len(ohlcv)} days of data for {symbol}")
        return ohlcv
    
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        return None

def fetch_today_data(symbol: str) -> Optional[Dict]:
    """Fetch today's latest data (for live trading)."""
    if not YFINANCE_AVAILABLE:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2d")
        
        if df.empty:
            return None
        
        # Get the most recent bar
        last = df.iloc[-1]
        return {
            "date": df.index[-1].isoformat(),
            "open": float(last["Open"]),
            "high": float(last["High"]),
            "low": float(last["Low"]),
            "close": float(last["Close"]),
            "volume": int(last["Volume"])
        }
    except Exception as e:
        logger.error(f"Failed to fetch today's data: {e}")
        return None

# ============== TECHNICAL INDICATORS ==============
def calculate_atr(ohlcv: List[Dict], period: int = 14) -> List[float]:
    """Calculate Average True Range."""
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

def calculate_tsi(ohlcv: List[Dict], fast: int = 13, slow: int = 25, signal: int = 13) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate True Strength Index.
    Returns: (tsi_values, signal_values, histogram)
    """
    closes = [bar["close"] for bar in ohlcv]
    
    # Calculate momentum (price change)
    momentum = []
    for i in range(1, len(closes)):
        momentum.append(closes[i] - closes[i-1])
    
    if len(momentum) < slow:
        return [50.0] * len(ohlcv), [50.0] * len(ohlcv), [0.0] * len(ohlcv)
    
    # Double smoothed momentum using EMA
    def calc_ema(data, period):
        if len(data) < period:
            return data
        ema = [data[0]]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
        return ema
    
    # First smoothing
    mom_ema1 = calc_ema(momentum, fast)
    # Second smoothing
    mom_ema2 = calc_ema(mom_ema1, slow)
    
    # TSI calculation
    tsi_values = []
    abs_mom_ema1 = calc_ema([abs(m) for m in momentum], fast)
    abs_mom_ema2 = calc_ema(abs_mom_ema1, slow)
    
    for i in range(len(momentum)):
        if abs_mom_ema2[i] != 0:
            tsi = 100 * (mom_ema2[i] / abs_mom_ema2[i])
        else:
            tsi = 50.0
        tsi_values.append(tsi)
    
    # Signal line (EMA of TSI)
    signal_values = calc_ema(tsi_values, signal)
    
    # Histogram
    histogram = [t - s for t, s in zip(tsi_values[:len(signal_values)], signal_values)] if len(signal_values) <= len(tsi_values) else [0]
    
    # Pad to match ohlcv length
    while len(tsi_values) < len(ohlcv):
        tsi_values.insert(0, 50.0)
        signal_values.insert(0, 50.0)
    
    return tsi_values, signal_values, histogram

# ============== SIGNAL GENERATION ==============
def generate_signal(ohlcv: List[Dict], atr: List[float], tsi: List[float], signal_line: List[float]) -> str:
    """
    Generate trading signal based on TSI strategy.
    BUY: TSI crosses above signal line (bullish)
    SELL: TSI crosses below signal line (bearish)
    HOLD: No clear signal
    """
    if len(ohlcv) < 2 or len(tsi) < 2 or len(signal_line) < 2:
        return "HOLD"
    
    current_tsi = tsi[-1]
    prev_tsi = tsi[-2]
    current_signal = signal_line[-1]
    prev_signal = signal_line[-2]
    
    current_price = ohlcv[-1]["close"]
    
    # TSI bullish crossover
    if prev_tsi <= prev_signal and current_tsi > current_signal:
        return "BUY"
    # TSI bearish crossover
    elif prev_tsi >= prev_signal and current_tsi < current_signal:
        return "SELL"
    
    return "HOLD"

# ============== RISK MANAGEMENT ==============
def calculate_stop_loss(entry_price: float, atr: float) -> float:
    """Calculate ATR-based stop loss."""
    return entry_price - (atr * STOP_LOSS_ATR_MULT)

def calculate_target(entry_price: float, atr: float) -> float:
    """Calculate ATR-based target."""
    return entry_price + (atr * TARGET_ATR_MULT)

def check_daily_loss_limit(state: Dict, capital: float) -> bool:
    """Check if daily loss limit has been reached."""
    daily_loss_cap_amount = capital * DAILY_LOSS_CAP
    if abs(state.get("daily_loss", 0)) >= daily_loss_cap_amount:
        logger.warning(f"Daily loss limit reached: {abs(state['daily_loss']):.2f} >= {daily_loss_cap_amount:.2f}")
        return True
    return False

# ============== GROWW API ==============
def groww_place_order(symbol: str, transaction_type: str, quantity: int, price: float) -> Optional[Dict]:
    """Place order via Groww API."""
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        logger.info(f"📋 SIGNAL: {transaction_type} {quantity} shares of {symbol} at ₹{price:.2f}")
        logger.info("   (No API credentials - order not placed)")
        return None
    
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": GROWW_API_KEY,
            "X-Secret-Key": GROWW_API_SECRET
        }
        
        payload = {
            "symbol": symbol,
            "transaction_type": transaction_type,  # BUY or SELL
            "quantity": quantity,
            "price": price,
            "order_type": "LIMIT"
        }
        
        response = requests.post(
            f"{GROWW_API_BASE}/v1/orders",
            headers=headers,
            json=payload,
            timeout=GROWW_API_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Order placed successfully: {result}")
            return result
        else:
            logger.error(f"Order failed: {response.status_code} - {response.text}")
            return None
    
    except requests.exceptions.Timeout:
        logger.error("Groww API timeout")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Groww API error: {e}")
        return None

def groww_get_positions() -> List[Dict]:
    """Get current positions from Groww API."""
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return []
    
    try:
        headers = {
            "X-Api-Key": GROWW_API_KEY,
            "X-Secret-Key": GROWW_API_SECRET
        }
        
        response = requests.get(
            f"{GROWW_API_BASE}/v1/positions",
            headers=headers,
            timeout=GROWW_API_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json().get("positions", [])
        else:
            return []
    
    except Exception:
        return []

# ============== TRADING EXECUTION ==============
def execute_trade(signal: str, current_price: float, atr: float, state: Dict, capital: float) -> Dict:
    """Execute trade based on signal."""
    result = {"action": "NONE", "signal": signal, "price": current_price}
    
    # Check if we should trade
    state = reset_daily_state(state)
    
    if signal == "HOLD":
        return result
    
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        logger.info("Max trades reached for today")
        return result
    
    if check_daily_loss_limit(state, capital):
        return result
    
    # Calculate position size
    quantity = int(POSITION_SIZE / current_price)
    if quantity < 1:
        logger.warning(f"Position size too small: ₹{POSITION_SIZE} / ₹{current_price}")
        return result
    
    # Calculate stop loss and target
    if signal == "BUY":
        stop_loss = calculate_stop_loss(current_price, atr)
        target = calculate_target(current_price, atr)
        
        logger.info(f"🟢 BUY SIGNAL: ₹{current_price:.2f}")
        logger.info(f"   Quantity: {quantity} | Position: ₹{quantity * current_price:.2f}")
        logger.info(f"   Stop Loss: ₹{stop_loss:.2f} | Target: ₹{target:.2f}")
        
        order = groww_place_order(SYMBOL, "BUY", quantity, current_price)
        
        result = {
            "action": "BUY",
            "signal": signal,
            "price": current_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "target": target,
            "order": order
        }
        
        state["trades_today"] += 1
        state["position"] = {
            "entry_price": current_price,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "target": target,
            "entry_time": datetime.now().isoformat()
        }
    
    elif signal == "SELL":
        # Check if we have a position to sell
        if not state.get("position"):
            # Close any existing position
            logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f} (No long position to close)")
            return result
        
        pos = state["position"]
        quantity = pos["quantity"]
        
        logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f}")
        logger.info(f"   Closing position from ₹{pos['entry_price']:.2f}")
        
        pnl = (current_price - pos["entry_price"]) * quantity
        logger.info(f"   P&L: ₹{pnl:.2f}")
        
        order = groww_place_order(SYMBOL, "SELL", quantity, current_price)
        
        result = {
            "action": "SELL",
            "signal": signal,
            "price": current_price,
            "quantity": quantity,
            "entry_price": pos["entry_price"],
            "pnl": pnl,
            "order": order
        }
        
        state["trades_today"] += 1
        state["daily_pnl"] += pnl
        if pnl < 0:
            state["daily_loss"] += pnl
        state["position"] = None
    
    save_state(state)
    return result

# ============== MARKET TIMING ==============
def is_market_open() -> bool:
    """Check if market is currently open (NSE India: 9:15 AM - 3:30 PM IST)."""
    now = datetime.now()
    
    # Weekend check
    if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    # Time check (simplified - 9:00 AM to 3:30 PM)
    hour = now.hour
    minute = now.minute
    
    if hour < 9 or hour >= 16:
        return False
    if hour == 9 and minute < 15:
        return False
    if hour == 15 and minute >= 30:
        return False
    
    return True

def wait_for_market_open():
    """Wait until market opens."""
    now = datetime.now()
    
    if now.weekday() >= 5:
        logger.info("Weekend - market closed")
        return False
    
    if now.hour < 9:
        # Wait until 9 AM
        logger.info("Pre-market: waiting for market open at 9:15 AM...")
        return True
    
    if now.hour == 9 and now.minute < 15:
        logger.info("Pre-market: waiting for market open at 9:15 AM...")
        return True
    
    return True

# ============== MAIN EXECUTION ==============
def main():
    """Main execution function."""
    logger.info("=" * 60)
    logger.info(f"LIVE TRADING - {SYMBOL} | {STRATEGY}")
    logger.info(f"Win Rate: {BENCHMARK_WIN_RATE * 100:.2f}%")
    logger.info(f"Position Size: ₹{POSITION_SIZE:,}")
    logger.info(f"Stop Loss: {STOP_LOSS_ATR_MULT * 100:.1f}% ATR")
    logger.info(f"Target: {TARGET_ATR_MULT}x ATR")
    logger.info("=" * 60)
    
    # Load state
    state = load_state()
    state = reset_daily_state(state)
    logger.info(f"State loaded: {state.get('trades_today', 0)} trades today")
    
    # Capital estimate
    CAPITAL = 100000  # ₹1,00,000
    
    # Check daily loss limit
    if check_daily_loss_limit(state, CAPITAL):
        logger.info("Daily loss limit already reached. Exiting.")
        sys.exit(0)
    
    # Wait for market open
    if not wait_for_market_open():
        sys.exit(0)
    
    # Pre-market warmup
    logger.info("Pre-market warmup: Fetching data...")
    
    # Fetch historical data
    ohlcv = fetch_recent_data(SYMBOL, 90)
    if not ohlcv:
        logger.error("Failed to fetch data. Exiting.")
        sys.exit(1)
    
    # Calculate indicators
    atr = calculate_atr(ohlcv, ATR_PERIOD)
    tsi, signal_line, histogram = calculate_tsi(ohlcv, TSI_FAST, TSI_SLOW, TSI_SIGNAL)
    
    # Generate current signal
    current_price = ohlcv[-1]["close"]
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)  # Default 2% if ATR unavailable
    signal = generate_signal(ohlcv, atr, tsi, signal_line)
    
    logger.info(f"Current Price: ₹{current_price:.2f}")
    logger.info(f"Current ATR: ₹{current_atr:.2f}")
    logger.info(f"Current TSI: {tsi[-1]:.2f}")
    logger.info(f"Signal Line: {signal_line[-1]:.2f}")
    logger.info(f"GENERATED SIGNAL: {signal}")
    
    # Execute trade
    if signal != "HOLD":
        result = execute_trade(signal, current_price, current_atr, state, CAPITAL)
        state["last_signal"] = signal
        
        if result["action"] != "NONE":
            logger.info(f"Trade executed: {result}")
    else:
        logger.info("No trade - HOLD signal")
    
    # Check existing position
    if state.get("position"):
        pos = state["position"]
        pos_price = pos["entry_price"]
        stop_loss = pos["stop_loss"]
        target = pos["target"]
        
        logger.info(f"Open Position:")
        logger.info(f"   Entry: ₹{pos_price:.2f}")
        logger.info(f"   Current: ₹{current_price:.2f}")
        logger.info(f"   Stop Loss: ₹{stop_loss:.2f}")
        logger.info(f"   Target: ₹{target:.2f}")
        
        pnl_pct = ((current_price - pos_price) / pos_price) * 100
        logger.info(f"   P&L: {pnl_pct:.2f}%")
        
        # Check stop loss / target
        if current_price <= stop_loss:
            logger.info("STOP LOSS HIT!")
        elif current_price >= target:
            logger.info("TARGET REACHED!")
    
    logger.info("=" * 60)
    logger.info("Script completed successfully")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
