#!/usr/bin/env python3
"""
Live Trading Script - LTIM.NS (L&T Infotech / Larsen & Toubro Infotech)
Strategy: VWAP + RSI + Volume Confirmation (v4 enhanced)
Added: 2026-03-22 | Volume surge 5.94x avg, 5D +2.19%, 33% below 52w high
Position: ₹7000 | Stop Loss: 1.5x ATR | Target: 3.5x ATR | Daily Loss Cap: 0.3%
Enhancements:
  - RSI filter (14): BUY only RSI > 40, SELL only RSI < 60
  - Volume confirmation: volume > 20-day SMA volume
  - ATR-based stop (replaces fixed 0.8%)
  - Volatility filter: skip when ATR > 20-day ATR SMA (choppy market)
Research: nse_market_research_2026-03-22.md | momentum scan 2026-03-22 17:28 UTC
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
        logging.FileHandler(LOG_DIR / "live_LTIM.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_LTIM")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL             = "LTIM.NS"
STRATEGY           = "VWAP+RSI+VOL"
POSITION           = 7000
STOP_LOSS_ATR_MULT = 1.5
TARGET_ATR_MULT    = 3.5
DAILY_LOSS_CAP     = 0.003
PARAMS = {
    "vwap_period":       14,
    "atr_multiplier":    1.5,
    "rsi_period":        14,
    "rsi_buy_min":       40,
    "rsi_sell_max":      60,
    "vol_sma_period":    20,
    "vol_confirm_mult":   1.2,
    "atr_vol_period":    20,
}

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
    rsi = [None] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        delta = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi[i + 1] = 100 - (100 / (1 + rs))
    return rsi

def calculate_vol_sma(ohlcv: list, period: int = 20) -> list:
    vol_sma = [None] * len(ohlcv)
    for i in range(period - 1, len(ohlcv)):
        vol_sma[i] = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
    return vol_sma

def calculate_atr_sma(atr_vals: list, period: int = 20) -> list:
    atr_sma = [None] * len(atr_vals)
    for i in range(len(atr_vals)):
        window = [v for v in atr_vals[max(0, i - period + 1):i + 1] if v is not None]
        if len(window) >= period // 2:
            atr_sma[i] = sum(window) / len(window)
    return atr_sma

def vwap_enhanced_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    vwap_period  = params["vwap_period"]
    rsi_period   = params["rsi_period"]
    rsi_buy_min  = params["rsi_buy_min"]
    rsi_sell_max = params["rsi_sell_max"]
    vol_period   = params["vol_sma_period"]
    vol_mult     = params["vol_confirm_mult"]
    atr_vol_p    = params["atr_vol_period"]

    vwap_vals = calculate_vwap(ohlcv, vwap_period)
    atr_vals  = calculate_atr(ohlcv, vwap_period)
    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    vol_sma   = calculate_vol_sma(ohlcv, vol_period)
    atr_sma   = calculate_atr_sma(atr_vals, atr_vol_p)

    signals   = ["HOLD"] * len(ohlcv)
    start_idx = max(vwap_period, rsi_period, vol_period, atr_vol_p)

    for i in range(start_idx, len(ohlcv)):
        if None in (vwap_vals[i], atr_vals[i], rsi_vals[i], vol_sma[i], atr_sma[i]):
            continue
        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        vol_avg = vol_sma[i]

        # Volatility filter
        if atr_sma[i] is not None and a > atr_sma[i] * 1.15:
            continue

        # Volume confirmation
        if vol < vol_avg * vol_mult:
            continue

        if price > v + a * params["atr_multiplier"]:
            if rsi > rsi_buy_min:
                signals[i] = "BUY"
        elif price < v - a * params["atr_multiplier"]:
            if rsi < rsi_sell_max:
                signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_LTIM.json"
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
    })
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_LTIM.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception:
            pass
    return False

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Live Trading Script: %s | %s | Vol 5.94x avg | 33%% below 52w high ===",
             SYMBOL, STRATEGY)

    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)

    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return

    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return

    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=120)
    if not ohlcv or len(ohlcv) < 60:
        log.error("Insufficient data for %s", SYMBOL)
        return

    signal, price, atr = vwap_enhanced_signal(ohlcv, PARAMS)

    if signal == "BUY":
        stop_loss  = round(price - STOP_LOSS_ATR_MULT * atr, 2)
        target_prc = round(price + TARGET_ATR_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price + STOP_LOSS_ATR_MULT * atr, 2)
        target_prc = round(price - TARGET_ATR_MULT * atr, 2)
    else:
        stop_loss  = 0.0
        target_prc = 0.0

    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s (v4 enhanced)", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : ₹%.2f  (%.1f× ATR)", stop_loss, STOP_LOSS_ATR_MULT)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_ATR_MULT)
    log.info("  FILTERS  : RSI(%.0f-%.0f) | Vol>avg×%.1f | Vol-chop filter",
             PARAMS["rsi_buy_min"], PARAMS["rsi_sell_max"], PARAMS["vol_confirm_mult"])
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr)

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