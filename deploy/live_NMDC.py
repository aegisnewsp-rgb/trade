#!/usr/bin/env python3
"""
Live Trading Script - NMDC.NS
Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8 LOWWR)
Win Rate: 13.3% → Target 50%+ (v8 LOWWR: full multi-filter upgrade for mining/commodity stock)
Position: ₹7000 | Stop Loss: 0.6% | Target: 4.0x ATR | Daily Loss Cap: 0.25%
Enhanced: 2026-03-23 - v8 LOWWR: multi-confirmation for low win-rate commodity stock
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
        logging.FileHandler(LOG_DIR / "live_NMDC.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_NMDC")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "NMDC.NS"
STRATEGY       = "VWAP_RSI_MACD_VOL_BB_v8_LOWWR"
POSITION       = 7000
STOP_LOSS_PCT  = 0.006
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.0025
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

# 3-TIER EXIT SYSTEM
SL_ATR_MULT       = 1.0
MAX_SL_PCT        = 0.015
TRAIL_TRIGGER_PCT  = 0.008
TARGET_1_MULT      = 1.5
TARGET_2_MULT      = 3.0
TARGET_3_MULT      = 5.0

# Entry window
BEST_ENTRY_START   = dtime(9, 30)
BEST_ENTRY_END     = dtime(14, 30)
NO_ENTRY_AFTER     = dtime(14, 30)

# NIFTY regime filter (for commodity stocks sensitive to market regime)
USE_REGIME_FILTER  = True
NIFTY_SYMBOL       = "^NSEI"

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

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"
IST_TZ_OFFSET    = 5.5

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def fetch_recent_data(days: int = 90, retries: int = 3) -> list | None:
    """Fetch 90 days for better backtest quality (commodity stocks need longer horizon)."""
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

def fetch_nifty_data(days: int = 60) -> list | None:
    """Fetch NIFTY data for regime detection."""
    for attempt in range(3):
        try:
            ticker = yf.Ticker(NIFTY_SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty NIFTY dataframe")
            return [
                {
                    "close": float(row["Close"]),
                }
                for idx, row in df.iterrows()
            ]
        except Exception as e:
            log.warning("NIFTY fetch attempt %d failed: %s", attempt + 1, e)
            time.sleep(2 ** attempt)
    return None

def get_nifty_regime() -> str:
    """Detect NIFTY market regime: UPTREND, RANGE, or DOWNTREND."""
    nifty_data = fetch_nifty_data(60)
    if not nifty_data or len(nifty_data) < 50:
        log.warning("Insufficient NIFTY data for regime detection — defaulting to UPTREND")
        return "UPTREND"
    closes = [d["close"] for d in nifty_data]
    sma20 = sum(closes[-20:]) / 20
    current = closes[-1]
    ratio = current / sma20
    if ratio > 1.02:
        regime = "UPTREND"
    elif ratio < 0.98:
        regime = "DOWNTREND"
    else:
        regime = "RANGE"
    log.info("NIFTY regime: %s (ratio=%.4f)", regime, ratio)
    return regime

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

def calculate_rsi(closes: list, period: int = 14) -> list:
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i-1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi = [None] * (period + 1)
    if avg_loss == 0:
        rsi.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100 - (100 / (1 + rs)))
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            rsi.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - (100 / (1 + rs)))
    return rsi

def calculate_macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    if len(closes) < slow + signal:
        return [None] * len(closes), [None] * len(closes)
    ema_fast = [None] * (fast - 1)
    ema_slow = [None] * (slow - 1)
    # Start EMA
    def ema_series(data, n):
        k = 2 / (n + 1)
        result = [None] * (n - 1)
        result.append(sum(data[:n]) / n)
        for i in range(n, len(data)):
            result.append((data[i] - result[-1]) * k + result[-1])
        return result
    ema_f = ema_series(closes, fast)
    ema_s = ema_series(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ema_f[i] is not None and ema_s[i] is not None:
            macd_line[i] = ema_f[i] - ema_s[i]
    signal_line = ema_series(macd_line, signal)
    return macd_line, signal_line

def calculate_ma(closes: list, period: int) -> list:
    ma = []
    for i in range(len(closes)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(closes[i - period + 1:i + 1]) / period)
    return ma

def calculate_bb(closes: list, period: int = 20, std_mult: float = 2.0) -> tuple:
    upper = []
    mid   = []
    lower = []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            mid.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            m = sum(window) / period
            s = (sum((x - m) ** 2 for x in window) / period) ** 0.5
            mid.append(m)
            upper.append(m + std_mult * s)
            lower.append(m - std_mult * s)
    return upper, mid, lower

def vwap_signal_v8(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    v8 LOWWR multi-filter signal for NMDC (commodity/mining stock).
    BUY: RSI < 32 AND price < lower BB AND volume > 2x MA AND price < VWAP + 0.5*ATR
    SELL: RSI > 68 AND price > upper BB AND volume > 2x MA AND price > VWAP - 0.5*ATR
    """
    period      = params.get("vwap_period", 14)
    atr_mult    = params.get("atr_multiplier", 1.5)
    rsi_period  = params.get("rsi_period", 14)
    vol_mult    = params.get("volume_multiplier", 2.0)
    bb_period   = params.get("bb_period", 20)
    bb_std      = params.get("bb_std", 2.0)
    ma_period   = params.get("trend_ma_period", 50)

    vwap_vals   = calculate_vwap(ohlcv, period)
    atr_vals    = calculate_atr(ohlcv, 14)
    closes      = [b["close"] for b in ohlcv]
    rsi_vals    = calculate_rsi(closes, rsi_period)
    macd, signal = calculate_macd(closes)
    bb_upper, bb_mid, bb_lower = calculate_bb(closes, bb_period, bb_std)
    ma_vals     = calculate_ma(closes, ma_period)

    # Volume MA
    volumes = [b["volume"] for b in ohlcv]
    vol_ma = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else volumes[-1]

    signals = ["HOLD"] * len(ohlcv)

    for i in range(max(period, ma_period, bb_period), len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue
        if rsi_vals[i] is None or bb_lower[i] is None or ma_vals[i] is None:
            continue

        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        bb_l    = bb_lower[i]
        bb_u    = bb_upper[i]
        ma      = ma_vals[i]
        vol     = volumes[i]
        macd_val = macd[i] if macd[i] is not None else 0
        sig_val  = signal[i] if signal[i] is not None else 0

        # BUY conditions (all must be true)
        buy = (
            rsi < params.get("rsi_oversold", 32) and       # RSI oversold
            price <= bb_l and                               # At/near lower BB
            vol > vol_ma * vol_mult and                     # Volume confirmation
            price > ma and                                  # Above 50-MA (uptrend)
            price < v + a * 0.5 and                         # Below VWAP (support)
            macd_val > sig_val                              # MACD bullish
        )

        # SELL conditions (all must be true)
        sell = (
            rsi > params.get("rsi_overbought", 68) and      # RSI overbought
            price >= bb_u and                                # At/near upper BB
            vol > vol_ma * vol_mult and                     # Volume confirmation
            price < ma and                                  # Below 50-MA (downtrend)
            price > v - a * 0.5 and                         # Above VWAP (resistance)
            macd_val < sig_val                              # MACD bearish
        )

        if buy:
            signals[i] = "BUY"
        elif sell:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def place_groww_order(symbol, signal, quantity, price, atr):
    """Place order via Groww API or paper trade."""
    import groww_api

    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)

    exchange = "NSE"

    if signal == "BUY":
        stop_loss = price - (atr * 1.0)
        target    = price + (atr * 4.0)
        result    = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="BUY",
            quantity=quantity, target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = price + (atr * 1.0)
        target    = price - (atr * 4.0)
        result    = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="SELL",
            quantity=quantity, target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None

    if result:
        log.info("Order placed: %s %s %s @ Rs%.2f", signal, quantity, symbol, price)
    return result

