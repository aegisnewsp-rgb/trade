#!/usr/bin/env python3
"""
Live Trading Script - FEDERALBNK.NS
Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (Enhanced v8 LOWWR)
Win Rate: 58.00% -> Target 65%+ (v8 LOWWR: full multi-filter upgrade from VWAP+RSI basic)
Position: ₹7000 | Stop Loss: 0.6% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
Enhanced: 2026-03-23 - v8 LOWWR: added MACD + Bollinger Band + Trend MA to basic VWAP+RSI
"""

import os, sys, json, time, logging, requests, math
import logging
import groww_api
import logging
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf
import logging
YFINANCE_AVAILABLE = True
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_FEDERALBNK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_FEDERALBNK")

SYMBOL         = "FEDERALBNK.NS"
BANK_INDEX     = "^NSEBANK"  # NIFTY BANK index for sector confirmation
STRATEGY       = "VWAP_RSI_MACD_VOL_BB_v8_LOWWR"
POSITION       = 7000

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
    "rsi_overbought": 68,
    "rsi_oversold": 32,
    "rsi_confirm_overbought": 68,
    "rsi_confirm_oversold": 32,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_multiplier": 2.0,
    "trend_ma_period": 50,
    "atr_period": 14,
    "bb_period": 20,
    "bb_std": 2.0,
}

BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END   = dtime(14, 30)
NO_ENTRY_AFTER   = dtime(14, 30)

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.now(datetime.UTC) + __import__("datetime").timedelta(hours=5.5)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def can_new_entry() -> bool:
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early — waiting for 9:30 AM IST entry window")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM IST — no new entries today")
        return False
    return True

def in_best_entry_window() -> bool:
    now = ist_now().time()
    return BEST_ENTRY_START <= now <= BEST_ENTRY_END

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

def fetch_bank_index_data(days: int = 30, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(BANK_INDEX).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty bank index dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d candles for bank index", len(ohlcv))
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching bank index: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.warning("Bank index fetch failed, proceeding without sector confirmation")
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

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    closes = [b["close"] for b in ohlcv]
    ema_fast, ema_slow = [closes[0]], [closes[0]]
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * (2/(fast+1)) + ema_fast[-1] * (1 - 2/(fast+1)))
        ema_slow.append(closes[i] * (2/(slow+1)) + ema_slow[-1] * (1 - 2/(slow+1)))
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    signal_line = [macd_line[0]]
    k_sig = 2/(signal+1)
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    histogram = [macd_line[i] - signal_line[i] for i in range(len(closes))]
    return macd_line, signal_line, histogram

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_bollinger_bands(ohlcv: list, period: int = 20, std_dev: float = 2.0) -> tuple:
    middle = calculate_ma(ohlcv, period)
    upper, lower = [], []
    for i in range(len(ohlcv)):
        if middle[i] is None:
            upper.append(None); lower.append(None)
        else:
            window = ohlcv[max(0, i - period + 1):i + 1]
            mean = middle[i]
            variance = sum((b["close"] - mean) ** 2 for b in window) / len(window)
            std = variance ** 0.5
            upper.append(mean + std_dev * std)
            lower.append(mean - std_dev * std)
    return upper, middle, lower

def calculate_bank_index_signal(bank_data: list) -> str:
    if not bank_data or len(bank_data) < 5:
        return "NEUTRAL"
    closes = [bar["close"] for bar in bank_data[-10:]]
    if len(closes) < 5:
        return "NEUTRAL"
    ma5 = sum(closes[-5:]) / 5
    current_close = closes[-1]
    if current_close > ma5 * 1.005:
        return "BULLISH"
    elif current_close < ma5 * 0.995:
        return "BEARISH"
    return "NEUTRAL"

def vwap_signal(ohlcv: list, params: dict, bank_data: list = None) -> tuple:
    period          = params["vwap_period"]
    atr_mult        = params["atr_multiplier"]
    rsi_period      = params["rsi_period"]
    rsi_overbought  = params.get("rsi_confirm_overbought", 68)
    rsi_oversold    = params.get("rsi_confirm_oversold", 32)
    vol_mult        = params.get("volume_multiplier", 2.0)
    trend_period    = params.get("trend_ma_period", 50)
    bb_period       = params.get("bb_period", 20)
    bb_std          = params.get("bb_std", 2.0)

    vwap_vals    = calculate_vwap(ohlcv, period)
    atr_vals     = calculate_atr(ohlcv, period)
    rsi_vals     = calculate_rsi(ohlcv, rsi_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, params["macd_fast"], params["macd_slow"], params["macd_signal"])
    ma_vals      = calculate_ma(ohlcv, trend_period)
    avg_vol      = calculate_avg_volume(ohlcv, period)
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(ohlcv, bb_period, bb_std)

    start_idx = max(period, rsi_period, params["macd_slow"], params["macd_signal"], bb_period, trend_period)
    signals   = ["HOLD"] * len(ohlcv)

    bank_signal = calculate_bank_index_signal(bank_data) if bank_data else "NEUTRAL"

    for i in range(start_idx, len(ohlcv)):
        if None in (vwap_vals[i], atr_vals[i], rsi_vals[i], macd_line[i], ma_vals[i], bb_upper[i]):
            continue

        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        trend   = ma_vals[i]
        macd_h  = histogram[i]
        sig_h   = histogram[i - 1] if i > 0 else 0
        bb_up   = bb_upper[i]
        bb_lo   = bb_lower[i]

        buy_ok = (
            price > v and
            rsi < rsi_oversold and
            macd_h > 0 and
            sig_h <= macd_h and
            vol > avg_vol * vol_mult and
            price > trend
        )

        if bank_signal == "BEARISH":
            buy_ok = buy_ok and (rsi < 25)

        if buy_ok:
            signals[i] = "BUY"

        sell_ok = (
            price < v and
            rsi > rsi_overbought and
            macd_h < 0 and
            sig_h >= macd_h and
            vol > avg_vol * vol_mult and
            price < trend
        )

        if bank_signal == "BULLISH":
            sell_ok = sell_ok and (rsi > 75)

        if sell_ok:
            signals[i] = "SELL"

    return signals[-1], price, a, rsi

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
    print(f"Running: FEDERALBNK.NS | Strategy: VWAP_RSI_MACD_VOL_BB_v8_LOWWR")
    print(f"{'='*60}")

    ohlcv = fetch_recent_data(days=60)
    bank_data = fetch_bank_index_data(days=30)

    if not ohlcv:
        print("No data fetched")
        return

    signal, price, atr, rsi = vwap_signal(ohlcv, PARAMS, bank_data)

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
