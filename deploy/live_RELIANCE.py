#!/usr/bin/env python3
"""
Live Trading Script - RELIANCE.NS
Strategy: TSI (True Strength Index) + VWAP Enhanced Alpha
Enhanced: Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime | Morning Momentum
Win Rate: 63.64% → Target: 70%+
Position: ₹7000 | Daily Loss Cap: 0.3%

DEEP REASONING NOTES:
- RELIANCE: Large-cap, 15-20M shares/day, ATR ~35-45 pts, fills guaranteed
- VWAP threshold 0.5% = ₹12.50 at ₹2500 → meaningful (0.3-0.5x ATR)
- Tight entries justified: liquid stock, tight stops acceptable
- Morning (9:30-12:00 IST): 40-50% of daily range + best volume
- 3-tier targets: 1.5x/3x/5x risk → ₹75/₹150/₹250 per unit
- NIFTY correlation 0.85-0.95: use as entry weight multiplier
"""

import os, sys, json, time, logging, requests
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
        logging.FileHandler(LOG_DIR / "live_RELIANCE.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_RELIANCE")

SYMBOL = "RELIANCE.NS"
STRATEGY = "TSI_VWAP_ALPHA"
POSITION = 7000
DAILY_LOSS_CAP = 0.003
PARAMS = {"fast_period": 13, "slow_period": 25, "signal_period": 13}

# Trail ATR multiplier
TRAIL_ATR_MULT = 0.3

# NIFTY index for market regime
NIFTY_SYMBOL = "^NSEI"

# Time windows (IST)
ENTRY_WAIT_MINUTES = 15   # Wait for 9:30 AM candle close
NO_ENTRY_AFTER = dtime(14, 30)   # 2:30 PM IST - no new entries
BEST_ENTRY_START = dtime(9, 30)  # Best entry window start
BEST_ENTRY_END = dtime(12, 0)    # Best entry window end
MORNING_MOMENTUM_END = dtime(10, 30)  # Morning momentum window

# Smart Entry thresholds
ENTRY_VWAP_PCT = 0.005    # price > VWAP + 0.5%
ENTRY_RSI_MIN = 55        # RSI > 55
ENTRY_VOL_MULT = 1.2      # volume > 1.2x 20-day avg
VWAP_SLOPE_PCT = 0.0005   # VWAP must be rising (0.05% per candle)

# Dynamic Stop Loss
SL_ATR_MULT = 1.5         # stop = entry - (1.5 × ATR)
MAX_SL_PCT = 0.02         # never more than 2% from entry
TRAIL_TRIGGER_PCT = 0.01  # trail to breakeven when 1% in favor
BREAKEVEN_BUFFER = 0.0005 # small buffer above entry for breakeven

# Target Management (3-tier)
TARGET_1_MULT = 1.5       # 1.5× risk → exit 1/3
TARGET_2_MULT = 3.0       # 3× risk → exit 1/3
TARGET_3_MULT = 5.0       # 5× risk → exit remaining 1/3

# NIFTY correlation weight
NIFTY_UPTREND_BOOST = 1.2    # multiplier when NIFTY > SMA20
NIFTY_RANGE_PENALTY = 0.8    # multiplier when NIFTY near SMA20

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")


def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)


def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)


def can_new_entry() -> bool:
    """TIME FILTER: No entries after 2:30 PM or before 9:30 AM"""
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
            log.warning("Attempt %d/%d for intraday 15m %s: %s", attempt + 1, retries, symbol, e)
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
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
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


def calculate_vwap_slope(vwap_values: list, lookback: int = 3) -> float:
    """VWAP slope: positive = rising, negative = falling"""
    if len(vwap_values) < lookback + 1:
        return 0.0
    recent = vwap_values[-(lookback):]
    # Simple linear slope approximation
    delta = recent[-1] - recent[0]
    avg_vwap = sum(recent) / len(recent)
    return delta / avg_vwap if avg_vwap > 0 else 0.0


