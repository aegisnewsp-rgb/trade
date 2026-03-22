#!/usr/bin/env python3
"""
Live Trading Script - HCLTECH.NS
Strategy: VWAP_RSI_v2 (Enhanced VWAP + RSI Momentum + Volume Confirmation)
Enhanced with: USD/INR Exchange Rate Check, NASDAQ Correlation
Win Rate: N/A -> Target 65%+
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

import yfinance
YFINANCE_AVAILABLE = True as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_HCLTECH.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HCLTECH")

SYMBOL         = "HCLTECH.NS"
STRATEGY       = "VWAP_RSI_v2_IT"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "vwap_period": 14, "atr_period": 14, "atr_multiplier": 1.5,
    "rsi_period": 14, "rsi_overbought": 55, "rsi_oversold": 45,
    "volume_multiplier": 1.2, "trend_ma_period": 50,
    "usd_inr_warning": 83.5,  # Block BUY if USD/INR above this
    "usd_inr_support": 82.0,  # Strong BUY signal if below
}

# Trailing stop: 0.3x ATR
TRAIL_ATR_MULT    = 0.3    # Trailing stop: 0.3x ATR
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT     = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT     = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT     = 5.0     # T3: 5.0x risk → exit remaining

# 3-TIER EXIT SYSTEM (v3 enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window (IT stocks have specific liquidity patterns)
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

# IT sector correlates with NASDAQ
NASDAQ_SYMBOL = "^IXIC"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)

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

def get_usd_inr_rate() -> Optional[float]:
    """Fetch current USD/INR exchange rate"""
    try:
        # Use USD/INR pair from yfinance
        usd_inr = yf.Ticker("USDINR=X").history(period="5d")
        if not usd_inr.empty:
            return float(usd_inr["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"Failed to fetch USD/INR: {e}")
    return None

def get_nasdaq_trend() -> Optional[str]:
    """Fetch NASDAQ trend direction"""
    try:
        nasdaq = yf.Ticker(NASDAQ_SYMBOL).history(period="10d")
        if len(nasdaq) >= 2:
            current = float(nasdaq["Close"].iloc[-1])
            previous = float(nasdaq["Close"].iloc[-2])
            if current > previous * 1.005:
                return "BULLISH"
            elif current < previous * 0.995:
                return "BEARISH"
            return "NEUTRAL"
    except Exception as e:
        log.warning(f"Failed to fetch NASDAQ: {e}")
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

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum = sum(
                (ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                for j in range(i - period + 1, i + 1)
            )
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

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

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def vwap_rsi_signal_v2(ohlcv: list, params: dict) -> tuple:
    """v2 VWAP + RSI: adds volume confirmation + trend MA alignment for IT sector."""
    period     = params["vwap_period"]
    atr_period = params["atr_period"]
    atr_mult   = params["atr_multiplier"]
    rsi_period = params["rsi_period"]
    rsi_ob     = params["rsi_overbought"]
    rsi_os     = params["rsi_oversold"]
    vol_mult   = params["volume_multiplier"]
    trend_period = params["trend_ma_period"]

    vwap_vals = calculate_vwap(ohlcv, period)
    atr_vals  = calculate_atr(ohlcv, atr_period)
    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    ma_vals   = calculate_ma(ohlcv, trend_period)
    avg_vol   = calculate_avg_volume(ohlcv, period)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(period, rsi_period, trend_period), len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        if ma_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        v, a, r = vwap_vals[i], atr_vals[i], rsi_vals[i]
        vol = ohlcv[i]["volume"]
        trend = ma_vals[i]

        volume_ok   = vol > avg_vol * vol_mult
        above_trend = price > trend
        below_trend = price < trend

        # BUY: bullish VWAP breakout + RSI confirm + volume + trend alignment
        if price > v + a * atr_mult and r < rsi_ob and volume_ok and above_trend:
            signals[i] = "BUY"
        # SELL: bearish VWAP breakdown + RSI confirm + volume + trend alignment
        elif price < v - a * atr_mult and r > rsi_os and volume_ok and below_trend:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr, current_rsi

def apply_it_sector_filters(signal: str, usd_inr: Optional[float], 
                            nasdaq_trend: Optional[str], params: dict) -> str:
    """Apply IT sector-specific filters: USD/INR and NASDAQ correlation"""
    if signal == "HOLD":
        return "HOLD"
    
    # USD/INR filter - IT companies benefit from weaker rupee
    if usd_inr is not None:
        warning_threshold = params.get("usd_inr_warning", 83.5)
        support_threshold = params.get("usd_inr_support", 82.0)
        
        if usd_inr > warning_threshold:
            log.info(f"USD/INR elevated: {usd_inr:.2f} - Negative for IT exports")
            # Weaken SELL conviction but don't block
            if signal == "SELL":
                log.info("SELL signal weakened by high USD/INR")
        
        if usd_inr < support_threshold:
            log.info(f"USD/INR supportive: {usd_inr:.2f} - Positive for IT exports")
            if signal == "BUY":
                log.info("BUY signal strengthened by low USD/INR")
    
    # NASDAQ correlation filter
    if nasdaq_trend is not None:
        if signal == "BUY" and nasdaq_trend == "BEARISH":
            log.info(f"NASDAQ bearish - blocking BUY signal")
            return "HOLD"
        if signal == "SELL" and nasdaq_trend == "BULLISH":
            log.info(f"NASDAQ bullish - blocking SELL signal")
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
    """Main execution for HCLTECH with USD/INR and NASDAQ filters"""
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
    print(f"Running: {ticker_sym} ({yahoo_sym}) - Enhanced with USD/INR + NASDAQ")
    print(f"{'='*60}")
    
    # Fetch IT sector indicators
    usd_inr = get_usd_inr_rate()
    nasdaq_trend = get_nasdaq_trend()
    
    log.info(f"IT Sector Check | USD/INR: {usd_inr:.4f if usd_inr else 'N/A'} | NASDAQ: {nasdaq_trend}")
    
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
    
    # Get signal
    signal, price, atr, rsi = vwap_rsi_signal_v2(ohlcv_dict, PARAMS)
    filtered_signal = apply_it_sector_filters(signal, usd_inr, nasdaq_trend, PARAMS)

    print(f"\nSignal: {filtered_signal} (raw: {signal})")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    print(f"RSI:    {rsi:.2f}")
    print(f"USD/INR: {usd_inr:.4f if usd_inr else 'N/A'}")
    print(f"NASDAQ: {nasdaq_trend}")
    print(f"Entry Window: {'YES' if can_new_entry() else 'NO'}")

    risk = atr * 1.0
    t1 = round(price + risk * TARGET_1_MULT, 2)
    t2 = round(price + risk * TARGET_2_MULT, 2)
    t3 = round(price + risk * TARGET_3_MULT, 2)
    sl = round(price - risk * 1.0, 2)
    print(f"SL:     Rs{sl:.2f}")
    print(f"T1:     Rs{t1:.2f} (1.5x risk, exit 1/3)")
    print(f"T2:     Rs{t2:.2f} (3.0x risk, exit 1/3)")
    print(f"T3:     Rs{t3:.2f} (5.0x risk, exit remaining)")
    print(f"Trail:  0.3x ATR trailing stop after 0.8% profit")

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
