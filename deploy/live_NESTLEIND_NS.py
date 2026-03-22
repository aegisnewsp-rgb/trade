#!/usr/bin/env python3
"""
Live Trading Script for NESTLEIND.NS
Strategy: MOMENTUM_DIVERGENCE (RSI Divergence)
Win Rate: 59.93%
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
SYMBOL = "NESTLEIND.NS"
STRATEGY = "MOMENTUM_DIVERGENCE"
BENCHMARK_WIN_RATE = 0.5993

POSITION_SIZE = 7000
DAILY_LOSS_CAP = 0.003
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 0.8
TARGET_ATR_MULT = 4.0

# Strategy Parameters
RSI_PERIOD = 14
LOOKBACK = 20
ATR_PERIOD = 14

# 3-TIER EXIT SYSTEM (enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window
BEST_ENTRY_START = dtime(9, 30)  # 9:30 AM IST
BEST_ENTRY_END   = dtime(14, 30) # 2:30 PM IST
NO_ENTRY_AFTER   = dtime(14, 30) # No new entries after 2:30 PM

def can_new_entry() -> bool:
    """Only allow entries during best entry window."""
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early — waiting for 9:30 AM IST entry window")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM IST — no new entries today")
        return False
    return True

def in_best_entry_window() -> bool:
    now = ist_now().time()
    return BEST_ENTRY_START <= now <= BEST_ENTRY_END

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

LOG_DIR = Path("/tmp")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_NESTLEIND.json")

def setup_logging():
    log_file = LOG_DIR / f"trades_NESTLEIND.log"
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

def calculate_rsi(ohlcv: List[Dict], period: int = 14) -> List[float]:
    rsi_values = []
    for i in range(len(ohlcv)):
        if i < period:
            rsi_values.append(50.0)
            continue
        gains = []
        losses = []
        for j in range(i - period, i):
            change = ohlcv[j+1]["close"] - ohlcv[j]["close"]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_values.append(rsi)
    return rsi_values

def check_consumer_staples_filter() -> dict:
    """
    Check consumer staples / FMCG sector health for NESTLEIND.
    Uses Nifty FMCG index (^NSEFMCG) as benchmark.
    Also checks gold/commodity prices as input cost indicator.
    """
    fmcg = {"symbol": "^NSEFMCG", "trend": "NEUTRAL", "strength": 0.0, "favorable": True}
    if not YFINANCE_AVAILABLE:
        logger.warning("Consumer staples filter: yfinance unavailable")
        return fmcg
    try:
        ticker = yf.Ticker("^NSEFMCG")
        df = ticker.history(period="5d")
        if df.empty or len(df) < 2:
            logger.warning("No FMCG index data available")
            return fmcg
        closes = df["Close"].values
        sma5 = sum(closes[-5:]) / min(5, len(closes))
        current = closes[-1]
        pct_change = ((current - closes[0]) / closes[0]) * 100 if closes[0] > 0 else 0
        
        if current > sma5 * 1.01:
            fmcg["trend"] = "BULLISH"
            fmcg["strength"] = min(pct_change / 2, 5.0)
        elif current < sma5 * 0.99:
            fmcg["trend"] = "BEARISH"
            fmcg["strength"] = max(pct_change / 2, -5.0)
        fmcg["current"] = round(current, 2)
        fmcg["sma5"] = round(sma5, 2)
        # FMCG bullish = favorable for NESTLEIND
        fmcg["favorable"] = fmcg["trend"] != "BEARISH"
        logger.info("FMCG sector: %s (%.2f), strength=%.2f, favorable=%s", 
                    fmcg["trend"], current, fmcg["strength"], fmcg["favorable"])
        
        # Also check gold as commodity input cost (inverse relationship)
        try:
            gold = yf.Ticker("GC=F")
            gold_df = gold.history(period="5d")
            if not gold_df.empty and len(gold_df) >= 2:
                gold_closes = gold_df["Close"].values
                gold_trend = ((gold_closes[-1] - gold_closes[0]) / gold_closes[0]) * 100 if gold_closes[0] > 0 else 0
                fmcg["gold_trend_pct"] = round(gold_trend, 2)
                # High gold prices = higher input costs = unfavorable for FMCG
                if gold_trend > 3:
                    fmcg["favorable"] = fmcg["favorable"] and False
                    logger.info("High gold trend (%.2f%%) signals input cost pressure", gold_trend)
        except Exception:
            pass
    except Exception as e:
        logger.warning("Consumer staples filter check failed: %s", e)
    return fmcg

# RSI filter: BUY>RSI55, SELL<RSI45
# Regime filter: skip DOWNTREND
def get_signal(ohlcv: List[Dict], rsi: List[float], staples: dict = None) -> str:
    if len(ohlcv) < LOOKBACK + 1 or len(rsi) < LOOKBACK + 1:
        return "HOLD"
    
    current_rsi = rsi[-1]
    prev_rsi = rsi[-LOOKBACK]
    price_now = ohlcv[-1]["close"]
    price_then = ohlcv[-LOOKBACK]["close"]
    
    # Bullish divergence: price lower, RSI higher
    if price_now < price_then and current_rsi > prev_rsi:
        # Check consumer staples sector health
        if staples and not staples.get("favorable", True):
            logger.info("BUY signal blocked: consumer staples sector unfavorable (trend=%s)", staples.get("trend"))
            return "HOLD"
        return "BUY"
    # Bearish divergence: price higher, RSI lower
    elif price_now > price_then and current_rsi < prev_rsi:
        return "SELL"
    # Overbought/Oversold
    if current_rsi < 30:
        if staples and not staples.get("favorable", True):
            logger.info("RSI oversold but consumer staples unfavorable - skipping")
            return "HOLD"
        return "BUY"
    elif current_rsi > 70:
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
    except requests.exceptions.Timeout:
        logger.error("Groww API timeout")
        return None
    except requests.exceptions.RequestException as e:
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
        logger.warning(f"Position size too small: ₹{POSITION_SIZE} / ₹{current_price}")
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
            logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f} (No long position to close)")
            return result
        pos = state["position"]
        quantity = pos["quantity"]
        logger.info(f"🔴 SELL SIGNAL: ₹{current_price:.2f} | Closing from ₹{pos['entry_price']:.2f}")
        pnl = (current_price - pos["entry_price"]) * quantity
        logger.info(f"   P&L: ₹{pnl:.2f}")
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
    logger.info(f"Win Rate: {BENCHMARK_WIN_RATE * 100:.2f}%")
    logger.info(f"Position Size: ₹{POSITION_SIZE:,} | SL: {STOP_LOSS_ATR_MULT*100:.1f}% ATR | TGT: {TARGET_ATR_MULT}x ATR")
    logger.info("=" * 60)
    state = load_state()
    state = reset_daily_state(state)
    CAPITAL = 100000
    if check_daily_loss_limit(state, CAPITAL):
        logger.info("Daily loss limit already reached. Exiting.")
        sys.exit(0)
    ohlcv = fetch_recent_data(SYMBOL, 90)
    if not ohlcv:
        logger.error("Failed to fetch data. Exiting.")
        sys.exit(1)
    atr = calculate_atr(ohlcv, ATR_PERIOD)
    rsi = calculate_rsi(ohlcv, RSI_PERIOD)
    current_price = ohlcv[-1]["close"]
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)
    
    # Check consumer staples sector health
    staples = check_consumer_staples_filter()
    
    signal = generate_signal(ohlcv, rsi, staples)
    logger.info(f"Current Price: ₹{current_price:.2f} | ATR: ₹{current_atr:.2f} | RSI: {rsi[-1]:.2f}")
    logger.info(f"GENERATED SIGNAL: {signal}")
    if signal != "HOLD":
        result = execute_trade(signal, current_price, current_atr, state, CAPITAL)
        state["last_signal"] = signal
        if result["action"] != "NONE":
            logger.info(f"Trade executed: {result}")
    else:
        logger.info("No trade - HOLD signal")
    if state.get("position"):
        pos = state["position"]
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
        logger.info(f"Open Position: Entry ₹{pos['entry_price']:.2f} | Current ₹{current_price:.2f} | P&L: {pnl_pct:.2f}%")
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
