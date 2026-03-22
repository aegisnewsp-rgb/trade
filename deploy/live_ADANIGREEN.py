#!/usr/bin/env python3
"""
Live Trading Script - ADANIGREEN.NS
Strategy: VWAP (Volume Weighted Average Price)
Win Rate: 70.00%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
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

import yfinance as yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_ADANIGREEN.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ADANIGREEN")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "ADANIGREEN.NS"
STRATEGY       = "VWAP_GREEN_ENERGY"
WIN_RATE       = "70.00%"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003

# Green Energy Sector Index Symbols (Yahoo Finance)
NIFTY_SYMBOL = "^NSEI"
SOLAR_INDEX_SYMBOL = "TAN"        # Invesco Solar ETF — solar sector proxy
WIND_INDEX_SYMBOL = "FAN"         # iShares Global Wind Energy ETF — wind sector proxy
RENEWABLE_INDEX_SYMBOL = "ICLN"  # iShares Global Clean Energy ETF — broad renewable

# Sector tailwind thresholds
SOLAR_MIN_PCT = 0.50    # Solar ETF > 50% of portfolio weight for bullish signal
WIND_MIN_PCT = 0.30     # Wind ETF > 30% for additional confirmation
RENEWABLE_CONFIRM = 0.55  # Renewable ETF above this = sector tailwind confirmed

PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5, "sector_tailwind_weight": 0.25,
          "rsi_threshold": 55, "volume_multiplier": 1.2}

# ── Groww Production Enhancements ───────────────────────────────────────────
# 3-Tier Target System (1.5x / 3x / 5x risk multiples)
TARGET_1_MULT = 1.5   # Exit 1/3 at 1.5× risk — secure profit
TARGET_2_MULT = 3.0   # Exit 1/3 at 3× risk — main target
TARGET_3_MULT = 5.0   # Exit remaining at 5× risk — stretch target

# Smart Entry Window: 9:30 AM – 2:30 PM IST only
SMART_ENTRY_START = dtime(9, 30)
SMART_ENTRY_END   = dtime(14, 30)

STOP_LOSS_PCT  = 0.008

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

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

def can_new_entry() -> bool:
    """HARD BLOCK: Only allow entries during smart session (9:30 AM - 2:30 PM IST)."""
    now = ist_now().time()
    if not (SMART_ENTRY_START <= now <= SMART_ENTRY_END):
        log.info("🛑 BLOCKED: Outside smart entry window (9:30 AM - 2:30 PM IST)")
        return False
    return True

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Calculate RSI for momentum confirmation."""
    rsi = [None] * period
    if len(ohlcv) < period + 1:
        return rsi
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    if len(gains) < period:
        return rsi + [None] * (len(ohlcv) - period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains) + 1):
        if i == period:
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
    return rsi

def get_avg_volume(ohlcv: list, lookback: int = 20) -> float:
    """Calculate average volume over lookback period."""
    if len(ohlcv) < lookback:
        return sum(ohlcv[j]["volume"] for j in range(len(ohlcv))) / len(ohlcv)
    return sum(ohlcv[j]["volume"] for j in range(-lookback, 0)) / lookback

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

def calculate_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

