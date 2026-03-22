#!/usr/bin/env python3
"""
Live Trading Script - SAGILITY.NS
Strategy: RSI Reversal + Volume Spike (mean reversion near 52-week low)
Position: ₹5000 | Stop Loss: 1.2% ATR | Target: 3.5x ATR | Daily Loss Cap: 0.4%
Research: deploy/research/2026-03-22_sagility_research.md
"""

import os, sys, json, time, logging, requests
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_SAGILITY.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SAGILITY")

SYMBOL         = "SAGILITY.NS"
STRATEGY       = "RSI_REVERSAL_VOLUME"
POSITION       = 5000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.012
TARGET_MULT    = 3.5
DAILY_LOSS_CAP = 0.004
PARAMS         = {
    "rsi_period": 14, "rsi_oversold": 35, "rsi_overbought": 65,
    "atr_period": 14, "volume_ma_period": 20, "volume_spike_mult": 1.5,
}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)

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
                {
                    "date": str(idx.date()),
                    "open": float(r["Open"]), "high": float(r["High"]),
                    "low": float(r["Low"]), "close": float(r["Close"]),
                    "volume": int(r["Volume"])
                }
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
        tr = (
            bar["high"] - bar["low"]
            if prev_close is None
            else max(
                bar["high"] - bar["low"],
                abs(bar["high"] - prev_close),
                abs(bar["low"] - prev_close),
            )
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
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        delta = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
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

def calculate_volume_ma(ohlcv: list, period: int = 20) -> list:
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            vol_ma.append(sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period)
    return vol_ma

def rsi_reversal_signal(ohlcv: list, params: dict) -> tuple:
    rsi_period   = params["rsi_period"]
    rsi_os       = params["rsi_oversold"]
    rsi_ob       = params["rsi_overbought"]
    atr_period   = params["atr_period"]
    vol_ma_period = params["volume_ma_period"]
    vol_spike    = params["volume_spike_mult"]

    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    atr_vals  = calculate_atr(ohlcv, atr_period)
    vol_ma    = calculate_volume_ma(ohlcv, vol_ma_period)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(rsi_period, vol_ma_period), len(ohlcv)):
        if rsi_vals[i] is None or atr_vals[i] is None or vol_ma[i] is None:
            continue
        price     = ohlcv[i]["close"]
        prev_price = ohlcv[i - 1]["close"]
        rsi       = rsi_vals[i]
        atr       = atr_vals[i]
        vol_today = ohlcv[i]["volume"]
        vol_avg   = vol_ma[i]

        # BUY: RSI oversold + price bounce + volume spike
        if rsi < rsi_os and price > prev_price and vol_today > vol_avg * vol_spike:
            signals[i] = "BUY"
        # SELL: RSI overbought + price drop + volume spike
        elif rsi > rsi_ob and price < prev_price and vol_today > vol_avg * vol_spike:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    current_vol = ohlcv[-1]["volume"] if ohlcv else 0
    vol_avg_val = vol_ma[-1] if vol_ma and vol_ma[-1] is not None else 1
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr, current_rsi, current_vol, vol_avg_val

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



def main():
    """Main trading loop"""
    import yfinance
    YFINANCE_AVAILABLE = True
    try:
        ticker = yfinance.Ticker("SAGILITY.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            print("SAGILITY: No data")
            return
        closes = d['Close'].tolist()
        print(f"SAGILITY: {len(closes)} candles, last price {closes[-1]:.2f}")
    except Exception as e:
        print(f"SAGILITY: Error - {e}")

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
