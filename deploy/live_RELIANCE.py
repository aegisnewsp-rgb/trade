#!/usr/bin/env python3
"""
Live Trading Script - RELIANCE.NS
Strategy: TSI (True Strength Index) + ADVANCED ALPHA
Enhanced: Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime Filter
Win Rate: 63.64% → Target: 70%+
Position: ₹7000 | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests

import sys
from pathlib import Path
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
        logging.FileHandler(LOG_DIR / "live_RELIANCE.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_RELIANCE")

SYMBOL = "RELIANCE.NS"
STRATEGY = "TSI_ALPHA"
POSITION = 7000
DAILY_LOSS_CAP = 0.003
PARAMS = {"fast_period": 13, "slow_period": 25, "signal_period": 13}

# ADVANCED ALPHA CONFIG
NIFTY_SYMBOL = "^NSEI"  # NIFTY 50 index
ENTRY_WAIT_MINUTES = 15  # Wait for 9:30 AM candle close
NO_ENTRY_AFTER = dtime(14, 30)  # 2:30 PM IST - no new entries
BEST_ENTRY_START = dtime(9, 30)  # Best entry window start
BEST_ENTRY_END = dtime(12, 0)    # Best entry window end

# Smart Entry thresholds
ENTRY_VWAP_PCT = 0.005    # price > VWAP + 0.5%
ENTRY_RSI_MIN = 55         # RSI > 55
ENTRY_VOL_MULT = 1.2      # volume > 1.2x 20-day avg

# Dynamic Stop Loss
SL_ATR_MULT = 1.5         # stop = entry - (1.5 × ATR)
MAX_SL_PCT = 0.02         # never more than 2% from entry
TRAIL_TRIGGER_PCT = 0.01  # trail to breakeven when 1% in favor

# Target Management (3-tier)
TARGET_1_MULT = 1.5       # 1.5× risk → exit 1/3
TARGET_2_MULT = 3.0       # 3× risk → exit 1/3
TARGET_3_MULT = 5.0       # 5× risk → exit remaining 1/3

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def can_new_entry() -> bool:
    """TIME FILTER: No entries after 2:30 PM or in first 15 minutes"""
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
    """Fetch 15-minute intraday data for today"""
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
    """Fetch 1-hour intraday data for today"""
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
    """VWAP using cumulative typical price × volume"""
    vwap, cum_pv, cum_vol = [], 0.0, 0
    for bar in ohlcv:
        tp = (bar["high"] + bar["low"] + bar["close"]) / 3
        cum_pv += tp * bar["volume"]
        cum_vol += bar["volume"]
        vwap.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)
    return vwap

def calculate_rsi(prices: list, period: int = 14) -> list:
    """RSI calculation"""
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
    """Simple Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

def get_market_regime() -> tuple[str, float]:
    """
    MARKET REGIME FILTER: Check NIFTY trend
    Returns: (regime, nifty_sma_ratio)
    UPTREND: NIFTY > 20-day SMA
    DOWNTREND: NIFTY < 20-day SMA
    RANGE: Within 2% of SMA
    """
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
    """RANGE: reduce position by 50%, DOWNTREND: no new entries"""
    if regime == "DOWNTREND":
        return 0.0  # No new entries
    elif regime == "RANGE":
        return 0.5  # 50% size
    return 1.0  # Full size in UPTREND