def main():
    """Main entry point for NMDC v8 LOWWR."""
    try:
        import yfinance
        YFINANCE_AVAILABLE = True
    except ImportError:
        log.error("yfinance not installed: pip install yfinance")
        return

    fname      = Path(__file__).stem
    sym        = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym  = ticker_sym + exchange_suffix

    log.info("=== NMDC v8 LOWWR ===")
    log.info("Symbol: %s (%s)", ticker_sym, yahoo_sym)

    # Regime check
    if USE_REGIME_FILTER:
        regime = get_nifty_regime()
        if regime == "DOWNTREND":
            log.info("NIFTY DOWNTREND — blocking BUY signals, reducing to 0 size")
        elif regime == "RANGE":
            log.info("NIFTY RANGE — 50%% position size only")

    # Fetch data
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv:
        log.error("No data available")
        return

    log.info("Loaded %d candles", len(ohlcv))

    # Generate signal
    signal, price, atr = vwap_signal_v8(ohlcv, PARAMS)
    log.info("Signal: %s | Price: Rs%.2f | ATR: Rs%.2f", signal, price, atr)

    # Regime position sizing
    position = POSITION
    if USE_REGIME_FILTER:
        regime = get_nifty_regime()
        if regime == "DOWNTREND":
            log.info("DOWNTREND — blocking BUY")
            signal = "HOLD"
        elif regime == "RANGE":
            position = POSITION // 2

    if not can_new_entry() and signal == "BUY":
        log.info("Outside entry window — holding")
        signal = "HOLD"

    qty = max(1, int(position / price)) if price > 0 else 0

    if signal == "BUY":
        sl   = round(price * (1 - STOP_LOSS_PCT), 2)
        tgt  = round(price * (1 + STOP_LOSS_PCT * TARGET_MULT), 2)
        log.info("BUY  Qty:%d  Price:Rs%.2f  SL:Rs%.2f  TGT:Rs%.2f", qty, price, sl, tgt)
        place_groww_order(ticker_sym, "BUY", qty, price, atr)
    elif signal == "SELL":
        sl   = round(price * (1 + STOP_LOSS_PCT), 2)
        tgt  = round(price * (1 - STOP_LOSS_PCT * TARGET_MULT), 2)
        log.info("SELL Qty:%d  Price:Rs%.2f  SL:Rs%.2f  TGT:Rs%.2f", qty, price, sl, tgt)
        place_groww_order(ticker_sym, "SELL", qty, price, atr)
    else:
        log.info("HOLD — no signal")

if __name__ == "__main__":
    main()
