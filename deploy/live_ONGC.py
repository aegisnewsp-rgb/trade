#!/usr/bin/env python3
"""
Live Trading Script - ONGC.NS
Strategy: MEAN_REVERSION v9 (RSI-only + VWAP bounce) - NO trend/MACD/BB filters
Win Rate: 25.0% -> Target 55%+ (v9 MEAN_REVERSION - pivoted from v8 multi-filter too restrictive)
Position: ₹7000 | Stop Loss: 0.6% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: 2026-03-23 - v9 MEAN_REVERSION: removed MACD/BB/trend filters that blocked signals
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
YFINANCE_AVAILABLE = True
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_ONGC.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ONGC")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "ONGC.NS"
STRATEGY       = "MEAN_REVERSION_RSI_V9"  # v9: simpler, no MACD/BB/trend filters
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.006
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "vwap_period": 14,
    "atr_multiplier": 1.5,
    "rsi_period": 14,
    "rsi_overbought": 62,
    "rsi_oversold": 38,
    "rsi_confirm_overbought": 62,
    "rsi_confirm_oversold": 38,
    "volume_multiplier": 1.3,
    "atr_period": 14,
}

BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END   = dtime(14, 30)
NO_ENTRY_AFTER   = dtime(14, 30)

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.now(datetime.UTC) + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

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

def can_new_entry() -> bool:
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early — waiting for 9:30 AM IST entry window")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM IST — no new entries today")
        return False
    return True

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv: list, period: int = 14) -> list:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high, low = bar["high"], bar["low"]
        close = bar["close"]
        tr = high - low if prev_close is None else max(
            high - low, abs(high - prev_close), abs(low - prev_close))
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = close
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

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def vwap_signal(ohlcv: list, params: dict) -> tuple:
    """MEAN_REVERSION v9: RSI-only + VWAP bounce + Volume confirmation.
    No trend filter, no MACD, no Bollinger Bands (too restrictive for ONGC).
    """
    period     = params["vwap_period"]
    atr_mult   = params["atr_multiplier"]
    rsi_period = params["rsi_period"]
    rsi_oversold   = params.get("rsi_oversold", 38)
    rsi_overbought = params.get("rsi_overbought", 62)
    vol_mult   = params.get("volume_multiplier", 1.3)

    vwap_vals  = calculate_vwap(ohlcv, period)
    atr_vals   = calculate_atr(ohlcv, period)
    rsi_vals   = calculate_rsi(ohlcv, rsi_period)
    avg_vol    = calculate_avg_volume(ohlcv, period)

    start_idx = max(period, rsi_period, 5)
    signals   = ["HOLD"] * len(ohlcv)

    for i in range(start_idx, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue

        price = ohlcv[i]["close"]
        v      = vwap_vals[i]
        a      = atr_vals[i]
        rsi    = rsi_vals[i]
        vol    = ohlcv[i]["volume"]

        # Mean reversion BUY: oversold + price near VWAP from below + volume surge
        oversold      = rsi < rsi_oversold
        near_vwap     = abs(price - v) < a * 1.0
        vol_confirmed = vol > avg_vol * vol_mult
        price_above_vwap = price > v  # recovering from below VWAP

        # Mean reversion SELL: overbought + price near VWAP from above + volume surge
        overbought    = rsi > rsi_overbought
        at_resistance = abs(price - v) < a * 1.0
        price_below_vwap = price < v  # falling from above VWAP

        if oversold and near_vwap and vol_confirmed and price_above_vwap:
            signals[i] = "BUY"
        elif overbought and at_resistance and vol_confirmed and price_below_vwap:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals else 50.0
    return current_signal, current_price, current_atr, current_rsi

def get_exit_levels(entry_price: float, atr: float, params: dict) -> list:
    risk = entry_price * STOP_LOSS_PCT
    t1 = round(entry_price + (TARGET_1_MULT * risk), 2)
    t2 = round(entry_price + (TARGET_2_MULT * risk), 2)
    t3 = round(entry_price + (TARGET_3_MULT * risk), 2)
    return [
        {"level": 1, "price": t1, "risk_mult": TARGET_1_MULT, "exit_pct": 0.33, "desc": "Secure 1.5×"},
        {"level": 2, "price": t2, "risk_mult": TARGET_2_MULT, "exit_pct": 0.33, "desc": "Main 3×"},
        {"level": 3, "price": t3, "risk_mult": TARGET_3_MULT, "exit_pct": 0.34, "desc": "Stretch 5×"},
    ]

def main():
    print(f"\n{'='*60}")
    print(f"Running: ONGC.NS | Strategy: MEAN_REVERSION v9 (RSI + VWAP bounce)")
    print(f"{'='*60}")

    ohlcv = fetch_recent_data(days=60)

    if not ohlcv:
        print("No data fetched")
        return

    signal, price, atr, rsi = vwap_signal(ohlcv, PARAMS)

    print(f"Signal: {signal} | Price: Rs{price:.2f} | ATR: Rs{atr:.2f} | RSI: {rsi:.1f}")

    if signal == "BUY":
        sl = round(price * (1 - STOP_LOSS_PCT), 2)
        exits = get_exit_levels(price, atr, PARAMS)
        qty = max(1, int(POSITION / price))
        risk = price - sl
        print(f"Stop:   Rs{sl:.2f} | Risk: Rs{risk:.2f}")
        print(f"T1: Rs{exits[0]['price']:.2f} | T2: Rs{exits[1]['price']:.2f} | T3: Rs{exits[2]['price']:.2f}")
        print(f"Qty: {qty} | Position: Rs{qty * price:.2f}")
        try:
            from groww_api import paper_trade
            paper_trade("BUY", SYMBOL, price, qty)
        except:
            pass
    elif signal == "SELL":
        sl = round(price * (1 + STOP_LOSS_PCT), 2)
        exits = get_exit_levels(price, atr, PARAMS)
        qty = max(1, int(POSITION / price))
        risk = sl - price
        print(f"Stop:   Rs{sl:.2f} | Risk: Rs{risk:.2f}")
        print(f"T1: Rs{exits[0]['price']:.2f} | T2: Rs{exits[1]['price']:.2f} | T3: Rs{exits[2]['price']:.2f}")
        print(f"Qty: {qty} | Position: Rs{qty * price:.2f}")
        try:
            from groww_api import paper_trade
            paper_trade("SELL", SYMBOL, price, qty)
        except:
            pass
    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()
