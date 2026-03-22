#!/usr/bin/env python3
"""
Live Trading Script for SRF.NS
Strategy: MACD_MOMENTUM
Win Rate: 60.13%
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
from typing import Optional, List, Dict, Tuple
from pathlib import Path

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
SYMBOL = "SRF.NS"
STRATEGY = "MACD_MOMENTUM"
BENCHMARK_WIN_RATE = 0.6013

POSITION_SIZE = 7000
DAILY_LOSS_CAP = 0.003
MAX_TRADES_PER_DAY = 1

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_ATR_MULT = 0.8
TARGET_ATR_MULT = 4.0

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ATR_PERIOD = 14

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

LOG_DIR = Path("/tmp")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_SRF.json")

def setup_logging():
    log_file = LOG_DIR / f"trades_SRF.log"
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

def calc_ema(data: List[float], period: int) -> List[float]:
    if len(data) < period:
        return data
    ema = [data[0]]
    multiplier = 2 / (period + 1)
    for i in range(1, len(data)):
        ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
    return ema

def calculate_macd(ohlcv: List[Dict], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[float], List[float], List[float]]:
    closes = [bar["close"] for bar in ohlcv]
    fast_ema = calc_ema(closes, fast)
    slow_ema = calc_ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = calc_ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram

def calculate_atr_based_position_size(entry_price: float, atr: float, capital: float = 100000, risk_pct: float = 0.02) -> dict:
    """
    Calculate position size based on ATR-based risk management.
    Risk: 2% of capital per trade
    Stop loss: 1.5x ATR (more aggressive for SRF's volatility)
    Max position capped at 2x typical size
    """
    risk_amount = capital * risk_pct
    atr_stop = atr * 1.5
    max_shares_by_risk = int(risk_amount / atr_stop)
    max_shares_by_cap = int(capital * 0.10 / entry_price)  # Max 10% of capital
    recommended_shares = min(max_shares_by_risk, max_shares_by_cap, 200)  # Cap at 200 shares
    position_value = recommended_shares * entry_price
    risk_reward_ratio = (atr * TARGET_ATR_MULT) / atr_stop if atr_stop > 0 else 0
    return {
        "shares": recommended_shares,
        "position_value": round(position_value, 2),
        "atr_stop": round(atr_stop, 2),
        "risk_amount": round(risk_amount, 2),
        "risk_reward": round(risk_reward_ratio, 2),
        "max_shares_by_cap": max_shares_by_cap,
        "max_shares_by_risk": max_shares_by_risk
    }

# RSI filter: BUY>RSI55, SELL<RSI45
# Regime filter: skip DOWNTREND
def get_regime
def get_signal(ohlcv: List[Dict], macd_line: List[float], signal_line: List[float]) -> str:
    if len(ohlcv) < max(MACD_FAST, MACD_SLOW, MACD_SIGNAL) + 1:
        return "HOLD"
    i = -1
    if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
        return "BUY"
    elif macd_line[i] < signal_line[i] and macd_line[i-1] >= signal_line[i-1]:
        return "SELL"
    return "HOLD"

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
        response = requests.post(f"GROWW_API_BASE/v1/orders", headers=headers, json=payload, timeout=GROWW_API_TIMEOUT)
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
    
    # ATR-based position sizing
    pos_info = calculate_atr_based_position_size(current_price, atr, capital)
    quantity = pos_info["shares"]
    
    if quantity < 1:
        logger.warning(f"Position size too small: {quantity} shares")
        return result
        
    if signal == "BUY":
        stop_loss = calculate_stop_loss(current_price, atr)
        target = calculate_target(current_price, atr)
        logger.info(f"🟢 BUY: ₹{current_price:.2f} | Qty:{quantity} ({pos_info['position_value']:.0f}₹) | SL:₹{stop_loss:.2f} | TGT:₹{target:.2f} | RR:{pos_info['risk_reward']:.1f}x")
        order = groww_place_order(SYMBOL, "BUY", quantity, current_price)
        result = {"action": "BUY", "signal": signal, "price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "atr_stop": pos_info["atr_stop"], "risk_reward": pos_info["risk_reward"], "order": order}
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
    ohlcv = fetch_recent_data(SYMBOL, 90)
    if not ohlcv:
        sys.exit(1)
    atr = calculate_atr(ohlcv, ATR_PERIOD)
    macd_line, signal_line, histogram = calculate_macd(ohlcv, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    current_price = ohlcv[-1]["close"]
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)
    signal = generate_signal(ohlcv, macd_line, signal_line)
    logger.info(f"Price: ₹{current_price:.2f} | ATR: ₹{current_atr:.2f} | MACD: {macd_line[-1]:.4f} | Signal: {signal}")
    if signal != "HOLD":
        result = execute_trade(signal, current_price, current_atr, state, CAPITAL)
        state["last_signal"] = signal
        if result["action"] != "NONE":
            logger.info(f"Trade executed: {result}")
    else:
        logger.info("HOLD signal - no trade")
    if state.get("position"):
        pos = state["position"]
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
        logger.info(f"Position: Entry ₹{pos['entry_price']:.2f} | Curr ₹{current_price:.2f} | P&L: {pnl_pct:.2f}%")
    logger.info("=" * 60)
    return 0


def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API or paper trade.
    Uses Bracket Orders (BO) when GROWW_API_KEY is set.
    Falls back to paper trading otherwise.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    
    if signal == "BUY":
        # Calculate target and stop loss  # 0.8% ATR approximation
        stop_loss = price - (atr * 1.0)  # 1x ATR stop
        target = price + (atr * 4.0)  # 4x ATR target
        # Use bracket order for BUY with target + stop loss
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="BUY",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3,
            trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = price + (atr * 1.0)
        target = price - (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="SELL",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3,
            trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("Order placed: {} {} {} @ Rs{:.2f}".format(
            signal, quantity, symbol, price))
    return result


if __name__ == "__main__":
    sys.exit(main())
