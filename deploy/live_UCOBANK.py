#!/usr/bin/env python3
"""
Live Trading Script - UCOBANK.NS
Strategy: ADX_TREND
Win Rate: 63.04%
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_UCOBANK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_UCOBANK")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "UCOBANK.NS"
STRATEGY       = "ADX_TREND"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"adx_period": 14, "adx_threshold": 25, "atr_multiplier": 1.5}

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

def calculate_adx(ohlcv: list, period: int = 14) -> tuple[list, list, list]:
    """
    Calculate ADX, +DI, -DI using the standard Wilder smoothing method.
    Returns (adx, plus_di, minus_di) lists.
    """
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv), [None] * len(ohlcv), [None] * len(ohlcv)

    # Step 1: True Range & Directional Movement
    tr_list = []
    plus_dm = []
    minus_dm = []
    prev_close = None

    for bar in ohlcv:
        tr = bar["high"] - bar["low"]
        dm_plus = 0.0
        dm_minus = 0.0

        if prev_close is not None:
            up_move = bar["high"] - ohlcv[ohlcv.index(bar) - 1]["high"]
            down_move = ohlcv[ohlcv.index(bar) - 1]["low"] - bar["low"]

            if up_move > down_move and up_move > 0:
                dm_plus = up_move
            if down_move > up_move and down_move > 0:
                dm_minus = down_move

        tr_list.append(tr)
        plus_dm.append(dm_plus)
        minus_dm.append(dm_minus)
        prev_close = bar["close"]

    # Step 2: Wilder smooth (EWM with alpha = 1/period)
    def wilder_smooth(values: list, period: int) -> list:
        result = []
        for i in range(len(values)):
            if i < period - 1:
                result.append(None)
            elif i == period - 1:
                result.append(sum(values[:period]))
            else:
                smoothed = result[-1] - (result[-1] / period) + values[i]
                result.append(smoothed)
        return result

    smoothed_tr = wilder_smooth(tr_list, period)
    smoothed_plus_dm = wilder_smooth(plus_dm, period)
    smoothed_minus_dm = wilder_smooth(minus_dm, period)

    # Step 3: DI indicators
    plus_di = []
    minus_di = []
    dx = []

    for i in range(len(ohlcv)):
        if i < period - 1 or smoothed_tr[i] is None or smoothed_tr[i] == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
        else:
            pdi = 100 * smoothed_plus_dm[i] / smoothed_tr[i]
            mdi = 100 * smoothed_minus_dm[i] / smoothed_tr[i]
            plus_di.append(pdi)
            minus_di.append(mdi)
            dx.append(abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0)

    # Step 4: ADX = Wilder smooth of DX
    adx = wilder_smooth(dx, period)

    return adx, plus_di, minus_di

def adx_trend_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    ADX_TREND strategy:
    - ADX > threshold → trend strength confirmed
    - +DI > -DI → BUY
    - -DI > +DI → SELL
    - Otherwise → HOLD
    """
    period     = params["adx_period"]
    threshold  = params["adx_threshold"]
    adx_vals, plus_di, minus_di = calculate_adx(ohlcv, period)
    atr_vals   = calculate_atr(ohlcv, period)

    current_adx  = adx_vals[-1]   if adx_vals   and adx_vals[-1]   is not None else 0.0
    current_pdi  = plus_di[-1]    if plus_di    and plus_di[-1]    is not None else 0.0
    current_mdi  = minus_di[-1]   if minus_di   and minus_di[-1]   is not None else 0.0
    current_atr  = atr_vals[-1]   if atr_vals   and atr_vals[-1]   is not None else 0.0
    current_price = ohlcv[-1]["close"]

    signal = "HOLD"
    if current_adx > threshold:
        if current_pdi > current_mdi:
            signal = "BUY"
        elif current_mdi > current_pdi:
            signal = "SELL"

    log.info("ADX=%.2f | +DI=%.2f | -DI=%.2f | Signal=%s", current_adx, current_pdi, current_mdi, signal)
    return signal, current_price, current_atr

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

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_UCOBANK.json"
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
    cap_file = LOG_DIR / "daily_pnl_UCOBANK.json"
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
    log.info("=== Live Trading Script: %s | %s | Win Rate: 63.04%% ===", SYMBOL, STRATEGY)

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

    signal, price, atr = adx_trend_signal(ohlcv, PARAMS)

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
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr)

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
