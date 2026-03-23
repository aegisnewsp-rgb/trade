#!/usr/bin/env python3
"""
Live Trading Script - RUPA.BO
Strategy: MEAN_REVERSION (RSI-only + VWAP bounce) - v9 LOWWREnhanced v8)
Win Rate: 0% -> Target 55%+ (MEAN_REVERSION v9 - simpler, faster signals))
Position: ₹7000 | Stop Loss: 0.6% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: 2026-03-23 - v9 MEAN_REVERSION: 0% WR v8 failed, pivoting to RSI-only bounce
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True
import requests

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_RUPA_BO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_RUPA_BO")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "RUPA.BO"
STRATEGY = "MEAN_REVERSION_RSI_V9"  # RUPA.BO
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
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_multiplier": 1.3,
    "trend_ma_period": 50,
    "atr_period": 14,
    "bb_period": 20,
    "bb_std": 2.0,
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
            log.warning("Attempt %d/%d failed: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv: list, period: int = 14) -> list:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high, low = bar[1], bar[2]
        close     = bar[3]
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
            tp_sum  = sum((ohlcv[j][1] + ohlcv[j][2] + ohlcv[j][3]) / 3
                          for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j][4] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    rsi_values = [50.0] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi_values
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i][3] - ohlcv[i - 1][3]
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

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    closes = [b[3] for b in ohlcv]
    ema_fast, ema_slow, macd_line = [], [], []
    k_fast = 2 / (fast + 1); k_slow = 2 / (slow + 1)
    ema_fast.append(closes[0]); ema_slow.append(closes[0])
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * k_fast + ema_fast[-1] * (1 - k_fast))
        ema_slow.append(closes[i] * k_slow + ema_slow[-1] * (1 - k_slow))
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    signal_line = []
    k_sig = 2 / (signal + 1)
    signal_line.append(macd_line[0])
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    histogram = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]
    return macd_line, signal_line, histogram

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j][3] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j][4] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_bollinger_bands(ohlcv: list, period: int = 20, std_dev: float = 2.0) -> tuple[list, list, list]:
    middle = calculate_ma(ohlcv, period)
    upper, lower = [], []
    for i in range(len(ohlcv)):
        if middle[i] is None:
            upper.append(None); lower.append(None)
        else:
            window = ohlcv[max(0, i - period + 1):i + 1]
            mean = middle[i]
            variance = sum((b[3] - mean) ** 2 for b in window) / len(window)
            std = variance ** 0.5
            upper.append(mean + std_dev * std)
            lower.append(mean - std_dev * std)
    return upper, middle, lower

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    """MEAN_REVERSION v9: RSI-only bounce + VWAP proximity + Volume confirmation.
    No trend filter (fails for consistently downtrending stocks).
    """
    period     = params["vwap_period"]
    atr_mult   = params["atr_multiplier"]
    rsi_period = params["rsi_period"]
    rsi_oversold   = params.get("rsi_oversold", 38)
    rsi_overbought = params.get("rsi_overbought", 62)
    vol_mult   = params.get("volume_multiplier", 1.5)

    vwap_vals  = calculate_vwap(ohlcv, period)
    atr_vals   = calculate_atr(ohlcv, period)
    rsi_vals   = calculate_rsi(ohlcv, rsi_period)
    avg_vol    = calculate_avg_volume(ohlcv, period)

    start_idx = max(period, rsi_period, 5)
    signals   = ["HOLD"] * len(ohlcv)

    for i in range(start_idx, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue

        price = ohlcv[i][3]
        v      = vwap_vals[i]
        a      = atr_vals[i]
        rsi    = rsi_vals[i]
        vol    = ohlcv[i][4]

        # Mean reversion: oversold + price near/at VWAP support
        # Volume confirms institutional interest
        oversold      = rsi < rsi_oversold
        near_vwap     = abs(price - v) < a * 1.0   # within 1 ATR of VWAP
        vol_confirmed = vol > avg_vol * vol_mult

        # Overbought: overbought + price near/at VWAP resistance
        overbought   = rsi > rsi_overbought
        at_resistance = abs(price - v) < a * 1.0  # same proximity logic

        if oversold and near_vwap and vol_confirmed:
            signals[i] = "BUY"
        elif overbought and at_resistance and vol_confirmed:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1][3]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals else 50.0
    return current_signal, current_price, current_atr, current_rsi


def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return

    fname = Path(__file__).stem
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix

    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym})")
    print(f"{'='*60}")

    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
    except Exception as e:
        print(f"Data fetch error: {e}")
        return

    ohlcv_list = []
    for idx, row in data.iterrows():
        ohlcv_list.append([
            float(row['Open']),
            float(row['High']),
            float(row['Low']),
            float(row['Close']),
            float(row['Volume'])
        ])

    if not ohlcv_list:
        print("No OHLCV data")
        return

    signal = None
    price = ohlcv_list[-1][3]
    atr = 0.0

    try:
        sig_result = vwap_signal(ohlcv_list, PARAMS)
        if isinstance(sig_result, tuple) and len(sig_result) >= 2:
            signal, price = sig_result[0], float(sig_result[1])
            atr = sig_result[2] if len(sig_result) > 2 else 0.0
        elif isinstance(sig_result, str):
            signal = sig_result
    except Exception as e:
        print(f"Signal error: {e}")
        signal = "HOLD"

    print(f"\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")

    if signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(7000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f}")
        print(f"Target: Rs{tgt:.2f}")
    elif signal == "SELL":
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
        qty = max(1, int(7000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f}")
        print(f"Target: Rs{tgt:.2f}")
    else:
        print("No trade — HOLD signal")

if __name__ == "__main__":
    main()
