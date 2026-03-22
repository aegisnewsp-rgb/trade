#!/usr/bin/env python3
"""
Live Trading Script - SIEMENS.NS
Strategy: VWAP + Momentum (dual-confirmation)
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0× ATR | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_SIEMENS.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SIEMENS")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "SIEMENS.NS"
STRATEGY       = "VWAP_MOMENTUM"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008    # 0.8% ATR stop
TARGET_MULT    = 4.0      # 4× ATR target
DAILY_LOSS_CAP = 0.003    # 0.3% daily loss cap
PARAMS         = {
    "vwap_period":     14,
    "mom_period":      14,
    "rsi_period":      14,
    "atr_period":      14,
    "mom_threshold":   0.0,   # momentum > 0 for BUY
    "rsi_buy_min":     50,    # RSI must be >= 50 for BUY signal
    "rsi_sell_max":    50,    # RSI must be <= 50 for SELL signal
}

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

def fetch_recent_data(days: int = 90, retries: int = 3) -> list | None:
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
    """Compute RSI using the Wilder smoothing method."""
    rsi = [None] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi

    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    if len(gains) < period:
        return rsi

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi[i + 1] = 100 - (100 / (1 + rs))

    return rsi

def calculate_momentum(ohlcv: list, period: int = 14) -> list:
    """Momentum: difference between current close and close `period` bars ago."""
    mom = []
    for i in range(len(ohlcv)):
        if i < period:
            mom.append(None)
        else:
            mom.append(ohlcv[i]["close"] - ohlcv[i - period]["close"])
    return mom

def vwap_momentum_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    VWAP + Momentum dual-confirmation strategy:
    BUY  if price > VWAP  AND momentum > 0  AND RSI >= rsi_buy_min
    SELL if price < VWAP  AND momentum < 0  AND RSI <= rsi_sell_max
    Otherwise HOLD.
    """
    vwap_p   = params["vwap_period"]
    mom_p    = params["mom_period"]
    rsi_p    = params["rsi_period"]

    vwap_vals = calculate_vwap(ohlcv, vwap_p)
    mom_vals  = calculate_momentum(ohlcv, mom_p)
    rsi_vals  = calculate_rsi(ohlcv, rsi_p)
    atr_vals  = calculate_atr(ohlcv, params.get("atr_period", 14))

    lookback = max(vwap_p, mom_p, rsi_p)

    # Work from the first fully-populated index
    start = lookback
    current_signal = "HOLD"

    for i in range(start, len(ohlcv)):
        price      = ohlcv[i]["close"]
        v          = vwap_vals[i]
        m          = mom_vals[i]
        r          = rsi_vals[i]
        a          = atr_vals[i]

        if v is None or m is None or r is None or a is None:
            continue

        # Dual confirmation: VWAP alignment + momentum + RSI
        if (price > v) and (m > params["mom_threshold"]) and (r >= params["rsi_buy_min"]):
            current_signal = "BUY"
        elif (price < v) and (m < -params["mom_threshold"]) and (r <= params["rsi_sell_max"]):
            current_signal = "SELL"
        else:
            current_signal = "HOLD"

    current_price = ohlcv[-1]["close"]
    current_atr   = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

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
