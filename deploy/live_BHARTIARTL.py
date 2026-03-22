#!/usr/bin/env python3
"""
Live Trading Script - BHARTIARTL.NS
Strategy: Momentum (RSI + ATR breakout)
Win Rate: N/A (default source)
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_BHARTIARTL.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_BHARTIARTL")

SYMBOL         = "BHARTIARTL.NS"
STRATEGY       = "MOMENTUM"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"rsi_period": 14, "atr_period": 14, "rsi_buy": 55, "rsi_sell": 45}

# 3-TIER EXIT SYSTEM (enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window
BEST_ENTRY_START = dtime(9, 30)  # 9:30 AM IST
BEST_ENTRY_END   = dtime(14, 30) # 2:30 PM IST
NO_ENTRY_AFTER   = dtime(14, 30) # No new entries after 2:30 PM

def can_new_entry() -> bool:
    """Only allow entries during best entry window."""
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
                {
                    "date": str(idx.date()),
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
                    "close": float(r["Close"]),
                    "volume": int(r["Volume"]),
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
    rsi = []
    gains, losses = [], []
    for i, bar in enumerate(ohlcv):
        if i == 0:
            rsi.append(None)
            continue
        change = bar["close"] - ohlcv[i - 1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
        if i < period:
            rsi.append(None)
        elif i == period:
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 0
            rsi.append(100 - 100 / (1 + rs))
        else:
            avg_gain = (rsi[-1] * (period - 1) + gains[-1]) / period if rsi[-1] is not None else gains[-1]
            avg_loss = (losses[-1] * (period - 1) + losses[-1]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 0
            rsi.append(100 - 100 / (1 + rs))
    return rsi

def momentum_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    rsi_period  = params["rsi_period"]
    atr_period  = params["atr_period"]
    rsi_buy_thresh = params["rsi_buy"]
    rsi_sell_thresh = params["rsi_sell"]

    rsi_vals = calculate_rsi(ohlcv, rsi_period)
    atr_vals = calculate_atr(ohlcv, atr_period)

    # Momentum: BUY when RSI crosses above rsi_buy AND price > 20-day SMA
    #            SELL when RSI crosses below rsi_sell AND price < 20-day SMA
    sma_period = 20
    sma_vals = []
    for i in range(len(ohlcv)):
        if i < sma_period - 1:
            sma_vals.append(None)
        else:
            sma = sum(ohlcv[j]["close"] for j in range(i - sma_period + 1, i + 1)) / sma_period
            sma_vals.append(sma)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(rsi_period, sma_period), len(ohlcv)):
        if rsi_vals[i] is None or atr_vals[i] is None or sma_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        rsi   = rsi_vals[i]
        sma   = sma_vals[i]
        atr   = atr_vals[i]

        # BUY: RSI above threshold AND price above SMA (uptrend momentum)
        if rsi > rsi_buy_thresh and price > sma:
            signals[i] = "BUY"
        # SELL: RSI below threshold AND price below SMA (downtrend momentum)
        elif rsi < rsi_sell_thresh and price < sma:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr


def main():
    """Main trading loop for BHARTIARTL"""
    symbol = "BHARTIARTL"
    params = {
        "rsi_period": 14,
        "atr_period": 14,
        "rsi_buy": 60,
        "rsi_sell": 40,
    }
    data = fetch_recent_data(days=60)
    if not data:
        print(f"No data for {symbol}")
        return
    signal, price, atr = momentum_signal(data, params)
    if signal in ("BUY", "SELL"):
        print(f"SIGNAL: {signal} {symbol} @ Rs{price:.2f} ATR: {atr:.2f}")
        quantity = max(1, 7000 // price)
        place_groww_order(symbol, signal, quantity, price)
    else:
        print(f"No signal: {signal}")

if __name__ == "__main__":
    main()

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


# Entry point below
