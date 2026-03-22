#!/usr/bin/env python3
"""
Live Trading Script - HINDALCO.NS
Strategy: VWAP_TREND_VOL_v2 (Enhanced VWAP + Trend MA Confirmation + Volume Filter)
Enhanced with: Global Commodity Correlation, ADX Trend Confirmation
Win Rate: N/A -> Target 60%+
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
"""

from typing import Optional
import os
import sys
import json
import time
import logging
import groww_api
import requests
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True as yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_HINDALCO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HINDALCO")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "HINDALCO.NS"
STRATEGY       = "VWAP_TREND_VOL_v2_ADX"
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "vwap_period": 14,
    "atr_multiplier": 1.5,
    "rsi_period": 14,
    "rsi_oversold": 45,
    "rsi_overbought": 55,
    "volume_multiplier": 1.2,
    "trend_ma_period": 50,
    "atr_period": 14,
    "adx_period": 14,
    "adx_threshold": 25,  # ADX must be above this for trend confirmation
    "trail_atr_mult": 0.3,
}

# Entry time window (IST)
ENTRY_START = dtime(9, 30)
ENTRY_END   = dtime(14, 30)

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Commodity Symbols ─────────────────────────────────────────────────────────
LME_ALUMINUM_SYMBOL = "ALI=F"  # Aluminum futures
COPPER_GLOBAL_SYMBOL = "HG=F"  # Copper futures
IRON_ORE_SYMBOL = "IRONORE"  # Use generic ticker

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)


def can_new_entry() -> bool:
    """TIME FILTER: No entries before 9:30 AM or after 2:30 PM IST"""
    now = ist_now().time()
    if now < ENTRY_START:
        log.info("⏰ Too early - waiting for 9:30 AM")
        return False
    if now >= ENTRY_END:
        log.info("⏰ After 2:30 PM - no new entries today")
        return False
    return True

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
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

def get_global_commodity_prices() -> dict:
    """Fetch global commodity prices for metals correlation"""
    result = {}
    symbols = {
        "aluminum": "ALI=F",
        "copper": "HG=F",
    }
    for name, sym in symbols.items():
        try:
            df = yf.Ticker(sym).history(period="5d")
            if not df.empty:
                result[name] = float(df["Close"].iloc[-1])
        except Exception as e:
            log.warning(f"Failed to fetch {name}: {e}")
    return result

def get_commodity_trend(commodity_prices: dict) -> Optional[str]:
    """Determine commodity trend direction"""
    if len(commodity_prices) < 2:
        return None
    values = list(commodity_prices.values())
    if all(values[i] >= values[i-1] for i in range(1, len(values))):
        return "BULLISH"
    elif all(values[i] <= values[i-1] for i in range(1, len(values))):
        return "BEARISH"
    return "NEUTRAL"

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

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_adx(ohlcv: list, period: int = 14) -> tuple[list, list, list]:
    """
    Calculate ADX (Average Directional Index) and +/- DI
    Returns: [adx_values, plus_di, minus_di]
    """
    if len(ohlcv) < period * 2:
        return [None] * len(ohlcv), [None] * len(ohlcv), [None] * len(ohlcv)
    
    high = [bar["high"] for bar in ohlcv]
    low = [bar["low"] for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]
    
    # Calculate True Range and Directional Movement
    tr_list = []
    plus_dm = []
    minus_dm = []
    
    for i in range(len(ohlcv)):
        if i == 0:
            tr_list.append(high[i] - low[i])
            plus_dm.append(0)
            minus_dm.append(0)
        else:
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr_list.append(max(hl, hc, lc))
            
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
            
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
    
    # Smooth using Wilder's method
    atr_smooth = []
    plus_di_smooth = []
    minus_di_smooth = []
    
    # Initial smoothed values
    atr_smooth.append(sum(tr_list[:period]) / period)
    plus_di_smooth.append(sum(plus_dm[:period]) / period)
    minus_di_smooth.append(sum(minus_dm[:period]) / period)
    
    for i in range(period, len(ohlcv)):
        atr_smooth.append((atr_smooth[-1] * (period - 1) + tr_list[i]) / period)
        plus_di_smooth.append((plus_di_smooth[-1] * (period - 1) + plus_dm[i]) / period)
        minus_di_smooth.append((minus_di_smooth[-1] * (period - 1) + minus_dm[i]) / period)
    
    # Calculate DX and ADX
    adx_values = []
    plus_di_final = []
    minus_di_final = []
    
    for i in range(len(ohlcv)):
        if i < period - 1:
            adx_values.append(None)
            plus_di_final.append(None)
            minus_di_final.append(None)
        elif i == period - 1:
            plus_di_final.append(100 * plus_di_smooth[-1] / atr_smooth[-1] if atr_smooth[-1] > 0 else 0)
            minus_di_final.append(100 * minus_di_smooth[-1] / atr_smooth[-1] if atr_smooth[-1] > 0 else 0)
            dx = (plus_di_final[-1] - minus_di_final[-1]) / (plus_di_final[-1] + minus_di_final[-1]) * 100 if (plus_di_final[-1] + minus_di_final[-1]) > 0 else 0
            adx_values.append(abs(dx))
        else:
            plus_di_final.append(100 * plus_di_smooth[-1] / atr_smooth[-1] if atr_smooth[-1] > 0 else 0)
            minus_di_final.append(100 * minus_di_smooth[-1] / atr_smooth[-1] if atr_smooth[-1] > 0 else 0)
            dx = (plus_di_final[-1] - minus_di_final[-1]) / (plus_di_final[-1] + minus_di_final[-1]) * 100 if (plus_di_final[-1] + minus_di_final[-1]) > 0 else 0
            adx_values.append(abs(dx))
    
    return adx_values, plus_di_final, minus_di_final

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def vwap_signal_v2(ohlcv: list, params: dict, 
                   commodity_trend: Optional[str] = None,
                   adx_values: Optional[list] = None) -> tuple[str, float, float]:
    """
    v2 VWAP with trend confirmation: adds RSI filter + volume confirmation + trend MA
    Enhanced with ADX confirmation for metals sector
    """
    vwap_period    = params["vwap_period"]
    atr_mult       = params["atr_multiplier"]
    rsi_period     = params["rsi_period"]
    rsi_oversold   = params["rsi_oversold"]
    rsi_overbought = params["rsi_overbought"]
    vol_mult       = params["volume_multiplier"]
    trend_period   = params["trend_ma_period"]
    adx_threshold  = params.get("adx_threshold", 25)

    vwap_vals = calculate_vwap(ohlcv, vwap_period)
    atr_vals  = calculate_atr(ohlcv, params["atr_period"])
    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    ma_vals   = calculate_ma(ohlcv, trend_period)
    avg_vol   = calculate_avg_volume(ohlcv, vwap_period)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(vwap_period, rsi_period, trend_period), len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        if ma_vals[i] is None:
            continue

        price  = ohlcv[i]["close"]
        v      = vwap_vals[i]
        a      = atr_vals[i]
        r      = rsi_vals[i]
        vol    = ohlcv[i]["volume"]
        trend  = ma_vals[i]

        volume_ok   = vol > avg_vol * vol_mult
        above_trend = price > trend
        below_trend = price < trend
        
        # ADX confirmation
        adx_ok = True
        if adx_values is not None and adx_values[i] is not None:
            adx_ok = adx_values[i] >= adx_threshold
            log.info(f"ADX check: {adx_values[i]:.2f} vs threshold {adx_threshold}")

        # BUY: bullish VWAP breakout + RSI not overbought + volume + trend alignment + ADX
        if price > v + a * atr_mult and r < rsi_overbought and volume_ok and above_trend and adx_ok:
            signals[i] = "BUY"
        # SELL: bearish VWAP breakdown + RSI not oversold + volume + trend alignment + ADX
        elif price < v - a * atr_mult and r > rsi_oversold and volume_ok and below_trend and adx_ok:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def apply_commodity_filter(signal: str, commodity_trend: Optional[str]) -> str:
    """Apply global commodity trend filter for metals stocks"""
    if signal == "HOLD":
        return "HOLD"
    
    if commodity_trend is not None:
        # Metals stocks benefit from rising commodity prices
        if signal == "BUY" and commodity_trend == "BEARISH":
            log.info(f"Global commodities bearish - reducing BUY conviction")
            return "HOLD"
        if signal == "SELL" and commodity_trend == "BULLISH":
            log.info(f"Global commodities bullish - reducing SELL conviction")
            return "HOLD"
    
    return signal

