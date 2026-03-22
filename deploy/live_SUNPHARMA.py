#!/usr/bin/env python3
"""
Live Trading Script - SUNPHARMA.NS (Sun Pharmaceutical Industries)
Strategy: VWAP Momentum
Source: NSE momentum scan (2026-03-22) — +1.50% with 1.41x volume ratio
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x | Daily Loss Cap: 0.3%
"""

import os

import sys
from pathlib import Path
import sys
import json
import time
import logging
import groww_api
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
        logging.FileHandler(LOG_DIR / "live_SUNPHARMA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SUNPHARMA")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "SUNPHARMA.NS"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5, "rsi_period": 14,
                  "rsi_overbought": 65, "rsi_oversold": 35}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

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
                {
                    "date":   str(idx.date()),
                    "open":   float(row["Open"]),
                    "high":   float(row["High"]),
                    "low":    float(row["Low"]),
                    "close":  float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
                for idx, row in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching data: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv: list, period: int = 14) -> list:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"],
            abs(bar["high"] - prev_close),
            abs(bar["low"]  - prev_close),
        )
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum  = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                          for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    rsi = []
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    if len(gains) < period:
        return [None] * len(ohlcv)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(len(ohlcv)):
        if i < period:
            rsi.append(None)
        elif i == period:
            rs = avg_gain / avg_loss if avg_loss > 0 else 0
            rsi.append(100 - (100 / (1 + rs)))
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 0
            rsi.append(100 - (100 / (1 + rs)))
    return rsi

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    rsi_period    = params["rsi_period"]
    rsi_ob        = params["rsi_overbought"]
    rsi_os        = params["rsi_oversold"]
    vwap_vals     = calculate_vwap(ohlcv, period)
    atr_vals      = calculate_atr(ohlcv, period)
    rsi_vals      = calculate_rsi(ohlcv, rsi_period)
    signals       = ["HOLD"] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        price    = ohlcv[i]["close"]
        v        = vwap_vals[i]
        a        = atr_vals[i]
        r        = rsi_vals[i]
        band     = a * atr_mult
        if price > v + band and r < rsi_ob:
            signals[i] = "BUY"
        elif price < v - band and r > rsi_os:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr, current_rsi

def log_signal(signal: str, price: float, atr: float, rsi: float):
    log_file = LOG_DIR / "signals_SUNPHARMA.json"
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
        "rsi":       round(rsi, 4),
    })
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f, RSI=%.2f)", signal, price, atr, rsi)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_SUNPHARMA.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception:
            pass
    return False

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Live Trading Script: %s | %s ===", SYMBOL, STRATEGY)
    log.info("Source: NSE momentum scan (2026-03-22) — +1.50%%, 1.41x vol ratio")

    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)

    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return

    today_str = ist_now().strftime("%Y-%m-%d")
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return

    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return

    signal, price, atr, rsi = vwap_signal(ohlcv, PARAMS)

    if signal == "BUY":
        stop_loss  = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price * (1 + STOP_LOSS_PCT), 2)
        target_prc = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss  = 0.0
        target_prc = 0.0

    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  RSI      : %.2f", rsi)
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr, rsi)

    if signal != "HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.warning("⚠ Groww order could not be placed – signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials found – signal printed only (paper mode).")

def place_groww_order(symbol, signal, quantity, price):
    """
    Emit trading signal to queue for Master Orchestrator.
    Orchestrator coalesces all signals and places orders via Groww API
    (single connection = no rate limiting across 468 scripts).
    Paper mode: orchestrator prints signals instead of placing.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from signals.schema import emit_signal
        # Get ATR from script's atr variable if available
        _atr = price * 0.008
        try:
            if 'atr' in globals() and isinstance(globals().get('atr'), (int, float)):
                _atr = float(globals()['atr'])
        except:
            _atr = price * 0.008
        _strategy = str(globals().get('STRATEGY_NAME', 'VWAP'))
        emit_signal(
            symbol=symbol, signal=signal, price=price,
            quantity=quantity, strategy=_strategy, atr=_atr,
            metadata={"source": Path(__file__).name}
        )
        return {"status": "queued", "symbol": symbol, "signal": signal}
    except ImportError:
        print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
        return {"status": "paper", "symbol": symbol, "signal": signal}


def place_order(symbol, signal, quantity, price):
    return place_groww_order(symbol, signal, quantity, price)

if __name__ == "__main__":