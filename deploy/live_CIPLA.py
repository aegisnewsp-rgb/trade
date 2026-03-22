#!/usr/bin/env python3
"""
Live Trading Script - CIPLA.NS (Cipla Ltd)
Strategy: MOMENTUM_DIVERGENCE (RSI Divergence)
Win Rate: 60.07%
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x | Daily Loss Cap: 0.3%
Added: 2026-03-22 | Defensive pharma sector, resilient in market pullback
"""

import os
import sys
import time
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
except ImportError:
    YFINANCE_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL             = "CIPLA.NS"
STRATEGY           = "MOMENTUM_DIVERGENCE"
BENCHMARK_WIN_RATE = 0.6007

POSITION_SIZE      = 7000
DAILY_LOSS_CAP     = 0.003
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 0.8
TARGET_ATR_MULT    = 4.0

RSI_PERIOD   = 14
LOOKBACK     = 20
ATR_PERIOD   = 14

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in"
GROWW_TIMEOUT    = 30

LOG_DIR    = Path(__file__).parent / "logs"
STATE_FILE = Path(__file__).parent / "state_CIPLA.json"
LOG_DIR.mkdir(exist_ok=True)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_CIPLA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_CIPLA")

IST_TZ_OFFSET = 5.5

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return __import__("datetime").time(9, 15) <= now.time() <= __import__("datetime").time(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return __import__("datetime").time(9, 0) <= now.time() < __import__("datetime").time(9, 15)

# ── State ──────────────────────────────────────────────────────────────────────

def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to load state: %s", e)
    return {"trades_today": 0, "last_trade_date": None, "daily_pnl": 0, "daily_loss": 0}

def save_state(state: Dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.warning("Failed to save state: %s", e)

def reset_daily_state(state: Dict) -> Dict:
    today = date.today().isoformat()
    if state.get("last_trade_date") != today:
        state["trades_today"]  = 0
        state["last_trade_date"] = today
        state["daily_pnl"]  = 0
        state["daily_loss"] = 0
    return state

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch_recent_data(symbol: str, days: int = 90) -> Optional[List[Dict]]:
    if not YFINANCE_AVAILABLE:
        log.error("yfinance not available")
        return None
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d")
        if df.empty:
            log.error("No data returned for %s", symbol)
            return None
        ohlcv = []
        for idx, row in df.iterrows():
            ohlcv.append({
                "date":   idx.isoformat(),
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        log.info("Fetched %d days of data for %s", len(ohlcv), symbol)
        return ohlcv
    except Exception as e:
        log.error("Failed to fetch data: %s", e)
        return None

# ── Indicators ─────────────────────────────────────────────────────────────────

def calculate_atr(ohlcv: List[Dict], period: int = 14) -> List[Optional[float]]:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high = bar["high"]
        low  = bar["low"]
        tr   = high - low if prev_close is None else max(
            high - low, abs(high - prev_close), abs(low - prev_close)
        )
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
        gains, losses = [], []
        for j in range(i - period, i):
            change = ohlcv[j + 1]["close"] - ohlcv[j]["close"]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
    return rsi_values

def detect_momentum_divergence(ohlcv: List[Dict], rsi: List[float]) -> str:
    """
    MOMENTUM_DIVERGENCE strategy:
    - Bullish divergence: price making lower lows, RSI making higher lows → BUY
    - Bearish divergence: price making higher highs, RSI making lower highs → SELL
    - RSI oversold/overbought confirmation
    """
    if len(ohlcv) < LOOKBACK + 1 or len(rsi) < LOOKBACK + 1:
        return "HOLD"

    current_rsi  = rsi[-1]
    prev_rsi     = rsi[-LOOKBACK]
    price_now    = ohlcv[-1]["close"]
    price_then   = ohlcv[-LOOKBACK]["close"]

    # Bullish divergence: price ↓, RSI ↑
    if price_now < price_then and current_rsi > prev_rsi:
        return "BUY"
    # Bearish divergence: price ↑, RSI ↓
    elif price_now > price_then and current_rsi < prev_rsi:
        return "SELL"
    # RSI oversold / overbought zones
    if current_rsi < 30:
        return "BUY"
    elif current_rsi > 70:
        return "SELL"
    return "HOLD"

# ── Trading ─────────────────────────────────────────────────────────────────────

def check_daily_loss_limit(state: Dict, capital: float) -> bool:
    daily_cap = capital * DAILY_LOSS_CAP
    if abs(state.get("daily_loss", 0)) >= daily_cap:
        log.warning("Daily loss limit reached: %.2f >= %.2f", abs(state["daily_loss"]), daily_cap)
        return True
    return False

def groww_place_order(symbol: str, transaction: str, quantity: int, price: float) -> Optional[Dict]:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        log.info("📋 SIGNAL: %s %d shares of %s at ₹%.2f (paper mode)", transaction, quantity, symbol, price)
        return None
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key":    GROWW_API_KEY,
        "X-Secret-Key": GROWW_API_SECRET,
    }
    payload = {
        "symbol":            symbol,
        "transaction_type": transaction,
        "quantity":         quantity,
        "price":            round(price, 2),
        "order_type":       "LIMIT",
        "exchange":         "NSE",
        "product":          "CNC",
    }
    for attempt in range(3):
        try:
            resp = requests.post(f"GROWW_API_BASE/v1/orders", headers=headers, json=payload, timeout=GROWW_TIMEOUT)
            if resp.status_code in (200, 201):
                result = resp.json()
                log.info("Order placed: %s", result)
                return result
            log.warning("Groww API attempt %d: HTTP %d – %s", attempt + 1, resp.status_code, resp.text)
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol)
    return None

def log_signal(signal: str, price: float, atr: float, rsi: float):
    log_file = LOG_DIR / "signals_CIPLA.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except Exception:
            entries = []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol":    SYMBOL,
        "strategy":  STRATEGY,
        "signal":    signal,
        "price":     round(price, 4),
        "atr":       round(atr, 4),
        "rsi":       round(rsi, 2),
    })
    entries[-500:]
    log_file.write_text(json.dumps(entries, indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f, RSI=%.1f)", signal, price, atr, rsi)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Live Trading: %s | %s | Win Rate: %.2f%% | Pharma defensive ===",
             SYMBOL, STRATEGY, BENCHMARK_WIN_RATE * 100)

    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)

    if not is_market_open():
        log.info("Market closed. Exiting.")
        return

    state = load_state()
    state = reset_daily_state(state)

    if check_daily_loss_limit(state, POSITION_SIZE):
        log.warning("Daily loss cap (0.3%%) hit – skipping today.")
        return

    log.info("Fetching market data...")
    ohlcv = fetch_recent_data(SYMBOL, days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return

    atr_vals = calculate_atr(ohlcv, ATR_PERIOD)
    rsi_vals = calculate_rsi(ohlcv, RSI_PERIOD)
    signal   = detect_momentum_divergence(ohlcv, rsi_vals)

    current_price = ohlcv[-1]["close"]
    current_atr  = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi  = rsi_vals[-1] if rsi_vals else 50.0

    if signal == "BUY":
        stop_loss = round(current_price - STOP_LOSS_ATR_MULT * current_atr, 2)
        target   = round(current_price + TARGET_ATR_MULT * current_atr, 2)
    elif signal == "SELL":
        stop_loss = round(current_price + STOP_LOSS_ATR_MULT * current_atr, 2)
        target   = round(current_price - TARGET_ATR_MULT * current_atr, 2)
    else:
        stop_loss = target = 0.0

    quantity = max(1, int(POSITION_SIZE / current_price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", current_price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION_SIZE)
    if current_atr > 0:
        log.info("  ATR      : %.4f", current_atr)
        log.info("  RSI      : %.1f", current_rsi)
        log.info("  STOP     : ₹%.2f  (%.1f× ATR)", stop_loss, STOP_LOSS_ATR_MULT)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target, TARGET_ATR_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, current_price, current_atr, current_rsi)

    if signal != "HOLD":
        tx = "BUY" if signal == "BUY" else "SELL"
        result = groww_place_order(SYMBOL, tx, quantity, current_price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.info("📋 No Groww credentials – paper mode signal logged.")
    else:
        log.info("HOLD – no action taken.")


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
        # Calculate target and stop loss
        atr = price * 0.008  # 0.8% ATR approximation
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
        atr = price * 0.008
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
    main()