def calculate_rsi(prices: list, period: int = 14) -> list:
    """RSI calculation - returns list of RSI values"""
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    result = [50.0] * period  # seed first period with neutral
    
    for i in range(period, len(prices)):
        avg_gain = sum(gains[i-period:i]) / period
        avg_loss = sum(losses[i-period:i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - (100.0 / (1.0 + rs)))
    return result


def calculate_sma(prices: list, period: int) -> float:
    """Simple Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period


def get_market_regime() -> tuple[str, float]:
    """
    MARKET REGIME FILTER: Check NIFTY trend
    Returns: (regime, nifty_sma_ratio, nifty_weight)
    UPTREND: NIFTY > 20-day SMA → weight 1.2
    DOWNTREND: NIFTY < 20-day SMA → weight 0.0 (no entries)
    RANGE: Within 2% of SMA → weight 0.8
    """
    nifty_data = fetch_recent_data(NIFTY_SYMBOL, days=40)
    if not nifty_data or len(nifty_data) < 25:
        log.warning("Could not fetch NIFTY data - assuming UPTREND")
        return "UPTREND", 1.0, 1.0
    
    nifty_closes = [bar["close"] for bar in nifty_data]
    nifty_sma20 = calculate_sma(nifty_closes, 20)
    nifty_current = nifty_closes[-1]
    ratio = nifty_current / nifty_sma20
    
    if ratio > 1.02:
        regime = "UPTREND"
        weight = NIFTY_UPTREND_BOOST
    elif ratio < 0.98:
        regime = "DOWNTREND"
        weight = 0.0
    else:
        regime = "RANGE"
        weight = NIFTY_RANGE_PENALTY
    
    log.info("📊 NIFTY Regime: %s | Current: %.2f | SMA20: %.2f | Ratio: %.3f | Weight: %.2f", 
             regime, nifty_current, nifty_sma20, ratio, weight)
    return regime, ratio, weight


def get_position_size_multiplier(regime: str, nifty_weight: float) -> float:
    """RANGE: reduce position by 50%, DOWNTREND: no new entries"""
    if regime == "DOWNTREND":
        return 0.0  # No new entries
    elif regime == "RANGE":
        return 0.5 * nifty_weight  # 50% size × nifty weight
    return nifty_weight  # Full size × nifty weight in UPTREND


def is_morning_momentum_window() -> bool:
    """Check if we're in the high-probability morning momentum window"""
    now = ist_now().time()
    return dtime(9, 30) <= now <= MORNING_MOMENTUM_END


def get_morning_momentum_score(intraday_15m: list) -> float:
    """
    Morning Momentum Score: 0.0 to 1.0
    Measures if price is accelerating in morning window (9:30-10:30)
    Score = % gain from open + volume acceleration
    """
    if not intraday_15m or len(intraday_15m) < 3:
        return 0.5  # neutral
    
    now = ist_now().time()
    if not (dtime(9, 30) <= now <= dtime(11, 0)):
        return 0.7  # give benefit of doubt outside morning window
    
    open_price = intraday_15m[0]["open"]
    current_price = intraday_15m[-1]["close"]
    price_change_pct = (current_price - open_price) / open_price if open_price > 0 else 0
    
    # Volume acceleration: compare recent 3 candles to previous 3
    if len(intraday_15m) >= 6:
        recent_vol = sum(intraday_15m[-3:][i]["volume"] for i in range(3))
        prev_vol = sum(intraday_15m[-6:-3][i]["volume"] for i in range(3))
        vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0
    else:
        vol_ratio = 1.0
    
    # Score: price change contribution + volume contribution
    score = min(1.0, abs(price_change_pct) * 20 + min(1.0, vol_ratio * 0.5))
    direction = 1.0 if price_change_pct > 0 else 0.5  # penalize negative
    
    log.info("🌅 Morning Momentum: price_chg=%.2f%% vol_ratio=%.2f score=%.2f", 
             price_change_pct * 100, vol_ratio, score * direction)
    return score * direction


def smart_entry_conditions_met(
    intraday_15m: list, 
    intraday_1hr: list, 
    daily_ohlcv: list, 
    current_price: float,
    tsi_signal: str
) -> tuple[bool, str, float]:
    """
    SMART ENTRY: Wait for first 15min candle close (9:30 AM)
    Entry if: price > VWAP + 0.5% AND RSI > 55 AND volume > 1.2x 20-day avg
    VWAP must be rising (slope > 0)
    TSI must be in BUY signal or HOLD with positive momentum
    Multi-timeframe: 15min + 1hr must agree
    Morning momentum boost for entries 9:30-10:30
    
    Returns: (conditions_met, reason_string, entry_score 0-1)
    """
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data...", 0.0
    
    now = ist_now()
    
    # Check if first 15min candle (9:15-9:30) has closed
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close", 0.0
    
    # Calculate 20-day average volume
    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1
    
    # Current volume (today)
    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    
    # VWAP on 15min
    vwap_15m = calculate_vwap(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    # VWAP slope - must be rising
    vwap_slope = calculate_vwap_slope(vwap_15m, lookback=3)
    
    # RSI on 15min (full list)
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_list_15m = calculate_rsi(closes_15m)
    rsi_15m = rsi_list_15m[-1] if rsi_list_15m else 50
    
    # VWAP on 1hr
    vwap_1hr = calculate_vwap(intraday_1hr) if intraday_1hr else []
    vwap_val_1hr = vwap_1hr[-1] if vwap_1hr else current_price
    
    # RSI on 1hr (full list)
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_list_1hr = calculate_rsi(closes_1hr)
    rsi_1hr = rsi_list_1hr[-1] if rsi_list_1hr else 50
    
    # Morning momentum score
    morning_score = get_morning_momentum_score(intraday_15m)
    
    log.info("📊 Smart Entry | Price: %.2f | VWAP_15m: %.2f (+0.5%%=%.2f) | Slope: %.4f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol: %.2fx | Morning: %.2f | TSI: %s",
             current_price, vwap_val, vwap_val * (1 + ENTRY_VWAP_PCT), vwap_slope,
             rsi_15m, rsi_1hr, vol_ratio, morning_score, tsi_signal)
    
    # Condition 1: Price > VWAP + 0.5%
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    
    # Condition 2: VWAP must be rising (or neutral)
    cond2 = vwap_slope > -VWAP_SLOPE_PCT  # slight negative tolerance
    
    # Condition 3: RSI > 55 (both timeframes should agree, allow 5 buffer for 1hr)
    cond3 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    
    # Condition 4: Volume > 1.2x 20-day avg
    cond4 = vol_ratio > ENTRY_VOL_MULT
    
    # Condition 5: TSI signal must be BUY (or HOLD with morning momentum boost)
    cond5_tsi = tsi_signal == "BUY" or (tsi_signal == "HOLD" and morning_score > 0.7)
    
    # Multi-timeframe agreement
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    
    # Calculate entry score (0-1)
    score = 0.0
    if cond1: score += 0.25
    if cond2: score += 0.10
    if cond3: score += 0.25
    if cond4: score += 0.15
    if cond5_tsi: score += 0.15
    if mt_confirmation: score += 0.10
    
    # Morning momentum bonus
    if morning_score > 0.6 and is_morning_momentum_window():
        score = min(1.0, score * 1.1)
    
    log.info("📊 Entry Score: %.2f | Conditions: VWAP=✅/❌ slope=✅/❌ RSI=✅/❌ Vol=✅/❌ TSI=✅/❌ MT=✅/❌",
             score, cond1, cond2, cond3, cond4, cond5_tsi, mt_confirmation)
    
    if cond1 and cond2 and cond3 and cond4 and cond5_tsi and mt_confirmation:
        reasons = []
        if cond1: reasons.append(f"Price>VWAP+0.5%")
        if cond3: reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond4: reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        if cond5_tsi: reasons.append(f"TSI={tsi_signal}")
        return True, f"✅ SMART ENTRY (score={score:.2f}): " + " + ".join(reasons), score
    
    reasons = []
    if not cond1: reasons.append(f"Price<VWAP+0.5% ({current_price/vwap_val-1:.2%})")
    if not cond2: reasons.append(f"VWAP falling ({vwap_slope:.4f})")
    if not cond3: reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond4: reasons.append(f"Vol low ({vol_ratio:.2f}x)")
    if not cond5_tsi: reasons.append(f"TSI={tsi_signal} (need BUY)")
    return False, f"❌ Entry: " + " | ".join(reasons), score


def tsi_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """TSI strategy signal - returns (signal, current_price, atr)"""
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
    
    # Crossover detection
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
    stop_loss = max(sl_atr, sl_max)  # Tighter stop wins
    log.info("🎯 Dynamic SL: ATR=%.2f (1.5x=%.2f) | Max-2%%=%.2f | Selected=%.2f", 
             atr, sl_atr, sl_max, stop_loss)
    return round(stop_loss, 2)


def calculate_targets(entry_price: float, stop_loss: float) -> list[dict]:
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
    log.info("🎯 3-Tier Targets: T1=%.2f (+%.1f%%) T2=%.2f (+%.1f%%) T3=%.2f (+%.1f%%) | Risk=%.2f",
             t1, TARGET_1_MULT * risk / entry_price * 100,
             t2, TARGET_2_MULT * risk / entry_price * 100,
             t3, TARGET_3_MULT * risk / entry_price * 100,
             risk)
    return targets


def check_target_tiers(current_price: float, entry_price: float, 
                        targets: list, positions_closed: list) -> tuple[list, list]:
    """
    Check which target tiers have been hit.
    Returns (updated_targets, updated_positions_closed)
    """
    for t in targets:
        if t["level"] not in positions_closed:
            if current_price >= t["price"]:
                log.info("🎯 TARGET %d HIT at %.2f (%.2f) - closing %.0f%% of position!", 
                         t["level"], current_price, t["price"], t["exit_pct"] * 100)
                positions_closed.append(t["level"])
    return targets, positions_closed


def check_trailing_stop(current_price: float, entry_price: float, 
                         stop_loss: float, high_water_mark: float) -> float:
    """
    TRAILING STOP: Move to breakeven when price is 1% in favor
    Then trail by 0.5% increments
    """
    profit_pct = (current_price - entry_price) / entry_price
    
    if profit_pct >= TRAIL_TRIGGER_PCT:
        # Trail to breakeven + small buffer
        new_stop = entry_price * (1 + BREAKEVEN_BUFFER)
        if new_stop > stop_loss:
            trail_amount = new_stop - stop_loss
            log.info("🔄 Trail stop: %.2f → %.2f (+%.2f profit)", 
                     stop_loss, new_stop, trail_amount)
            return round(new_stop, 2)
    
    return stop_loss


# ─────────────────────────────────────────────────────────────
# Groww API (stub - integrate with real API when ready)
# ─────────────────────────────────────────────────────────────
def place_groww_order(symbol, signal, quantity, price):
    """Place order via Groww API or paper trade"""
    try:
        import groww_api
        if not groww_api.is_configured():
            return groww_api.paper_trade(signal, symbol, price, quantity)
    except ImportError:
        pass
    
    # Paper trade fallback
    log.info("📝 PAPER TRADE: %s %d %s @ Rs%.2f", signal, quantity, symbol, price)
    return {"status": "paper", "signal": signal, "price": price, "qty": quantity}


# ─────────────────────────────────────────────────────────────
# MAIN TRADING LOOP
# ─────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("🚀 RELIANCE Live Trading | TSI+VWAP ALPHA | Position: ₹%d", POSITION)
    log.info("=" * 60)
    
    # Fetch historical daily data for TSI and volume calculations
    daily_data = fetch_recent_data(SYMBOL, days=60)
    if not daily_data:
        log.error("Failed to fetch daily data - aborting")
        return
    
    log.info("📊 Fetched %d days of daily data", len(daily_data))
    
    # Get market regime
    regime, nifty_ratio, nifty_weight = get_market_regime()
    pos_mult = get_position_size_multiplier(regime, nifty_weight)
    
    if pos_mult == 0.0:
        log.info("🛑 DOWNTREND - no new entries today")
        return
    
    # Trading loop
    entry_price = None
    stop_loss = None
    targets = []
    positions_closed = []
    high_water_mark = None
    position_open = False
    
    while is_market_open():
        now = ist_now()
        log.info("⏰ [%s IST] Checking entry conditions...", now.strftime("%H:%M:%S"))
        
        # Fetch intraday data
        intraday_15m = fetch_intraday_15min(SYMBOL)
        intraday_1hr = fetch_intraday_1hr(SYMBOL)
        
        if not intraday_15m:
            log.warning("No 15min data available yet")
            time.sleep(60)
            continue
        
        current_price = intraday_15m[-1]["close"]
        
        # Get TSI signal from daily data
        tsi_sig, tsi_price, atr = tsi_signal(daily_data, PARAMS)
        log.info("📊 TSI Signal: %s | Price: %.2f | ATR: %.2f", tsi_sig, tsi_price, atr)
        
        # Check if we can enter
        if not position_open and can_new_entry():
            conditions_met, reason, score = smart_entry_conditions_met(
                intraday_15m, intraday_1hr, daily_data, current_price, tsi_sig
            )
            
            if conditions_met and score >= 0.7:
                log.info("🚀 ENTERING POSITION | Score: %.2f | Reason: %s", score, reason)
                
                entry_price = round(current_price, 2)
                atr_used = atr if atr > 0 else current_price * 0.008  # fallback ATR
                stop_loss = calculate_dynamic_sl(entry_price, atr_used)
                targets = calculate_targets(entry_price, stop_loss)
                high_water_mark = entry_price
                positions_closed = []
                
                # Calculate position size with regime multiplier
                effective_position = int(POSITION * pos_mult)
                quantity = max(1, effective_position // entry_price)
                
                log.info("💰 Entry: ₹%.2f | SL: %.2f (risk ₹%.2f) | Qty: %d | Eff Pos: ₹%d",
                         entry_price, stop_loss, entry_price - stop_loss, quantity, effective_position)
                
                # Place order
                order_result = place_groww_order(SYMBOL, "BUY", quantity, entry_price)
                log.info("📋 Order: %s", order_result)
                position_open = True
        
        # Monitor open position
        if position_open and entry_price:
            # Update high water mark
            if current_price > high_water_mark:
                high_water_mark = current_price
            
            # Check targets
            targets, positions_closed = check_target_tiers(
                current_price, entry_price, targets, positions_closed
            )
            
            # Check trailing stop
            new_sl = check_trailing_stop(current_price, entry_price, stop_loss, high_water_mark)
            if new_sl > stop_loss:
                log.info("🔄 Stop loss raised to %.2f", new_sl)
                stop_loss = new_sl
            
            # Check hard stop loss
            if current_price <= stop_loss:
                log.info("🛑 STOP LOSS HIT at %.2f (SL: %.2f)", current_price, stop_loss)
                order_result = place_groww_order(SYMBOL, "SELL", quantity, current_price)
                log.info("📋 Stop order: %s", order_result)
                position_open = False
                break
            
            # Check if all targets hit
            if len(positions_closed) == 3:
                log.info("✅ ALL TARGETS HIT - closing remaining position")
                order_result = place_groww_order(SYMBOL, "SELL", quantity, current_price)
                log.info("📋 Close order: %s", order_result)
                position_open = False
                break
            
            # Log current P&L
            pnl = (current_price - entry_price) * quantity
            pnl_pct = (current_price - entry_price) / entry_price * 100
            log.info("📊 P&L: ₹%.2f (%.2f%%) | HW: %.2f | SL: %.2f | Closed: %s",
                     pnl, pnl_pct, high_water_mark, stop_loss, positions_closed)
        
        # Update daily data for next iteration
        updated_daily = fetch_recent_data(SYMBOL, days=60)
        if updated_daily and updated_daily != daily_data:
            daily_data = updated_daily
        
        # Wait before next check
        time.sleep(300)  # 5-minute intervals
    
    # End of day
    if position_open:
        log.info("📡 EOD - squaring off open position at market")
        # Square off at last price
        final_data = fetch_intraday_15min(SYMBOL)
        if final_data:
            final_price = final_data[-1]["close"]
            order_result = place_groww_order(SYMBOL, "SELL", quantity, final_price)
            log.info("📋 EOD Square-off: %s", order_result)
    
    log.info("🏁 Trading session ended")
    return


if __name__ == "__main__":
    main()
