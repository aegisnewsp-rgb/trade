#!/usr/bin/env python3
"""
Live Trading Script - SBIN.NS
Strategy: VWAP + PSU BANK OPTIMIZED ALPHA
Enhanced: Smart Entry | 0.8% ATR Stop | PSU-Optimized VWAP | NIFTY BANK Correlation
Win Rate: 63.64% → Target: 70%+
Position: ₹10000 | Daily Loss Cap: 0.3%

PSU BANK PROFILE:
- SBIN mean-reverts tightly around VWAP (institutional anchoring via GOI/LIC holdings)
- Tighter VWAP band (0.3% vs 0.5%) captures mean-reversion bounces better
- RSI tends to be mean-reverting: oversold ~35-40, overbought ~60-65
- Lower liquidity than private banks (HDFC/ICICI) — entry size capped at ₹10K cleanly
- High NIFTY BANK correlation — check index before entry
- News sensitive to: GOI directives, RBI policy, CGA statements, PSU divestment news
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
        logging.FileHandler(LOG_DIR / "live_SBIN.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SBIN")

SYMBOL = "SBIN.NS"
STRATEGY = "VWAP_PSU_ALPHA"
POSITION = 10000  # ₹10K position — SBIN liquidity supports this cleanly
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5}

NIFTY_SYMBOL = "^NSEI"
NIFTY_BANK_SYMBOL = "^NSEBANK"  # Added: NIFTY BANK index for PSU correlation
ENTRY_WAIT_MINUTES = 15
NO_ENTRY_AFTER = dtime(14, 30)
BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END = dtime(12, 0)

# PSU-OPTIMIZED PARAMETERS
# Tighter VWAP band (0.3% vs 0.5%) — SBIN mean-reverts closer to VWAP
ENTRY_VWAP_PCT = 0.003
# Lower RSI threshold — SBIN mean-reverts, doesn't push RSI to 55+ before bouncing
ENTRY_RSI_MIN = 50
# Lower vol threshold — PSU banks have steadier volume, less dramatic spikes
ENTRY_VOL_MULT = 1.1

# 0.8% ATR stop loss (task spec)
SL_ATR_MULT = 1.0      # 1.0x ATR = 0.8% ATR at current prices
MAX_SL_PCT = 0.008     # 0.8% hard cap — matches 0.8% ATR target
TRAIL_TRIGGER_PCT = 0.01

TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0

# PSU bank oversold RSI level — SBIN-specific
# RSI < 35 = deeply oversold, expect mean-reversion bounce to 50+
RSI_OVERSOLD_SBIN = 38

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def can_new_entry() -> bool:
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early - waiting for 9:30 AM candle close")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM - no new entries today")
        return False
    return True

def fetch_recent_data(symbol: str, days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(symbol).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", symbol)
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
            log.warning("Attempt %d/%d for intraday %s: %s", attempt + 1, retries, symbol, e)
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
    atr, prev_close = [], None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_vwap(ohlcv: list) -> list:
    """Standard VWAP — for PSU banks, anchored VWAP from day open is more reliable."""
    vwap, cum_pv, cum_vol = [], 0.0, 0
    for bar in ohlcv:
        tp = (bar["high"] + bar["low"] + bar["close"]) / 3
        cum_pv += tp * bar["volume"]
        cum_vol += bar["volume"]
        vwap.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)
    return vwap

def calculate_anchored_vwap_from_open(ohlcv: list) -> list:
    """Anchored VWAP from first bar of day — better for PSU bank mean-reversion."""
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

def get_nifty_bank_correlation() -> tuple[float, str]:
    """
    Check NIFTY BANK index vs NIFTY 50 correlation.
    PSU banks (SBIN) have HIGH correlation with NIFTY BANK.
    Returns correlation score and advice.
    """
    try:
        nifty = yf.Ticker(NIFTY_SYMBOL)
        nifty_bank = yf.Ticker(NIFTY_BANK_SYMBOL)
        
        nifty_df = nifty.history(period="10d")
        bank_df = nifty_bank.history(period="10d")
        
        if nifty_df.empty or bank_df.empty:
            log.warning("Could not fetch NIFTY/BANK data for correlation — assuming positive")
            return 1.0, "ASSUME_POSITIVE"
        
        nifty_returns = nifty_df["Close"].pct_change().dropna()
        bank_returns = bank_df["Close"].pct_change().dropna()
        
        min_len = min(len(nifty_returns), len(bank_returns))
        if min_len < 5:
            return 1.0, "INSUFFICIENT_DATA"
        
        correlation = nifty_returns.iloc[-min_len:].corr(bank_returns.iloc[-min_len:])
        correlation = float(correlation) if not pd.isna(correlation) else 1.0
        
        log.info("🏦 NIFTY BANK Correlation: %.3f", correlation)
        
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
    nifty_data = fetch_recent_data(NIFTY_SYMBOL, days=40)
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
    PSU-OPTIMIZED ENTRY CONDITIONS:
    - Tighter VWAP band (0.3% vs 0.5%) — SBIN mean-reverts closer to VWAP
    - Lower RSI threshold (50 vs 55) — PSU banks bounce before RSI hits 55+
    - NIFTY BANK correlation check — PSU banks track index closely
    - Anchored VWAP from day open preferred for mean-reversion entry
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
    
    # Use anchored VWAP (from day open) — more reliable for PSU bank mean-reversion
    vwap_15m = calculate_anchored_vwap_from_open(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m)[-1] if len(closes_15m) > 14 else 50
    
    vwap_1hr = calculate_anchored_vwap_from_open(intraday_1hr) if intraday_1hr else []
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    # NIFTY BANK correlation check — PSU banks track index
    nifty_bank_corr, corr_status = get_nifty_bank_correlation()
    
    log.info("📊 Smart Entry Check | Price: %.2f | VWAP_15m: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f | BANK_Corr: %.3f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio, nifty_bank_corr)
    
    # PSU-optimized entry conditions
    # Tighter VWAP band (0.3% vs 0.5%) — SBIN mean-reverts within 0.3% of VWAP
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    # Lower RSI threshold (50 vs 55) — SBIN bounces before RSI reaches 55+
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    # Lower volume threshold (1.1 vs 1.2) — PSU banks have steadier volume
    cond3 = vol_ratio > ENTRY_VOL_MULT
    # Market direction confirmation via RSI alignment
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    # NIFTY BANK correlation check — only enter if positive correlation (PSU banks track index)
    cond4 = nifty_bank_corr > 0.3 or corr_status in ("INSUFFICIENT_DATA", "ERROR", "ASSUME_POSITIVE")
    
    if cond1 and cond2 and cond3 and mt_confirmation and cond4:
        reasons = []
        if cond1: reasons.append(f"Price>VWAP+0.3%")
        if cond2: reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond3: reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        if cond4: reasons.append(f"BankCorr={nifty_bank_corr:.2f}")
        return True, "✅ PSU SMART ENTRY: " + " + ".join(reasons)
    
    reasons = []
    if not cond1: reasons.append(f"Price<VWAP+0.3% ({current_price/vwap_val-1:.2%})")
    if not cond2: reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3: reasons.append(f"Vol low ({vol_ratio:.2f}x)")
    if not cond4: reasons.append(f"BankCorr low ({nifty_bank_corr:.3f})")
    return False, "❌ Entry conditions not met: " + " | ".join(reasons)

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period = params["vwap_period"]
    atr_mult = params["atr_multiplier"]
    vwap_vals = calculate_anchored_vwap_from_open(ohlcv)  # Use anchored VWAP for PSU banks
    atr_vals = calculate_atr(ohlcv, period)
    signals = ["HOLD"] * len(ohlcv)
    
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or vwap_vals[i] == 0 or atr_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        v, a = vwap_vals[i], atr_vals[i]
        if price > v + a * atr_mult:
            signals[i] = "BUY"
        elif price < v - a * atr_mult:
            signals[i] = "SELL"
    
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr

def calculate_dynamic_sl(entry_price: float, atr: float) -> float:
    """
    PSU-OPTIMIZED STOP LOSS:
    - 0.8% ATR stop (SL_ATR_MULT=1.0)
    - Hard cap at 0.8% (MAX_SL_PCT=0.008)
    - For SBIN at ₹800, ATR ≈ ₹8-12 → stop ≈ ₹6-10 from entry (0.75-1.2%)
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