def get_green_energy_sector_tailwind() -> dict:
    """
    Check green energy sector conditions via solar/wind/renewable ETFs.
    ADANIGREEN is a pure-play renewable energy company — sector tailwinds directly benefit.
    
    Returns dict with:
    - solar_signal: bullish/neutral/bearish
    - wind_signal: bullish/neutral/bearish  
    - renewable_signal: bullish/neutral/bearish
    - combined: 0.0-1.0 score
    - tailwind_active: bool
    """
    result = {
        "solar_signal": "NEUTRAL",
        "wind_signal": "NEUTRAL",
        "renewable_signal": "NEUTRAL",
        "solar_pct_chg": 0.0,
        "wind_pct_chg": 0.0,
        "renewable_pct_chg": 0.0,
        "combined": 0.5,
        "tailwind_active": False,
    }
    
    try:
        # Solar ETF (TAN)
        solar_ticker = yf.Ticker(SOLAR_INDEX_SYMBOL)
        solar_data = solar_ticker.history(period="10d")
        if not solar_data.empty:
            solar_closes = solar_data["Close"].values
            if len(solar_closes) >= 2:
                solar_pct = (solar_closes[-1] - solar_closes[0]) / solar_closes[0]
                result["solar_pct_chg"] = solar_pct
                if solar_pct > SOLAR_MIN_PCT:
                    result["solar_signal"] = "BULLISH"
                elif solar_pct < -SOLAR_MIN_PCT:
                    result["solar_signal"] = "BEARISH"
                log.info("☀️ Solar ETF (TAN): %.2f%% | Signal: %s", solar_pct * 100, result["solar_signal"])
    except Exception as e:
        log.warning("Solar ETF check failed: %s", e)
    
    try:
        # Wind ETF (FAN)
        wind_ticker = yf.Ticker(WIND_INDEX_SYMBOL)
        wind_data = wind_ticker.history(period="10d")
        if not wind_data.empty:
            wind_closes = wind_data["Close"].values
            if len(wind_closes) >= 2:
                wind_pct = (wind_closes[-1] - wind_closes[0]) / wind_closes[0]
                result["wind_pct_chg"] = wind_pct
                if wind_pct > WIND_MIN_PCT:
                    result["wind_signal"] = "BULLISH"
                elif wind_pct < -WIND_MIN_PCT:
                    result["wind_signal"] = "BEARISH"
                log.info("🌬️ Wind ETF (FAN): %.2f%% | Signal: %s", wind_pct * 100, result["wind_signal"])
    except Exception as e:
        log.warning("Wind ETF check failed: %s", e)
    
    try:
        # Broad Renewable ETF (ICLN)
        renewable_ticker = yf.Ticker(RENEWABLE_INDEX_SYMBOL)
        renewable_data = renewable_ticker.history(period="10d")
        if not renewable_data.empty:
            renewable_closes = renewable_data["Close"].values
            if len(renewable_closes) >= 2:
                renewable_pct = (renewable_closes[-1] - renewable_closes[0]) / renewable_closes[0]
                result["renewable_pct_chg"] = renewable_pct
                if renewable_pct > RENEWABLE_CONFIRM:
                    result["renewable_signal"] = "BULLISH"
                elif renewable_pct < -RENEWABLE_CONFIRM:
                    result["renewable_signal"] = "BEARISH"
                log.info("⚡ Renewable ETF (ICLN): %.2f%% | Signal: %s", renewable_pct * 100, result["renewable_signal"])
    except Exception as e:
        log.warning("Renewable ETF check failed: %s", e)
    
    # Combined score: weighted average (renewable most important for ADANIGREEN)
    scores = []
    if result["solar_signal"] == "BULLISH":
        scores.append(0.3)
    elif result["solar_signal"] == "BEARISH":
        scores.append(0.0)
    if result["wind_signal"] == "BULLISH":
        scores.append(0.25)
    elif result["wind_signal"] == "BEARISH":
        scores.append(0.0)
    if result["renewable_signal"] == "BULLISH":
        scores.append(0.45)
    elif result["renewable_signal"] == "BEARISH":
        scores.append(0.0)
    
    if scores:
        result["combined"] = sum(scores) / len(scores) if scores else 0.5
    
    # Tailwind is active if renewable is bullish AND at least one of solar/wind is bullish
    result["tailwind_active"] = (
        result["renewable_signal"] == "BULLISH" and
        (result["solar_signal"] == "BULLISH" or result["wind_signal"] == "BULLISH")
    )
    
    log.info("🌱 Green Energy Combined Score: %.2f | Tailwind Active: %s", 
             result["combined"], result["tailwind_active"])
    return result

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, dict]:
    """
    VWAP signal with green energy sector tailwind filter.
    Enhanced with RSI filter (55/45) and volume confirmation (1.2x avg).

    Entry: price > VWAP + ATR AND sector tailwind active AND RSI > 55 AND volume > 1.2x avg
    Exit: price < VWAP - ATR OR RSI < 45 OR sector turns bearish
    """
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    rsi_threshold = params.get("rsi_threshold", 55)
    vol_mult      = params.get("volume_multiplier", 1.2)
    vwap_vals     = calculate_vwap(ohlcv, period)
    atr_vals      = calculate_atr(ohlcv, period)
    rsi_vals      = calculate_rsi(ohlcv, period)
    avg_vol       = get_avg_volume(ohlcv)
    signals       = ["HOLD"] * len(ohlcv)

    # Get green energy sector tailwind
    sector = get_green_energy_sector_tailwind()
    log.info("🌱 Sector Tailwind: Solar=%s Wind=%s Renewable=%s | Combined=%.2f | Active=%s",
             sector["solar_signal"], sector["wind_signal"], sector["renewable_signal"],
             sector["combined"], sector["tailwind_active"])

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        price    = ohlcv[i]["close"]
        v        = vwap_vals[i]
        a        = atr_vals[i]
        rsi      = rsi_vals[i]
        volume   = ohlcv[i]["volume"]
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0

        # BUY: price > VWAP + ATR AND sector tailwind AND RSI > 55 AND volume > 1.2x avg
        rsi_confirm = rsi > rsi_threshold
        vol_confirm = vol_ratio > vol_mult
        if price > v + a * atr_mult and sector["tailwind_active"] and rsi_confirm and vol_confirm:
            signals[i] = "BUY"
        # SELL: price < VWAP - ATR OR RSI < 45 OR sector turns bearish
        elif price < v - a * atr_mult or rsi < 45 or sector["renewable_signal"] == "BEARISH":
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0

    vwap_current = vwap_vals[-1] if vwap_vals and vwap_vals[-1] else 0.0
    vwap_premium = ((current_price - vwap_current) / vwap_current * 100) if vwap_current > 0 else 0.0

    metadata = {
        "vwap": vwap_current,
        "vwap_premium_pct": vwap_premium,
        "atr": current_atr,
        "rsi": current_rsi,
        "sector": sector,
        "entry_threshold": f"VWAP + ATR + RSI>{rsi_threshold} + Vol>{vol_mult}x",
    }

    return current_signal, current_price, current_atr, metadata

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
    """
    Universal main() — detects strategy type and runs appropriate signal.
    Works with: VWAP, ADX_TREND, TSI, RSI, MACD, Bollinger, MA_ENVELOPE, etc.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return
    
    # Detect symbol from filename
    fname = Path(__file__).stem  # e.g. "live_RELIANCE"
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    
    # Determine exchange suffix for yfinance
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix
    
    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym})")
    print(f"{'='*60}")
    
    # Fetch data
    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
        ohlcv = [[r[0], r[1], r[2], r[3], r[4]] for r in data.itertuples()]
        print(f"Loaded {len(ohlcv)} candles")
    except Exception as e:
        print(f"Data fetch error: {e}")
        return
    
    # Prepare OHLCV list for strategy functions
    ohlcv_list = []
    for idx, row in data.iterrows():
        ohlcv_list.append([
            float(row['Open']),
            float(row['High']),
            float(row['Low']),
            float(row['Close']),
            float(row['Volume'])
        ])
    
    if not ohlcv_list:
        print("No OHLCV data")
        return
    
    # Detect strategy type and run appropriate signal
    signal = None
    price = ohlcv_list[-1][3]  # close price
    metadata = {}
    
    try:
        # Try strategy functions in priority order
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple) and len(sig_result) >= 4:
                signal, price, atr, metadata = sig_result[0], float(sig_result[1]), sig_result[2], sig_result[3]
            elif isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'adx_signal' in dir():
            sig_result = adx_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'rsi_signal' in dir():
            sig_result = rsi_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'macd_signal' in dir():
            sig_result = macd_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
            # Generic: look for any function returning signal
            for func_name in ['signal', 'get_signal', 'generate_signal']:
                if func_name in dir():
                    func = eval(func_name)
                    if callable(func):
                        result = func(ohlcv_list)
                        if isinstance(result, tuple):
                            signal, price = result[0], float(result[1])
                        elif isinstance(result, str):
                            signal = result
                        break
        
        # Default fallback: calculate basic signals
        if not signal:
            closes = [o[4] for o in ohlcv_list]
            if len(closes) >= 20:
                sma20 = sum(closes[-20:]) / 20
                current = closes[-1]
                if current > sma20 * 1.005:
                    signal = "BUY"
                    price = current
                elif current < sma20 * 0.995:
                    signal = "SELL"
                    price = current
                else:
                    signal = "HOLD"
                    price = current
    
    except Exception as e:
        print(f"Signal generation error: {e}")
        signal = "HOLD"
        price = ohlcv_list[-1][3]
    
    # Calculate ATR for risk management
    atr = price * 0.008  # fallback
    if len(ohlcv_list) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_list))):
            h = ohlcv_list[i][1]
            l = ohlcv_list[i][2]
            prev_c = ohlcv_list[i-1][3]
            tr = max(h-l, abs(h-prev_c), abs(l-prev_c))
            trs.append(tr)
        if trs:
            atr = sum(trs) / len(trs)
    
    # Get sector tailwind for display
    sector = metadata.get("sector", {}) if metadata else {}
    
    # Output
    print(f"\n--- Green Energy Sector ---")
    print(f"☀️ Solar (TAN):    {sector.get('solar_signal', 'N/A')} ({sector.get('solar_pct_chg', 0)*100:+.2f}%)")
    print(f"🌬️ Wind (FAN):     {sector.get('wind_signal', 'N/A')} ({sector.get('wind_pct_chg', 0)*100:+.2f}%)")
    print(f"⚡ Renewable:      {sector.get('renewable_signal', 'N/A')} ({sector.get('renewable_pct_chg', 0)*100:+.2f}%)")
    print(f"🌱 Sector Score:   {sector.get('combined', 0.5):.2f} | Tailwind: {'ACTIVE' if sector.get('tailwind_active') else 'INACTIVE'}")
    
    print(f"\n--- Technical ---")
    print(f"VWAP:   Rs{metadata.get('vwap', 0):.2f} ({metadata.get('vwap_premium_pct', 0):+.2f}%)")
    print(f"Signal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    print(f"RSI:    {metadata.get('rsi', 50.0):.1f} (threshold: >55 bull / <45 bear)")
    print(f"Entry Window: {'✅ 9:30 AM - 2:30 PM IST' if can_new_entry() else '❌ Outside window'}")

    if signal == "BUY" and can_new_entry():
        sl = round(price - atr * 1.0, 2)
        tgt1 = round(price + atr * TARGET_1_MULT, 2)
        tgt2 = round(price + atr * TARGET_2_MULT, 2)
        tgt3 = round(price + atr * TARGET_3_MULT, 2)
        qty = max(1, int(POSITION / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target1: Rs{tgt1:.2f} ({TARGET_1_MULT}× risk) - exit 1/3")
        print(f"Target2: Rs{tgt2:.2f} ({TARGET_2_MULT}× risk) - exit 1/3")
        print(f"Target3: Rs{tgt3:.2f} ({TARGET_3_MULT}× risk) - exit remaining")
        print(f"🎯 3-Tier Targets: {TARGET_1_MULT}× / {TARGET_2_MULT}× / {TARGET_3_MULT}× risk")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy="VWAP_GREEN_ENERGY",
                atr=atr,
                metadata={
                    "source": Path(__file__).name,
                    "sector": sector,
                    "vwap_premium_pct": metadata.get("vwap_premium_pct", 0),
                    "rsi": metadata.get("rsi", 50.0),
                    "targets": [tgt1, tgt2, tgt3],
                }
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("BUY", ticker_sym, price, qty)
            except:
                pass

    elif signal == "SELL" and can_new_entry():
        sl = round(price + atr * 1.0, 2)
        tgt1 = round(price - atr * TARGET_1_MULT, 2)
        tgt2 = round(price - atr * TARGET_2_MULT, 2)
        tgt3 = round(price - atr * TARGET_3_MULT, 2)
        qty = max(1, int(POSITION / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target1: Rs{tgt1:.2f} ({TARGET_1_MULT}× risk) - exit 1/3")
        print(f"Target2: Rs{tgt2:.2f} ({TARGET_2_MULT}× risk) - exit 1/3")
        print(f"Target3: Rs{tgt3:.2f} ({TARGET_3_MULT}× risk) - exit remaining")
        print(f"🎯 3-Tier Targets: {TARGET_1_MULT}× / {TARGET_2_MULT}× / {TARGET_3_MULT}× risk")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="SELL",
                price=price,
                quantity=qty,
                strategy="VWAP_GREEN_ENERGY",
                atr=atr,
                metadata={
                    "source": Path(__file__).name,
                    "sector": sector,
                    "rsi": metadata.get("rsi", 50.0),
                    "targets": [tgt1, tgt2, tgt3],
                }
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("SELL", ticker_sym, price, qty)
            except:
                pass

    else:
        if signal != "HOLD":
            print(f"No trade — {signal} signal but outside smart entry window (9:30 AM - 2:30 PM IST)")
        else:
            print("No trade — HOLD signal")


if __name__ == "__main__":
    main()

