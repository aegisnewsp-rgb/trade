#!/usr/bin/env python3
"""
Live Trading Script - IGL.NS (Indraprastha Gas Limited)
Strategy: ADX_TREND (Average Directional Index)
Win Rate: 60.2%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests, math
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
        logging.FileHandler(LOG_DIR / "live_IGL.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_IGL")

SYMBOL         = "IGL.NS"
STRATEGY       = "ADX_TREND"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"adx_period": 14, "adx_threshold": 25}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)

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

def adx_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    ADX Trend strategy: BUY when +DI > -DI with strong trend (ADX > threshold),
    SELL when -DI > +DI. Uses simplified True Range / Directional Movement.
    """
    period     = params["adx_period"]
    threshold  = params["adx_threshold"]

    high  = [bar["high"] for bar in ohlcv]
    low   = [bar["low"]  for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]

    tr_list = [high[i] - low[i]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(ohlcv))
    ]

    plus_dm = [0.0] * len(ohlcv)
    minus_dm = [0.0] * len(ohlcv)
    for i in range(1, len(ohlcv)):
        up_move  = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i]  = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    # Smooth with EMA
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(ohlcv) < period * 2:
        return "HOLD", close[-1], 0.0

    tr_smooth  = ema(tr_list, period)
    plus_dm_sm = ema(plus_dm, period)
    minus_dm_sm = ema(minus_dm, period)

    plus_di  = [100 * plus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]
    minus_di = [100 * minus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]

    dx = [100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          if (plus_di[i] + minus_di[i]) != 0 else 0 for i in range(len(ohlcv))]
    adx_vals = ema(dx, period)

    if len(adx_vals) < 2:
        return "HOLD", close[-1], 0.0

    # Signal: trending ADX with directional crossover
    if adx_vals[-1] > threshold:
        if plus_di[-1] > minus_di[-1] and plus_di[-2] <= minus_di[-2]:
            signal = "BUY"
        elif minus_di[-1] > plus_di[-1] and minus_di[-2] <= plus_di[-2]:
            signal = "SELL"
        else:
            signal = "HOLD"
    else:
        signal = "HOLD"

    atr_vals = calculate_atr(ohlcv, period)
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, close[-1], current_atr

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
