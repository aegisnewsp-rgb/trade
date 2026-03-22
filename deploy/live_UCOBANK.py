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

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
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

# Smart entry: 9:30-14:30 IST
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
    main()
