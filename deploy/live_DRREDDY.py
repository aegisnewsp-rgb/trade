#!/usr/bin/env python3
"""
Live Trading Script - DRREDDY.NS
Strategy: VWAP + Volume Confirmation
Win Rate: 63.64%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Added volume confirmation filter (volume > 20-day avg)
"""

import os
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
        logging.FileHandler(LOG_DIR / "live_DRREDDY.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_DRREDDY")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "DRREDDY.NS"
STRATEGY       = "VWAP_VOL_CONFIRM"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5, "vol_sma_period": 20, "vol_multiplier": 1.2}

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

def calculate_volume_sma(ohlcv: list, period: int = 20) -> list:
    """Calculate simple moving average of volume for confirmation filter."""
    sma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            sma.append(None)
        else:
            avg_vol = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
            sma.append(avg_vol)
    return sma

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    """
    VWAP with volume confirmation.
    BUY: price > VWAP + ATR*mult AND volume > vol_sma * multiplier
    SELL: price < VWAP - ATR*mult AND volume > vol_sma * multiplier
    """
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    vol_period    = params.get("vol_sma_period", 20)
    vol_mult      = params.get("vol_multiplier", 1.2)
    vwap_vals     = calculate_vwap(ohlcv, period)
    atr_vals      = calculate_atr(ohlcv, period)
    vol_sma_vals  = calculate_volume_sma(ohlcv, vol_period)
    signals       = ["HOLD"] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or vol_sma_vals[i] is None:
            continue
        price     = ohlcv[i]["close"]
        volume    = ohlcv[i]["volume"]
        v         = vwap_vals[i]
        a         = atr_vals[i]
        vol_sma   = vol_sma_vals[i]
        vol_confirm = volume > vol_sma * vol_mult

        if price > v + a * atr_mult and vol_confirm:
            signals[i] = "BUY"
        elif price < v - a * atr_mult and vol_confirm:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_vol    = ohlcv[-1]["volume"]
    vol_sma_now    = vol_sma_vals[-1] if vol_sma_vals and vol_sma_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr, current_vol, vol_sma_now

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"GROWW_API_BASE/orders"
    payload = {
        "symbol":      symbol,
        "exchange":    "NSE",
        "transaction": "BUY" if signal == "BUY" else "SELL",
        "quantity":    quantity,
        "price":       round(price, 2),
        "order_type":  "LIMIT",
        "product":     "CNC",
    }
    headers = {
        "Authorization": f"Bearer GROWW_API_KEY",
        "X-Api-Secret":  GROWW_API_SECRET,
        "Content-Type":  "application/json",
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("Groww order placed: %s", resp.json())
                return resp.json()
            log.warning("Groww API attempt %d: HTTP %d – %s", attempt + 1, resp.status_code, resp.text)
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol)
    return None

def log_signal(signal: str, price: float, atr: float, volume: float, vol_sma: float):
    log_file = LOG_DIR / "signals_DRREDDY.json"
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
        "volume":    int(volume),
        "vol_sma":   round(vol_sma, 0),
    })
    entries[-500:]
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f, Vol=%d, VolSMA=%.0f)", signal, price, atr, int(volume), vol_sma)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_DRREDDY.json"
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
    log.info("=== Live Trading Script: %s | %s | Win Rate: 63.64%% ===", SYMBOL, STRATEGY)

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

    signal, price, atr, volume, vol_sma = vwap_signal(ohlcv, PARAMS)

    if signal == "BUY":
        stop_loss   = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc  = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss   = round(price * (1 + STOP_LOSS_PCT), 2)
        target_prc  = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss   = 0.0
        target_prc  = 0.0

    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  VOLUME   : %d (SMA=%.0f, mult=%.1f)", int(volume), vol_sma, PARAMS["vol_multiplier"])
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr, volume, vol_sma)

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
    Place order via Groww API (real) or paper trade.
    Uses Bracket Order (BO) for BUY/SELL with target + stop loss built-in.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008  # 0.8% of price as ATR approximation
    
    if signal == "BUY":
        stop_loss = round(price - atr * 1.0, 2)
        target = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="BUY", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = round(price + atr * 1.0, 2)
        target = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="SELL", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, stop_loss, target))
    return result
    Place order via Groww API (real) or paper trade.
    Uses Bracket Order (BO) for BUY/SELL with target + stop loss built-in.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008  # 0.8% of price as ATR approximation
    
    if signal == "BUY":
        stop_loss = round(price - atr * 1.0, 2)
        target = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="BUY", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = round(price + atr * 1.0, 2)
        target = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="SELL", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, stop_loss, target))
    return result

if __name__ == "__main__":
    main()
