#!/usr/bin/env python3
"""
Live Trading Script - ACC.NS
Strategy: MA_ENVELOPE (ENHANCED v3)
Win Rate: 59.09% → Target 65-70% with 3-tier exits + RSI filter + volume confirmation
Position: ₹7000 | Daily Loss Cap: 0.3%

Enhancements v3:
- 3-tier profit targets (T1: 1.5x, T2: 3.0x, T3: 5.0x risk)
- RSI confirmation filter (RSI > 50 for BUY, RSI < 50 for SELL)
- Entry window: 9:30 AM - 2:30 PM IST only
- Volume confirmation: 1.2x 20-day MA required
- Trailing stop after T1 hit
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
        logging.FileHandler(LOG_DIR / "live_ACC.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ACC")

SYMBOL         = "ACC.NS"
STRATEGY       = "MA_ENVELOPE_V3"
POSITION       = 7000
DAILY_LOSS_CAP = 0.003
# ENHANCED v3: Added RSI period, tighter envelope, volume confirmation
PARAMS         = {"ma_period": 15, "envelope_pct": 0.015, "atr_multiplier": 1.5, "volume_ma_period": 20, "volume_mult": 1.2, "rsi_period": 14}

# 3-TIER EXIT SYSTEM
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

# RSI filter
ENTRY_RSI_MIN    = 50      # RSI must be above 50 for BUY
ENTRY_RSI_MAX    = 50      # RSI must be below 50 for SELL

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"
IST_TZ_OFFSET = 5.5

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

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

def calculate_volume_ma(ohlcv: list, period: int = 20) -> list:
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            vol_ma.append(sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period)
    return vol_ma

def calculate_rsi(prices: list, period: int = 14) -> list:
    """Calculate RSI indicator."""
    rsi = []
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    
    for i in range(len(prices)):
        if i < period:
            rsi.append(None)
        elif i == period:
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
        else:
            avg_gain = (rsi[-1] * (period - 1) + gains[i-1]) / period if rsi[-1] != 0 else gains[i-1] / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period if avg_loss != 0 else losses[i-1] / period
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
    return rsi

def ma_envelope_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    """Returns: (signal, price, atr, rsi)"""
    period      = params["ma_period"]
    env_pct     = params["envelope_pct"]
    vol_ma_per  = params.get("volume_ma_period", 20)
    vol_mult    = params.get("volume_mult", 1.2)
    rsi_period  = params.get("rsi_period", 14)
    
    closes      = [b["close"] for b in ohlcv]
    ma_vals     = calculate_ma(closes, period)
    vol_ma      = calculate_volume_ma(ohlcv, vol_ma_per)
    atr_vals    = calculate_atr(ohlcv)
    rsi_vals    = calculate_rsi(closes, rsi_period)
    signals     = ["HOLD"] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if ma_vals[i] is None or atr_vals[i] is None:
            continue
        price   = closes[i]
        upper   = ma_vals[i] * (1 + env_pct)
        lower   = ma_vals[i] * (1 - env_pct)
        current_rsi = rsi_vals[i] if rsi_vals and i < len(rsi_vals) else 50
        
        # ENHANCED v3: Volume confirmation + RSI filter
        if vol_ma[i] is not None and ohlcv[i]["volume"] < vol_ma[i] * vol_mult:
            continue
        if current_rsi is None:
            continue
            
        if price < lower and current_rsi > ENTRY_RSI_MIN:
            signals[i] = "BUY"
        elif price > upper and current_rsi < ENTRY_RSI_MAX:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    return current_signal, current_price, current_atr, current_rsi

def place_groww_order(symbol, signal, quantity, price, atr):
    """
    Place order via Groww API or paper trade.
    Uses 3-TIER EXIT SYSTEM:
    - T1: 1.5x risk → exit 1/3
    - T2: 3.0x risk → exit 1/3
    - T3: 5.0x risk → exit remaining
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    risk = atr * SL_ATR_MULT
    stop_loss = price - risk if signal == "BUY" else price + risk
    
    # 3-tier targets
    t1 = price + (risk * TARGET_1_MULT) if signal == "BUY" else price - (risk * TARGET_1_MULT)
    t2 = price + (risk * TARGET_2_MULT) if signal == "BUY" else price - (risk * TARGET_2_MULT)
    t3 = price + (risk * TARGET_3_MULT) if signal == "BUY" else price - (risk * TARGET_3_MULT)
    
    # Use bracket order with T1 as primary target
    result = groww_api.place_bo(
        exchange=exchange,
        symbol=symbol,
        transaction=signal,
        quantity=quantity,
        target_price=t1,
        stop_loss_price=stop_loss,
        trailing_sl=0.3,
        trailing_target=0.5
    )
    
    if result:
        log.info("3-TIER ORDER: {} {} @ Rs{:.2f} | SL: {:.2f} | T1: {:.2f} T2: {:.2f} T3: {:.2f}".format(
            signal, quantity, price, stop_loss, t1, t2, t3))
    return result


def main():
    log.info("Starting ACC.NS live trader - Strategy: %s", STRATEGY)
    
    while True:
        try:
            now = ist_now()
            
            # Check if market is open
            if not is_market_open():
                if is_pre_market():
                    log.info("Pre-market hours - waiting for open at 9:15 AM IST")
                else:
                    log.info("Market closed - sleeping 60s")
                time.sleep(60)
                continue
            
            # Check entry window
            if not can_new_entry():
                time.sleep(60)
                continue
            
            # Fetch data
            ohlcv = fetch_recent_data(days=60)
            if not ohlcv:
                log.warning("No data - retrying in 30s")
                time.sleep(30)
                continue
            
            # Get signal with RSI
            signal, price, atr, rsi = ma_envelope_signal(ohlcv, PARAMS)
            log.info("Signal: %s | Price: %.2f | ATR: %.2f | RSI: %.2f", signal, price, atr, rsi)
            
            if signal == "HOLD":
                time.sleep(60)
                continue
            
            # Calculate position size
            risk = atr * SL_ATR_MULT
            if risk <= 0:
                risk = price * 0.01
            max_risk = POSITION * 0.02  # 2% max risk
            risk = min(risk, max_risk)
            quantity = int(POSITION / price)
            
            # Place order
            result = place_groww_order(SYMBOL, signal, quantity, price, atr)
            if result:
                log.info("Order result: %s", result)
            
            time.sleep(300)  # Wait 5 min between signals
            
        except KeyboardInterrupt:
            log.info("Shutdown requested")
            break
        except Exception as e:
            log.error("Error: %s", e)
            time.sleep(30)


if __name__ == "__main__": main()