def smart_entry_conditions_met(intraday_15m: list, intraday_1hr: list, 
                                daily_ohlcv: list, current_price: float) -> tuple[bool, str]:
    """
    SMART ENTRY: Wait for first 15min candle close (9:30 AM)
    Entry if: price > VWAP + 0.5% AND RSI > 55 AND volume > 1.2x 20-day avg
    Multi-timeframe: 15min + 1hr must agree
    """
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data..."
    
    # Check if first 15min candle (9:15-9:30) has closed
    first_candle = intraday_15m[0]
    candle_close_time = first_candle["time"].to_pydatetime() if hasattr(first_candle["time"], 'to_pydatetime') else first_candle["time"]
    
    # Need at least one completed 15min candle after 9:15
    now = ist_now()
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close"
    
    # Calculate 20-day average volume
    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1
    
    # Current volume (today)
    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    
    # VWAP on 15min
    vwap_15m = calculate_vwap(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    # RSI on 15min
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m)[-1] if len(closes_15m) > 14 else 50
    
    # VWAP on 1hr
    vwap_1hr = calculate_vwap(intraday_1hr) if intraday_1hr else []
    vwap_val_1hr = vwap_1hr[-1] if vwap_1hr else current_price
    
    # RSI on 1hr
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    log.info("📊 Smart Entry Check | Price: %.2f | VWAP_15m: %.2f (need +0.5%%) | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio)
    
    # Condition 1: Price > VWAP + 0.5%
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    
    # Condition 2: RSI > 55 (both timeframes should agree)
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5  # Allow 5 buffer for 1hr
    
    # Condition 3: Volume > 1.2x 20-day avg
    cond3 = vol_ratio > ENTRY_VOL_MULT
    
    # Multi-timeframe agreement
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    
    if cond1 and cond2 and cond3 and mt_confirmation:
        reasons = []
        if cond1: reasons.append(f"Price>VWAP+0.5%")
        if cond2: reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond3: reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        return True, "✅ SMART ENTRY: " + " + ".join(reasons)
    
    reasons = []
    if not cond1: reasons.append(f"Price<VWAP+0.5% ({current_price/vwap_val-1:.2%})")
    if not cond2: reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3: reasons.append(f"Vol low ({vol_ratio:.2f}x)")
    return False, "❌ Entry conditions not met: " + " | ".join(reasons)

def tsi_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """TSI strategy signal"""
    fast, slow, sig_p = params["fast_period"], params["slow_period"], params["signal_period"]
    closes = [bar["close"] for bar in ohlcv]
    momentum = [0.0] + [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result
    
    if len(momentum) <= slow:
        return "HOLD", closes[-1], 0.0
    
    abs_momentum = [abs(m) for m in momentum]
    ema_abs = ema(abs_momentum, slow)
    ema_mom = ema(momentum, slow)
    tsi = [0.0] * len(closes)
    for i in range(slow - 1, len(closes)):
        if ema_abs[i] != 0:
            tsi[i] = 100.0 * ema_mom[i] / ema_abs[i]
    
    signal_ema = ema(tsi, sig_p)
    
    if len(tsi) < 2 or len(signal_ema) < 2:
        return "HOLD", closes[-1], 0.0
    
    if tsi[-2] <= signal_ema[-2] and tsi[-1] > signal_ema[-1]:
        signal = "BUY"
    elif tsi[-2] >= signal_ema[-2] and tsi[-1] < signal_ema[-1]:
        signal = "SELL"
    else:
        signal = "HOLD"
    
    atr = calculate_atr(ohlcv)
    current_atr = atr[-1] if atr and atr[-1] is not None else 0.0
    return signal, closes[-1], current_atr

def calculate_dynamic_sl(entry_price: float, atr: float) -> float:
    """
    DYNAMIC STOP LOSS: ATR-based
    stop = entry - (1.5 × ATR)
    Maximum stop: never more than 2% from entry
    """
    sl_atr = entry_price - (SL_ATR_MULT * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    # Use whichever is tighter (more conservative)
    stop_loss = max(sl_atr, sl_max)  # Tighter stop
    log.info("🎯 Dynamic SL: ATR-based=%.2f | Max-2%%=%.2f | Selected=%.2f", sl_atr, sl_max, stop_loss)
    return round(stop_loss, 2)

def calculate_targets(entry_price: float, stop_loss: float) -> tuple[list, list]:
    """
    TARGET MANAGEMENT (3-tier):
    Target 1: 1.5× risk → exit 1/3 position
    Target 2: 3× risk → exit 1/3 position  
    Target 3: 5× risk → exit remaining 1/3
    """
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

def log_signal(signal: str, price: float, atr: float, targets: list = None, regime: str = "UNKNOWN"):
    log_file = LOG_DIR / "signals_RELIANCE.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entry = {"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY,
             "signal": signal, "price": round(price, 4), "atr": round(atr, 4),
             "regime": regime}
    if targets:
        entry["targets"] = [{"t"+str(t["level"]): t["price"]} for t in targets]
    entries.append(entry)
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_RELIANCE.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception:
            pass
    return False

def main():
    log.info("=" * 70)
    log.info("🚀 ADVANCED ALPHA - RELIANCE.NS | TSI Strategy Enhanced")
    log.info("   Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime")
    log.info("=" * 70)
    
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)
    
    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return
    
    today_str = ist_now().strftime("%Y-%m-%d")
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return
    
    # STEP 1: Check Market Regime
    log.info("\n📊 [STEP 1] Checking Market Regime (NIFTY)...")
    regime, regime_ratio = get_market_regime()
    pos_mult = get_position_size_multiplier(regime)
    
    if regime == "DOWNTREND":
        log.warning("🔴 DOWNTREND - No new entries. Will hold existing positions only.")
        # Continue to monitor existing but don't enter new
    
    log.info("Market is open. Fetching data...")
    
    # STEP 2: Fetch data
    daily_ohlcv = fetch_recent_data(SYMBOL, days=90)
    if not daily_ohlcv or len(daily_ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return
    
    intraday_15m = fetch_intraday_15min(SYMBOL)
    intraday_1hr = fetch_intraday_1hr(SYMBOL)
    
    # STEP 3: Get base signal from TSI
    signal, price, atr = tsi_signal(daily_ohlcv, PARAMS)
    log.info("\n📊 [STEP 2] TSI Signal: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)
    
    # STEP 4: Smart Entry Check (only for BUY signals)
    entry_allowed = True
    entry_reason = ""
    
    if signal == "BUY" and pos_mult > 0:
        if not can_new_entry():
            entry_allowed = False
            entry_reason = "Time filter blocked entry"
        else:
            entry_allowed, entry_reason = smart_entry_conditions_met(
                intraday_15m, intraday_1hr, daily_ohlcv, price)
    
    if signal == "BUY" and not entry_allowed:
        log.info("🚫 SMART ENTRY BLOCKED: %s", entry_reason)
        signal = "HOLD"
    
    # STEP 5: Calculate Dynamic Stop & Targets
    stop_loss = 0.0
    targets = []
    
    if signal == "BUY" and entry_allowed:
        stop_loss = calculate_dynamic_sl(price, atr)
        targets = calculate_targets(price, stop_loss)
        log.info("\n🎯 [STEP 3] Dynamic Stop Loss: ₹%.2f", stop_loss)
        log.info("🎯 [STEP 4] Target Management:")
        for t in targets:
            log.info("   Target %d: ₹%.2f (%.1f× risk, exit %.0f%%)", 
                     t["level"], t["price"], t["risk_mult"], t["exit_pct"] * 100)
    
    # Position sizing
    adjusted_position = int(POSITION * pos_mult)
    quantity = max(1, int(adjusted_position / price))
    
    log.info("\n" + "=" * 70)
    log.info("  SYMBOL      : %s", SYMBOL)
    log.info("  STRATEGY    : %s", STRATEGY)
    log.info("  SIGNAL      : ★ %s ★", signal)
    log.info("  REGIME      : %s (size mult: %.0f%%)", regime, pos_mult * 100)
    log.info("  SMART ENTRY : %s", entry_reason if signal == "HOLD" else "PASSED")
    log.info("  PRICE       : ₹%.2f", price)
    log.info("  QTY         : %d shares (₹%d position)", quantity, adjusted_position)
    log.info("  ATR          : %.4f", atr)
    if stop_loss > 0:
        log.info("  STOP LOSS   : ₹%.2f  (%.1f%% from entry)", stop_loss, (price - stop_loss) / price * 100)
        log.info("  TARGETS     : T1=₹%.2f | T2=₹%.2f | T3=₹%.2f", 
                 targets[0]["price"], targets[1]["price"], targets[2]["price"])
    log.info("=" * 70)
    
    log_signal(signal, price, atr, targets, regime)
    
    if signal != "HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.warning("⚠ Groww order could not be placed – signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials – paper mode (signal logged).")

def place_groww_order(symbol, signal, quantity, price):
    """
    Emit trading signal to queue for Master Orchestrator.
    Orchestrator coalesces all signals and places orders via Groww API
    (single connection = no rate limiting across 468 scripts).
    Paper mode: orchestrator prints signals instead of placing.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from signals.schema import emit_signal
        # Get ATR from script's atr variable if available
        _atr = price * 0.008
        try:
            if 'atr' in globals() and isinstance(globals().get('atr'), (int, float)):
                _atr = float(globals()['atr'])
        except:
            _atr = price * 0.008
        _strategy = str(globals().get('STRATEGY_NAME', 'VWAP'))
        emit_signal(
            symbol=symbol, signal=signal, price=price,
            quantity=quantity, strategy=_strategy, atr=_atr,
            metadata={"source": Path(__file__).name}
        )
        return {"status": "queued", "symbol": symbol, "signal": signal}
    except ImportError:
        print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
        return {"status": "paper", "symbol": symbol, "signal": signal}


def place_order(symbol, signal, quantity, price):
    return place_groww_order(symbol, signal, quantity, price)

if __name__ == "__main__":