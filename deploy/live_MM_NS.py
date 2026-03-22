#!/usr/bin/env python3
"""
Live Trading Script - M&M.NS
Strategy: VWAP (Volume Weighted Average Price)
Enhanced with: Festival Season Check, Tractor Sales Proxy
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Research: 2026-03-22 - Top momentum pick (+4.91% 5D), PE 22x, Beta 0.29
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
from typing import Optional, List

import yfinance
YFINANCE_AVAILABLE = True
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_MM_NS.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_MM_NS")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "M&M.NS"
STRATEGY       = "VWAP_AUTOMOBILE_FESTIVE"
WIN_RATE       = "N/A (new)"
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "vwap_period": 14, "atr_multiplier": 1.5,
    # Sniper params (2026-03-22)
    "rsi_buy": 50, "vol_threshold": 0.5, "hold_days": 5,
}

# Festival and seasonality
# Key Indian festivals affecting tractor sales: Diwali, Holi, Dussehra
FESTIVE_MONTHS = [1, 9, 10, 11]  # January (post-winter), September-October (festive), November (Diwali)
HARVEST_SEASON_MONTHS = [2, 3, 4, 10, 11]  # Rabi harvest Oct-Nov, Kharif harvest Mar-Apr

# Tractor sales proxy
TRACTOR_SALES_ETB_SYMBOL = "TRACTORIND.NS"  # Escorts Tractor (tractor sector proxy)

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

# Smart entry: 9:30-14:30 IST
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

def get_festive_season_status() -> str:
    """
    Determine current festive/harvest season status for rural economy
    Returns: FESTIVE_PEAK, HARVEST_ACTIVE, OFF_SEASON
    """
    now = ist_now()
    month_num = now.month
    
    # Check for festive season
    if month_num in FESTIVE_MONTHS:
        return "HARVEST_ACTIVE" if month_num in HARVEST_SEASON_MONTHS else "FESTIVE_PEAK"
    
    # Check harvest season
    if month_num in HARVEST_SEASON_MONTHS:
        return "HARVEST_ACTIVE"
    
    return "OFF_SEASON"

def get_tractor_sales_proxy() -> Optional[str]:
    """
    Get tractor sales indicator using Escorts Tractor as proxy
    """
    try:
        tractor_etb = yf.Ticker(TRACTOR_SALES_ETB_SYMBOL).history(period="10d")
        if len(tractor_etb) >= 2:
            current = float(tractor_etb["Close"].iloc[-1])
            previous = float(tractor_etb["Close"].iloc[-2])
            if current > previous * 1.01:
                return "STRONG"
            elif current < previous * 0.99:
                return "WEAK"
            return "MODERATE"
    except Exception as e:
        log.warning(f"Failed to fetch tractor sales proxy: {e}")
    return None

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
    """Calculate VWAP using period for lookback"""
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            window = ohlcv[i - period + 1:i + 1]
            typical_prices = [(bar["high"] + bar["low"] + bar["close"]) / 3 for bar in window]
            volumes = [bar["volume"] for bar in window]
            vwap_value = sum(tp * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
            vwap.append(vwap_value)
    return vwap

def get_trade_decision(price: float, vwap: float, atr: float, multiplier: float = 1.5) -> str:
    if vwap is None or atr is None:
        return "HOLD"
    upper_band = vwap + atr * multiplier
    lower_band = vwap - atr * multiplier
    if price > upper_band:
        return "BUY"
    elif price < lower_band:
        return "SELL"
    return "HOLD"

def apply_festive_and_tractor_filters(signal: str, festive_status: str, 
                                      tractor_sales: Optional[str]) -> str:
    """
    Apply festival season and tractor sales filters for M&M
    M&M is heavily rural/agriculture focused
    """
    if signal == "HOLD":
        return "HOLD"
    
    # Festival season filter
    log.info(f"Festive/Harvest Status: {festive_status}")
    
    if festive_status == "OFF_SEASON":
        if signal == "BUY":
            log.info("Off-season - reducing BUY conviction")
            # Convert to HOLD during off-season for BUY signals
            return "HOLD"
    elif festive_status == "FESTIVE_PEAK" or festive_status == "HARVEST_ACTIVE":
        if signal == "SELL":
            log.info("Festive/Harvest season - reducing SELL conviction")
            # Agricultural demand is strong, reduce SELL
            return "HOLD"
    
    # Tractor sales proxy filter
    if tractor_sales is not None:
        log.info(f"Tractor Sales Indicator: {tractor_sales}")
        
        if signal == "BUY" and tractor_sales == "WEAK":
            log.info("Weak tractor sales - blocking BUY")
            return "HOLD"
        if signal == "SELL" and tractor_sales == "STRONG":
            log.info("Strong tractor sales - blocking SELL")
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
    """Main execution for M&M with festive season and tractor sales filters"""
    try:
        import yfinance
        YFINANCE_AVAILABLE = True
    
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return
    
    fname = Path(__file__).stem
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix
    
    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym}) - Enhanced with Festival + Tractor Sales")
    print(f"{'='*60}")
    
    # Check seasonal indicators
    festive_status = get_festive_season_status()
    tractor_sales = get_tractor_sales_proxy()
    
    log.info(f"Agriculture Check | Season: {festive_status} | Tractor Sales: {tractor_sales}")
    
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
    
    # Build ohlcv dict list
    ohlcv_dict = [{"open": o[0], "high": o[1], "low": o[2], "close": o[3], "volume": o[4]} for o in ohlcv_list]
    
    # Calculate indicators
    vwap_period = PARAMS["vwap_period"]
    atr_period = 14
    
    vwap_vals = calculate_vwap(ohlcv_dict, vwap_period)
    atr_vals = calculate_atr(ohlcv_dict, atr_period)
    
    current_price = ohlcv_dict[-1]["close"]
    current_vwap = vwap_vals[-1] if vwap_vals and vwap_vals[-1] is not None else current_price
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else current_price * 0.015
    
    signal = get_trade_decision(current_price, current_vwap, current_atr, PARAMS["atr_multiplier"])
    filtered_signal = apply_festive_and_tractor_filters(signal, festive_status, tractor_sales)
    
    print(f"\nSignal: {filtered_signal} (raw: {signal})")
    print(f"Price:  Rs{current_price:.2f}")
    print(f"VWAP:   Rs{current_vwap:.2f}")
    print(f"ATR:    Rs{current_atr:.2f}")
    print(f"Season: {festive_status}")
    print(f"Tractor Sales Proxy: {tractor_sales}")
    
    if filtered_signal == "BUY":
        sl = round(current_price - current_atr * 1.0, 2)
        tgt = round(current_price + current_atr * 4.0, 2)
        qty = max(1, int(10000 / current_price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{current_price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-current_price:.2f} reward)")
        
        try:
            from groww_api import paper_trade
            paper_trade("BUY", ticker_sym, current_price, qty)
        except:
            pass
    
    elif filtered_signal == "SELL":
        sl = round(current_price + current_atr * 1.0, 2)
        tgt = round(current_price - current_atr * 4.0, 2)
        qty = max(1, int(10000 / current_price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-current_price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{current_price-tgt:.2f} reward)")
        
        try:
            from groww_api import paper_trade
            paper_trade("SELL", ticker_sym, current_price, qty)
        except:
            pass
    
    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()
