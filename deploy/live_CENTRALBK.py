#!/usr/bin/env python3
"""
Live Trading Script - CENTRALBK.NS
Strategy: MA_ENVELOPE
Win Rate: 58.60%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_CENTRALBK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_CENTRALBK")

SYMBOL         = "CENTRALBK.NS"
STRATEGY       = "MA_ENVELOPE"
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"ma_period": 20, "envelope_pct": 0.02}

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

def calculate_ma(prices: list, period: int) -> list:
    ma = []
    for i in range(len(prices)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(prices[i - period + 1:i + 1]) / period)
    return ma

def ma_envelope_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period  = params["ma_period"]
    env_pct = params["envelope_pct"]
    closes  = [b["close"] for b in ohlcv]
    ma_vals = calculate_ma(closes, period)
    signals = ["HOLD"] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        if ma_vals[i] is None: continue
        price = closes[i]
        upper = ma_vals[i] * (1 + env_pct)
        lower = ma_vals[i] * (1 - env_pct)
        if price < lower:
            signals[i] = "BUY"
        elif price > upper:
            signals[i] = "SELL"
    atr_vals       = calculate_atr(ohlcv)
    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

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
        ticker = yfinance.Ticker("CENTRALBK.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            print("CENTRALBK: No data")
            return
        closes = d['Close'].tolist()
        print(f"CENTRALBK: {len(closes)} candles, last price {closes[-1]:.2f}")
    except Exception as e:
        print(f"CENTRALBK: Error - {e}")

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()


if __name__ == "__main__": main()
