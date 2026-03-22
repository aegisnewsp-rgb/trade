#!/usr/bin/env python3
"""
Live Trading Script - IDEA.NS
Strategy: VOLUME_DIVERGENCE
Win Rate: 59.52%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_IDEA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_IDEA")

SYMBOL         = "IDEA.NS"
STRATEGY       = "VOLUME_DIVERGENCE_RSI_FILTER"
POSITION       = 7000
STOP_LOSS_PCT  = 0.005
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
RSI_PERIOD     = 14
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 65
PARAMS         = {"ma_period": 20, "volume_ma_period": 20, "div_threshold": 0.05}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"
IST_TZ_OFFSET = 5.5

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

# Smart entry: 9:30-14:30 IST
def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty: raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(row["Open"]),
                 "high": float(row["High"]), "low": float(row["Low"]),
                 "close": float(row["Close"]), "volume": int(row["Volume"])}
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

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    rsi = []
    for i in range(len(gains)):
        if i < period - 1:
            rsi.append(None)
        elif i == period - 1:
            avg_gain = sum(gains[i-period+1:i+1]) / period
            avg_loss = sum(losses[i-period+1:i+1]) / period
            rsi.append(100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss)))
        else:
            avg_gain = (rsi[-1] * (period - 1) + gains[i]) / period
            avg_loss = (losses[-1] * (period - 1) + losses[i]) / period
            rsi.append(100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss)))
    return [None] + rsi

def calculate_ma(prices: list, period: int) -> list:
    ma = []
    for i in range(len(prices)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(prices[i - period + 1:i + 1]) / period)
    return ma

def volume_divergence_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    ma_period     = params["ma_period"]
    vol_period    = params["volume_ma_period"]
    div_threshold = params["div_threshold"]

    closes  = [b["close"]  for b in ohlcv]
    volumes = [b["volume"] for b in ohlcv]

    ma_vals  = calculate_ma(closes,  ma_period)
    vol_ma   = calculate_ma(volumes, vol_period)
    rsi_vals = calculate_rsi(ohlcv, RSI_PERIOD)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(ma_period, len(ohlcv)):
        if ma_vals[i] is None or vol_ma[i] is None or vol_ma[i] == 0 or rsi_vals[i] is None:
            continue
        price      = closes[i]
        prev_price = closes[i - 1]
        vol_ratio  = volumes[i] / vol_ma[i]
        r          = rsi_vals[i]

        # Bullish divergence: price drops but volume surges + RSI oversold
        if price < ma_vals[i] and vol_ratio > (1 + div_threshold):
            if r < RSI_OVERSOLD:
                signals[i] = "BUY"
        # Bearish divergence: price rises but volume drops + RSI overbought
        elif price > ma_vals[i] and vol_ratio < (1 - div_threshold):
            if r > RSI_OVERBOUGHT:
                signals[i] = "SELL"

    atr_vals = calculate_atr(ohlcv)
    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
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


if __name__ == "__main__": main()
