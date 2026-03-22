#!/usr/bin/env python3
"""
Live Trading Script - SUNPHARMA.NS (Sun Pharmaceutical Industries)
Strategy: VWAP Momentum
Source: NSE momentum scan (2026-03-22) — +1.50% with 1.41x volume ratio
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
