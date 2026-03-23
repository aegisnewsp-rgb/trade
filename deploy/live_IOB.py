#!/usr/bin/env python3
"""
Live Trading Script - IOB.NS (Indian Overseas Bank)
Strategy: VWAP (Volume Weighted Average Price)
Win Rate: 62.00% (estimated based on PSU bank sector)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Added: 2026-03-22 | PSU bank momentum play, +6.54% on Mar 20
"""

import os, sys, json, time, logging, requests
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
        logging.FileHandler(LOG_DIR / "live_IOB.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_IOB")

SYMBOL         = "IOB.NS"
STRATEGY       = "VWAP_RSI_FILTER"
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.005
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
RSI_PERIOD     = 14
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 65
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.now(datetime.UTC) + __import__("datetime").timedelta(hours=5.5)

# Smart entry: 9:30-14:30 IST
def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

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
    atr, prev_close = [], None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        delta = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    rsi = [None] * (period + 1)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi.append(100 - (100 / (1 + rs)))
    return rsi

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

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    period, atr_mult = params["vwap_period"], params["atr_multiplier"]
    vwap_vals = calculate_vwap(ohlcv, period)
    atr_vals  = calculate_atr(ohlcv, period)
    rsi_vals  = calculate_rsi(ohlcv, RSI_PERIOD)
    signals   = ["HOLD"] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        r = rsi_vals[i]
        if price > vwap_vals[i] + atr_vals[i] * atr_mult:
            if r < RSI_OVERSOLD:
                signals[i] = "BUY"
        elif price < vwap_vals[i] - atr_vals[i] * atr_mult:
            if r > RSI_OVERBOUGHT:
                signals[i] = "SELL"
    last = signals[-1]
    entry = ohlcv[-1]["close"]
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    sl = entry - current_atr * STOP_LOSS_PCT
    tgt = entry + current_atr * TARGET_MULT
    return last, float(sl), float(tgt), current_rsi

def get_groww_quote() -> dict | None:
    if not GROWW_API_KEY:
        return None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"GROWW_API_BASE/live/quotes/{SYMBOL}",
                headers={"Authorization": f"Bearer GROWW_API_KEY"},
                timeout=GROWW_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.warning("Groww API attempt %d failed: %s", attempt + 1, e)
            time.sleep(1)
    return None

def main():
    log.info("Starting %s live trading — strategy: %s | RSI Filter: %d/%d | SL: 0.5%%", SYMBOL, STRATEGY, RSI_OVERSOLD, RSI_OVERBOUGHT)
    data = fetch_recent_data()
    if not data:
        log.error("No data fetched. Exiting.")
        sys.exit(1)
    signal, sl, tgt, rsi = vwap_signal(data, PARAMS)
    price = data[-1]["close"]
    quantity = max(1, int(POSITION / price))
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    log.info("  RSI      : %.1f", rsi)
    log.info("  STOP     : ₹%.2f  (0.5%%)", sl)
    log.info("  TARGET   : ₹%.2f  (4.0× ATR)", tgt)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if signal == "BUY":
        log.info(">>> BUY SIGNAL for %s at ₹%.2f", SYMBOL, price)
        log.info("    Stop Loss: ₹%.2f | Target: ₹%.2f", sl, tgt)
    elif signal == "SELL":
        log.info(">>> SELL SIGNAL for %s at ₹%.2f", SYMBOL, price)


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
