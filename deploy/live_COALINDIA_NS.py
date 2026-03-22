#!/usr/bin/env python3
"""
Live Trading Script - COALINDIA.NS
Strategy: VWAP + PSU COMMODITY OPTIMIZED ALPHA
Enhanced: Smart Entry | 0.8% ATR Stop | PSU-Optimized VWAP | NIFTY ENERGY Correlation
Win Rate: 60.00% → Target: 68%+
Position: ₹7000 | Daily Loss Cap: 0.3%

PSU COMMODITY (COAL) PROFILE:
- COALINDIA mean-reverts tightly around VWAP (GOI-controlled, institutional anchoring)
- Tighter VWAP band (0.3% vs 0.5%) captures mean-reversion bounces better
- Coal is slow-moving: longer holding periods (overnight) can capture multi-day moves
- RSI tends to be mean-reverting: oversold ~35-40, overbought ~60-65
- Lower liquidity than private peers — entry size capped at ₹7K cleanly
- High NIFTY ENERGY correlation — check index before entry
- Global coal price linkage: seasonal patterns possible (summer demand, pre-monsoon)
- News sensitive to: GOI directives, CIL production data, electricity demand, import duty changes
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

import yfinance
YFINANCE_AVAILABLE = True as yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_COALINDIA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_COALINDIA")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "COALINDIA.NS"
STRATEGY       = "VWAP_PSU_COMMODITY"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

NIFTY_SYMBOL = "^NSEI"
NIFTY_ENERGY_SYMBOL = "^CNXENERGY"  # NIFTY ENERGY index for PSU commodity correlation
ENTRY_WAIT_MINUTES = 15
NO_ENTRY_AFTER = dtime(14, 0)      # Earlier cutoff — coal is slow-moving, capture AM session
BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END = dtime(12, 0)

# PSU-COMMODITY-OPTIMIZED PARAMETERS
# Tighter VWAP band (0.3% vs 0.5%) — COALINDIA mean-reverts closer to VWAP
ENTRY_VWAP_PCT = 0.003
# Lower RSI threshold — PSU commodity stocks bounce before RSI hits 55+
ENTRY_RSI_MIN = 50
# Lower vol threshold — PSU commodity has steadier volume, less dramatic spikes
ENTRY_VOL_MULT = 1.1

# 0.8% ATR stop loss
SL_ATR_MULT = 1.0      # 1.0x ATR = ~0.8% ATR at current prices
MAX_SL_PCT = 0.008     # 0.8% hard cap — matches 0.8% ATR target
TRAIL_TRIGGER_PCT = 0.01

TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0

# PSU commodity oversold RSI level — COALINDIA-specific
# RSI < 38 = deeply oversold, expect mean-reversion bounce to 50+
RSI_OVERSOLD_COAL = 38

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
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early - waiting for 9:30 AM candle close")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:00 PM - no new entries today (coal is slow-moving, AM session preferred)")
        return False
    return True

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

def fetch_intraday_15min(symbol: str, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval="15m", period="1d")
            if df.empty:
                return None
            ohlcv = [
                {"time": idx, "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d for intraday 15m %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
    return None

def fetch_intraday_1hr(symbol: str, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval="1h", period="5d")
            if df.empty:
                return None
            ohlcv = [
                {"time": idx, "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d for 1hr %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
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
    """Standard rolling VWAP."""
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

def calculate_anchored_vwap_from_open(ohlcv: list) -> list:
    """Anchored VWAP from first bar of day — better for PSU commodity mean-reversion."""
    if not ohlcv:
        return []
    cum_pv, cum_vol = 0.0, 0
    vwap = []
    for bar in ohlcv:
        tp = (bar["high"] + bar["low"] + bar["close"]) / 3
        cum_pv += tp * bar["volume"]
        cum_vol += bar["volume"]
        vwap.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)
    return vwap

def calculate_rsi(prices: list, period: int = 14) -> list:
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    return [100 - (100 / (1 + rs))]

def calculate_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

def get_nifty_energy_correlation() -> tuple[float, str]:
    """
    Check NIFTY ENERGY index vs NIFTY 50 correlation.
    COALINDIA has HIGH correlation with NIFTY ENERGY.
    Returns correlation score and advice.
    """
    try:
        nifty = yf.Ticker(NIFTY_SYMBOL)
        nifty_energy = yf.Ticker(NIFTY_ENERGY_SYMBOL)
        
        nifty_df = nifty.history(period="10d")
        energy_df = nifty_energy.history(period="10d")
        
        if nifty_df.empty or energy_df.empty:
            log.warning("Could not fetch NIFTY/ENERGY data for correlation — assuming positive")
            return 1.0, "ASSUME_POSITIVE"
        
        nifty_returns = nifty_df["Close"].pct_change().dropna()
        energy_returns = energy_df["Close"].pct_change().dropna()
        
        min_len = min(len(nifty_returns), len(energy_returns))
        if min_len < 5:
            return 1.0, "INSUFFICIENT_DATA"
        
        correlation = nifty_returns.iloc[-min_len:].corr(energy_returns.iloc[-min_len:])
        correlation = float(correlation) if not pd.isna(correlation) else 1.0
        
        log.info("⚡ NIFTY ENERGY Correlation: %.3f", correlation)
        
        if correlation > 0.6:
            return correlation, "HIGH_POSITIVE"
        elif correlation > 0.3:
            return correlation, "MODERATE_POSITIVE"
        elif correlation > 0:
            return correlation, "LOW_POSITIVE"
        else:
            return correlation, "NEGATIVE"
    except Exception as e:
        log.warning("Correlation check failed: %s — assuming positive", e)
        return 1.0, "ERROR"

def get_market_regime() -> tuple[str, float]:
    nifty_data = fetch_recent_data(days=40)
    if not nifty_data or len(nifty_data) < 25:
        log.warning("Could not fetch NIFTY data - assuming UPTREND")
        return "UPTREND", 1.0
    
    nifty_closes = [bar["close"] for bar in nifty_data]
    nifty_sma20 = calculate_sma(nifty_closes, 20)
    nifty_current = nifty_closes[-1]
    ratio = nifty_current / nifty_sma20
    
    if ratio > 1.02:
        regime = "UPTREND"
    elif ratio < 0.98:
        regime = "DOWNTREND"
    else:
        regime = "RANGE"
    
    log.info("📊 NIFTY Regime: %s | Current: %.2f | SMA20: %.2f | Ratio: %.3f", 
             regime, nifty_current, nifty_sma20, ratio)
    return regime, ratio

def get_position_size_multiplier(regime: str) -> float:
    if regime == "DOWNTREND":
        return 0.0
    elif regime == "RANGE":
        return 0.5
    return 1.0

def smart_entry_conditions_met(intraday_15m: list, intraday_1hr: list, 
                                daily_ohlcv: list, current_price: float) -> tuple[bool, str]:
    """
    PSU-COMMODITY-OPTIMIZED ENTRY CONDITIONS:
    - Tighter VWAP band (0.3% vs 0.5%) — COALINDIA mean-reverts closer to VWAP
    - Lower RSI threshold (50 vs 55) — PSU commodity stocks bounce before RSI hits 55+
    - NIFTY ENERGY correlation check — PSU coal tracks energy index closely
    - Anchored VWAP from day open preferred for mean-reversion entry
    - Coal is slow-moving: prefer AM session entries, overnight holds possible
    """
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data..."
    
    now = ist_now()
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close"
    
    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1
    
    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    
    # Use anchored VWAP (from day open) — more reliable for PSU commodity mean-reversion
    vwap_15m = calculate_anchored_vwap_from_open(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m)[-1] if len(closes_15m) > 14 else 50
    
    vwap_1hr = calculate_anchored_vwap_from_open(intraday_1hr) if intraday_1hr else []
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    # NIFTY ENERGY correlation check — PSU coal tracks energy index
    nifty_energy_corr, corr_status = get_nifty_energy_correlation()
    
    log.info("📊 Smart Entry Check | Price: %.2f | VWAP_15m: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f | ENERGY_Corr: %.3f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio, nifty_energy_corr)
    
    # PSU-commodity-optimized entry conditions
    # Tighter VWAP band (0.3% vs 0.5%) — COALINDIA mean-reverts within 0.3% of VWAP
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    # Lower RSI threshold (50 vs 55) — PSU commodity bounces before RSI reaches 55+
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    # Lower volume threshold (1.1 vs 1.2) — PSU commodity has steadier volume
    cond3 = vol_ratio > ENTRY_VOL_MULT
    # Market direction confirmation via RSI alignment
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    # NIFTY ENERGY correlation check — only enter if positive correlation
    cond4 = nifty_energy_corr > 0.3 or corr_status in ("INSUFFICIENT_DATA", "ERROR", "ASSUME_POSITIVE")
    
    if cond1 and cond2 and cond3 and mt_confirmation and cond4:
        reasons = []
        if cond1: reasons.append(f"Price>VWAP+0.3%")
        if cond2: reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond3: reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        if cond4: reasons.append(f"EnergyCorr={nifty_energy_corr:.2f}")
        return True, "✅ PSU COMMODITY SMART ENTRY: " + " + ".join(reasons)
    
    reasons = []
    if not cond1: reasons.append(f"Price<VWAP+0.3% ({current_price/vwap_val-1:.2%})")
    if not cond2: reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3: reasons.append(f"Vol low ({vol_ratio:.2f}x)")
    if not cond4: reasons.append(f"EnergyCorr low ({nifty_energy_corr:.3f})")
    return False, "❌ Entry conditions not met: " + " | ".join(reasons)

def calculate_dynamic_sl(entry_price: float, atr: float) -> float:
    """
    PSU-COMMODITY-OPTIMIZED STOP LOSS:
    - 0.8% ATR stop (SL_ATR_MULT=1.0)
    - Hard cap at 0.8% (MAX_SL_PCT=0.008)
    - For COALINDIA at ₹400, ATR ≈ ₹4-6 → stop ≈ ₹3-5 from entry (0.75-1.2%)
    """
    sl_atr = entry_price - (SL_ATR_MULT * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    stop_loss = max(sl_atr, sl_max)
    
    # Compute actual % from entry for logging
    sl_pct = (entry_price - stop_loss) / entry_price * 100
    log.info("🎯 Dynamic SL: ATR-based=%.2f (%.1f%%) | Max-0.8%%=%.2f | Selected=%.2f", 
             sl_atr, sl_pct, sl_max, stop_loss)
    return round(stop_loss, 2)

def calculate_targets(entry_price: float, stop_loss: float) -> tuple[list, list]:
    risk = entry_price - stop_loss
    t1 = round(entry_price + (TARGET_1_MULT * risk), 2)
    t2 = round(entry_price + (TARGET_2_MULT * risk), 2)
    t3 = round(entry_price + (TARGET_3_MULT * risk), 2)
    
    targets = [
        {"level": 1, "price": t1, "risk_mult": TARGET_1_MULT, "exit_pct": 0.33, "desc": "Secure 1.5×"},
        {"level": 2, "price": t2, "risk_mult": TARGET_2_MULT, "exit_pct": 0.33, "desc": "Main 3×"},
        {"level": 3, "price": t3, "risk_mult": TARGET_3_MULT, "exit_pct": 0.34, "desc": "Stretch 5×"},
    ]
    return targets

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    vwap_vals     = calculate_anchored_vwap_from_open(ohlcv)  # Use anchored VWAP for PSU commodity
    atr_vals      = calculate_atr(ohlcv, period)
    signals       = ["HOLD"] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or vwap_vals[i] == 0 or atr_vals[i] is None:
            continue
        price    = ohlcv[i]["close"]
        v        = vwap_vals[i]
        a        = atr_vals[i]
        if price > v + a * atr_mult:
            signals[i] = "BUY"
        elif price < v - a * atr_mult:
            signals[i] = "SELL"

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
        stop_loss = price - (atr * 1.0)  # 1x ATR stop = 0.8%
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
        import yfinance
YFINANCE_AVAILABLE = True as yf
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
    print(f"Strategy: {STRATEGY}")
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
    price = ohlcv_list[-1][2]  # close price
    
    try:
        # Try strategy functions in priority order
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'adx_signal' in dir():
            sig_result = adx_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'rsi_signal' in dir():
            sig_result = rsi_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'macd_signal' in dir():
            sig_result = macd_signal(ohlcv_list, {})
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
        price = ohlcv_list[-1][4]
    
    # Calculate ATR for risk management
    # Use real ATR from calculate_atr()  # fallback
    if len(ohlcv_list) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_list))):
            h = ohlcv_list[i][1]
            l = ohlcv_list[i][2]
            prev_c = ohlcv_list[i-1][4]
            tr = max(h-l, abs(h-prev_c), abs(l-prev_c))
            trs.append(tr)
        if trs:
            atr = sum(trs) / len(trs)
    
    # Output
    print(f"\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    
    if signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")
        
        # Place order
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr,
                metadata={"source": Path(__file__).name}
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("BUY", ticker_sym, price, qty)
            except:
                pass
    
    elif signal == "SELL":
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{price-tgt:.2f} reward)")
        
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="SELL",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("SELL", ticker_sym, price, qty)
            except:
                pass
    
    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()