def place_groww_order(symbol, signal, quantity, price):
    """Place order via Groww API or paper trade."""
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    # Use real ATR from calculate_atr()
    
    if signal == "BUY":
        stop_loss = price - (atr * 1.0)
        target = price + (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="BUY",
            quantity=quantity, target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = price + (atr * 1.0)
        target = price - (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol, transaction="SELL",
            quantity=quantity, target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("Order placed: {} {} {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
    return result

def main():
    """Main execution for HINDALCO with ADX and commodity correlation"""
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        import yfinance
YFINANCE_AVAILABLE = True as yf
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return
    
    fname = Path(__file__).stem
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix
    
    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym}) - Enhanced with ADX + Commodity")
    print(f"{'='*60}")
    
    # Fetch commodity data first
    commodity_prices = get_global_commodity_prices()
    commodity_trend = get_commodity_trend(commodity_prices)
    log.info(f"Commodity Check | Prices: {commodity_prices} | Trend: {commodity_trend}")
    
    # Fetch stock data
    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
        
        ohlcv_list = []
        for idx, row in data.iterrows():
            ohlcv_list.append([
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                float(row['Volume'])
            ])
        print(f"Loaded {len(ohlcv_list)} candles")
    except Exception as e:
        print(f"Data fetch error: {e}")
        return
    
    if not ohlcv_list:
        print("No OHLCV data")
        return
    
    # Build ohlcv dict list for the signal function
    ohlcv_dict = [{"open": o[0], "high": o[1], "low": o[2], "close": o[3], "volume": o[4]} for o in ohlcv_list]
    
    # Calculate ADX
    adx_vals, plus_di, minus_di = calculate_adx(ohlcv_dict, PARAMS["adx_period"])
    current_adx = adx_vals[-1] if adx_vals and adx_vals[-1] is not None else 0
    log.info(f"ADX: {current_adx:.2f} | Threshold: {PARAMS['adx_threshold']}")
    
    # Get signal
    signal, price, atr = vwap_signal_v2(ohlcv_dict, PARAMS, commodity_trend, adx_vals)
    filtered_signal = apply_commodity_filter(signal, commodity_trend)
    
    print(f"\nSignal: {filtered_signal} (raw: {signal})")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    print(f"ADX:    {current_adx:.2f}")
    print(f"Commodity Trend: {commodity_trend}")
    
    if filtered_signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")
        
        try:
            from groww_api import paper_trade
            paper_trade("BUY", ticker_sym, price, qty)
        except:
            pass
    
    elif filtered_signal == "SELL":
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{price-tgt:.2f} reward)")
        
        try:
            from groww_api import paper_trade
            paper_trade("SELL", ticker_sym, price, qty)
        except:
            pass
    
    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()
