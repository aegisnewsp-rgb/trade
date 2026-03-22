#!/usr/bin/env python3
"""
Live Trading Script - HDFCBANK.NS
Strategy: ADX_TREND_v3 (ENHANCED - Banking-optimized with multi-timeframe confirmation)
Win Rate: 60.61% -> Target 68%+ (v3: stricter ADX>28, volume 1.5x, RSI sweet spot, VWAP confirm, NIFTY BANK sector check)
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_HDFCBANK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HDFCBANK")

SYMBOL         = "HDFCBANK.NS"
BANK_INDEX     = "^NSEBANK"  # NIFTY BANK index for sector confirmation
STRATEGY       = "ADX_TREND_v3"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "adx_period": 14,
    "adx_threshold": 28,          # RAISED from 25: stricter trend confirmation
    "rsi_period": 14,
    "rsi_oversold": 45,          # RAISED from 40: sweet spot 45-60 for buys
    "rsi_overbought": 60,
    "rsi_sweet_spot_min": 45,     # NEW: RSI sweet spot lower bound
    "rsi_sweet_spot_max": 60,    # NEW: RSI sweet spot upper bound
    "volume_multiplier": 1.5,     # RAISED from 1.2: HDFCBANK high-volume, need stronger spike
    "atr_period": 14,
    "vwap_period": 14,            # NEW: VWAP confirmation
    "confidence_threshold": 0.60, # NEW: minimum confidence to enter
}

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

def fetch_bank_index_data(days: int = 30, retries: int = 3) -> list | None:
    """Fetch NIFTY BANK index data for sector confirmation."""
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
            log.info("Fetched %d candles for %s", len(ohlcv), BANK_INDEX)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching bank index: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.warning("Bank index fetch failed for %s, proceeding without sector confirmation", BANK_INDEX)
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
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    rsi = [None] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(ohlcv)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi.append(100 - (100 / (1 + rs)))
    return rsi

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_vwap(ohlcv: list, period: int = 14) -> float:
    """Calculate VWAP for last N candles - returns current VWAP value."""
    if len(ohlcv) < period:
        return ohlcv[-1]["close"] if ohlcv else 0.0
    tp_sum = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                 for j in range(len(ohlcv) - period, len(ohlcv)))
    vol_sum = sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv)))
    return tp_sum / vol_sum if vol_sum > 0 else ohlcv[-1]["close"]

def calculate_bank_index_signal(bank_data: list) -> str:
    """Calculate simple signal from NIFTY BANK index - returns BULLISH, BEARISH, or NEUTRAL."""
    if not bank_data or len(bank_data) < 5:
        return "NEUTRAL"
    
    # Simple trend: compare recent close to moving average
    closes = [bar["close"] for bar in bank_data[-10:]]
    if len(closes) < 5:
        return "NEUTRAL"
    
    ma5 = sum(closes[-5:]) / 5
    current_close = closes[-1]
    
    if current_close > ma5 * 1.005:  # 0.5% above MA
        return "BULLISH"
    elif current_close < ma5 * 0.995:  # 0.5% below MA
        return "BEARISH"
    return "NEUTRAL"

def adx_signal_v3(ohlcv: list, params: dict, bank_index_data: list = None) -> tuple[str, float, float, float]:
    """
    v3 ADX Trend ENHANCED for HDFCBANK banking sector:
    - ADX > 28 (stricter than v2's 25)
    - RSI in sweet spot 45-60 for BUY, 40-55 for SELL
    - Volume > 1.5x average (raised from 1.2x)
    - VWAP confirmation (price > VWAP for longs)
    - NIFTY BANK index confirmation
    - Confidence scoring to filter weak signals
    
    Returns: (signal, price, atr, confidence)
    """
    period          = params["adx_period"]
    threshold       = params["adx_threshold"]
    rsi_period      = params["rsi_period"]
    rsi_overbought  = params["rsi_overbought"]
    rsi_oversold    = params["rsi_oversold"]
    rsi_sweet_min   = params.get("rsi_sweet_spot_min", 45)
    rsi_sweet_max   = params.get("rsi_sweet_spot_max", 60)
    vol_mult        = params["volume_multiplier"]
    vwap_period     = params.get("vwap_period", 14)
    conf_threshold  = params.get("confidence_threshold", 0.60)

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
        up_move   = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i]  = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(ohlcv) < period * 2:
        return "HOLD", close[-1], 0.0, 0.0

    tr_smooth   = ema(tr_list, period)
    plus_dm_sm  = ema(plus_dm, period)
    minus_dm_sm = ema(minus_dm, period)

    plus_di  = [100 * plus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]
    minus_di = [100 * minus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]

    dx = [100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          if (plus_di[i] + minus_di[i]) != 0 else 0 for i in range(len(ohlcv))]
    adx_vals = ema(dx, period)

    rsi_vals = calculate_rsi(ohlcv, rsi_period)
    avg_vol  = calculate_avg_volume(ohlcv, period)
    current_vwap = calculate_vwap(ohlcv, vwap_period)
    
    # Bank index confirmation
    bank_signal = calculate_bank_index_signal(bank_index_data) if bank_index_data else "NEUTRAL"

    if len(adx_vals) < 2:
        return "HOLD", close[-1], 0.0, 0.0

    # Signal: trending ADX with directional crossover + RSI filter + volume + VWAP confirm
    signal = "HOLD"
    confidence = 0.0
    
    if adx_vals[-1] > threshold:
        current_vol = ohlcv[-1]["volume"]
        vol_ok = current_vol > avg_vol * vol_mult
        rsi_now = rsi_vals[-1] if rsi_vals[-1] is not None else 50
        current_price = close[-1]
        
        # VWAP confirmation check
        price_above_vwap = current_price > current_vwap
        price_below_vwap = current_price < current_vwap
        
        # RSI sweet spot check
        rsi_in_buy_zone = rsi_sweet_min <= rsi_now <= rsi_sweet_max
        rsi_in_sell_zone = rsi_oversold <= rsi_now <= rsi_overbought
        
        # Calculate confidence score components
        conf_adx = min(adx_vals[-1] / 40, 1.0)  # ADX contribution (max at 40)
        conf_volume = min(vol_ok, (current_vol / (avg_vol * vol_mult)))  # Volume strength
        conf_rsi_buy = 1.0 if rsi_in_buy_zone else 0.5 if rsi_sweet_min <= rsi_now <= 65 else 0.0
        conf_rsi_sell = 1.0 if rsi_in_sell_zone else 0.5 if 35 <= rsi_now <= rsi_overbought else 0.0
        conf_bank = 1.0 if bank_signal == "NEUTRAL" else (0.8 if bank_signal == "BULLISH" else 0.4)
        
        if plus_di[-1] > minus_di[-1] and plus_di[-2] <= minus_di[-2]:
            # BUY: bullish crossover + RSI sweet spot + volume confirm + VWAP confirm
            if rsi_in_buy_zone and vol_ok and price_above_vwap:
                # Confidence: weighted average of factors
                confidence = (conf_adx * 0.35 + conf_volume * 0.25 + conf_rsi_buy * 0.25 + conf_bank * 0.15)
                if confidence >= conf_threshold:
                    signal = "BUY"
                    log.info("BUY signal | ADX=%.1f | RSI=%.1f | Vol=%.1fx | VWAP=%.2f | Bank=%s | Conf=%.2f",
                             adx_vals[-1], rsi_now, current_vol/avg_vol, current_vwap, bank_signal, confidence)
                    
        elif minus_dm[-1] > plus_dm[-1] and minus_dm[-2] <= plus_dm[-2]:
            # SELL: bearish crossover + RSI not oversold + volume confirm + VWAP confirm
            if rsi_in_sell_zone and vol_ok and price_below_vwap:
                confidence = (conf_adx * 0.35 + conf_volume * 0.25 + conf_rsi_sell * 0.25 + conf_bank * 0.15)
                if confidence >= conf_threshold:
                    signal = "SELL"
                    log.info("SELL signal | ADX=%.1f | RSI=%.1f | Vol=%.1fx | VWAP=%.2f | Bank=%s | Conf=%.2f",
                             adx_vals[-1], rsi_now, current_vol/avg_vol, current_vwap, bank_signal, confidence)

    atr_vals = calculate_atr(ohlcv, params["atr_period"])
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, close[-1], current_atr, confidence

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
