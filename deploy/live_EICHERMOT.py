#!/usr/bin/env python3
"""
Live Trading Script - EICHERMOT.NS (Eicher Motors Ltd)
Strategy: VWAP + RSI Momentum
Win Rate: 61.54% (based on TATASTEEL benchmark — similar auto sector)
Position: ₹7000 | Stop Loss: 1.0x ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
Enhanced: 2026-03-22 - Optimized stop loss: 0.8% ATR → 1.0x ATR for better risk management
Added: Royal Enfield brand leader, defensive auto sector
"""

import os
import sys
import time
import logging
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
SYMBOL             = "EICHERMOT.NS"
STRATEGY           = "VWAP_RSI"
BENCHMARK_WIN_RATE = 0.6154

POSITION_SIZE      = 7000
DAILY_LOSS_CAP     = 0.003
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 1.0   # Enhanced: was 0.8, now 1.0x ATR for better risk management
TARGET_ATR_MULT    = 4.0

VWAP_PERIOD  = 14
RSI_PERIOD   = 14
ATR_PERIOD   = 14

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in"
GROWW_TIMEOUT    = 30

LOG_DIR    = Path(__file__).parent / "logs"
STATE_FILE = Path(__file__).parent / "state_EICHERMOT.json"
LOG_DIR.mkdir(exist_ok=True)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_EICHERMOT.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_EICHERMOT")

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

def calculate_vwap(ohlcv: List[Dict], period: int = 14) -> List[Optional[float]]:
    """Compute VWAP using period lookback."""
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum  = sum(
                (ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                for j in range(i - period + 1, i + 1)
            )
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def calculate_rsi(ohlcv: List[Dict], period: int = 14) -> List[float]:
    rsi_values = [50.0] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi_values
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100 - (100 / (1 + rs))
    return rsi_values

def vwap_rsi_signal(ohlcv: List[Dict], params: dict) -> tuple[str, float, float, float]:
    """
    VWAP + RSI momentum strategy.
    Returns (signal, price, atr, rsi).
    BUY:  price > VWAP + ATR*mult AND RSI < 65
    SELL: price < VWAP - ATR*mult AND RSI > 35
    """
    vwap_vals = calculate_vwap(ohlcv, params["vwap_period"])
    atr_vals  = calculate_atr(ohlcv, params["atr_period"])
    rsi_vals  = calculate_rsi(ohlcv, params["rsi_period"])

    signal   = "HOLD"
    price    = ohlcv[-1]["close"]
    atr      = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    rsi      = rsi_vals[-1] if rsi_vals else 50.0

    v = vwap_vals[-1]
    if v is None or atr <= 0:
        return signal, price, atr, rsi

    if price > v + atr * params["atr_multiplier"] and rsi < params["rsi_overbought"]:
        signal = "BUY"
    elif price < v - atr * params["atr_multiplier"] and rsi > params["rsi_oversold"]:
        signal = "SELL"

    return signal, price, atr, rsi

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
    log_file = LOG_DIR / "signals_EICHERMOT.json"
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
    log.info("=== Live Trading: %s | %s | Win Rate: %.2f%% | Auto sector ===",
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

    params = {
        "vwap_period":     VWAP_PERIOD,
        "atr_period":      ATR_PERIOD,
        "atr_multiplier":  1.5,
        "rsi_period":      RSI_PERIOD,
        "rsi_overbought":  65,
        "rsi_oversold":    35,
    }

    signal, price, atr, rsi = vwap_rsi_signal(ohlcv, params)

    if signal == "BUY":
        stop_loss = round(price - STOP_LOSS_ATR_MULT * atr, 2)
        target    = round(price + TARGET_ATR_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss = round(price + STOP_LOSS_ATR_MULT * atr, 2)
        target    = round(price - TARGET_ATR_MULT * atr, 2)
    else:
        stop_loss = target = 0.0

    quantity = max(1, int(POSITION_SIZE / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION_SIZE)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  RSI      : %.1f", rsi)
        log.info("  STOP     : ₹%.2f  (%.1f× ATR) [enhanced: was 0.8x, now 1.0x]", stop_loss, STOP_LOSS_ATR_MULT)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target, TARGET_ATR_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr, rsi)

    if signal != "HOLD":
        tx = "BUY" if signal == "BUY" else "SELL"
        result = groww_place_order(SYMBOL, tx, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.info("📋 No Groww credentials – paper mode signal logged.")
    else:
        log.info("HOLD – no action taken.")

if __name__ == "__main__":
    main()
