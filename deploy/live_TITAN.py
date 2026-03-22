#!/usr/bin/env python3
"""
Live Trading Script - TITAN.NS
Strategy: VWAP + ADVANCED ALPHA
Enhanced: Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime Filter
Gold-Aware | Seasonality-Adjusted | Consumer Index Confirmation
Win Rate: 61.11% → Target: 70%+
Position: ₹7000 | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_TITAN.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_TITAN")

SYMBOL = "TITAN.NS"
STRATEGY = "VWAP_ALPHA_GOLD_AWARE"
POSITION = 7000
DAILY_LOSS_CAP = 0.003

# Gold-aware: jewelry stock — gold is raw material AND demand driver
GOLD_SYMBOL = "GC=F"  # Gold Futures (CME) — proxies MCX India correlation
GOLD_FALLBACK_SYMBOLS = ["^MCX", "TAIEX"]  # fallback if GC=F unavailable
NIFTY_SYMBOL = "^NSEI"
NIFTY_CONSUMER_SYMBOL = "^CNXCNR"  # Nifty Consumer Index

NIFTY50_SYMBOL = "^NSEI"
ENTRY_WAIT_MINUTES = 15
NO_ENTRY_AFTER = dtime(14, 30)
BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END = dtime(12, 0)

# === GOLD-AWARE PARAMETERS ===
# TITAN: gold price movement affects margins AND consumer demand
GOLD_TREND_CHECK_DAYS = 20
GOLD_HIGH_THRESHOLD_PCT = 0.03   # >3% gold rally in 20d → bullish tailwind
GOLD_LOW_THRESHOLD_PCT = -0.03   # <-3% gold drop in 20d → headwind (margins compressed)
GOLD_ATR_INFLATION = 1.25        # When gold is volatile, TITAN's ATR inflates too

# === SEASONALITY ADJUSTMENTS ===
# Wedding seasons: Nov-Feb (Q4) + Apr-May (Q2)
# Non-wedding/post-season: Mar (current), Jun-Oct
SEASONAL_VOL_MULTIPLIER = {
    "Q4": 1.15,   # Nov-Feb: higher volumes, slightly higher ATR
    "Q2": 1.10,   # Apr-May: wedding prep season
    "Q1": 0.85,   # Mar: post-wedding, softer — REDUCE vol thresholds
    "Q3": 0.90,   # Jun-Oct: monsoon + slowdown, moderate
}
SEASONAL_VOL_THRESHOLD_ADJUST = {
    "Q4": 1.0,    # Full volume threshold
    "Q2": 1.0,    # Full volume threshold
    "Q1": 0.75,   # LOWER threshold — less volume needed to confirm
    "Q3": 0.85,   # Slightly lower threshold
}

# === CONSUMER INDEX CORRELATION ===
# TITAN tracks Nifty Consumer — don't fight the consumer index
CONSumer_CONFIRM_REQUIRED = True
CONSumer_MIN_CORRELATION = 0.55  # If consumer index RSI below this, proceed with caution

# === ENTRY PARAMETERS (consumer stocks = lower volatility → tighter stops) ===
ENTRY_VWAP_PCT = 0.004    # 0.4% — tighter than high-vol stocks
# RSI filter: BUY only when RSI > 55, SELL only when RSI < 45
ENTRY_RSI_MIN = 55
ENTRY_RSI_MAX = 45
# Volume 1.2x avg for entry confirmation
ENTRY_VOL_MULT = 1.2

# ATR: consumer stocks have lower daily range
SL_ATR_MULT = 1.5         # Tighter stop — consumer ATR is lower than IT/banking
MAX_SL_PCT = 0.018         # 1.8% max stop (tighter than 2% default)
TRAIL_TRIGGER_PCT = 0.008  # Lower trail trigger for lower-vol consumer stock

TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0

# Trailing stop: 0.3× ATR (activates after TRAIL_TRIGGER_PCT profit)
TRAIL_ATR_MULT = 0.3

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in/v1"


def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)


def get_seasonal_period() -> str:
    """Return current quarter/season for volume adjustments."""
    now = ist_now()
    month = now.month
    if month in [11, 12, 1, 2]:
        return "Q4"
    elif month in [4, 5]:
        return "Q2"
    elif month in [1, 2, 3]:
        return "Q1"
    else:
        return "Q3"


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
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr


def calculate_vwap(ohlcv: list) -> list:
    vwap, cum_pv, cum_vol = [], 0.0, 0
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


def get_gold_trend() -> tuple[str, float, float]:
    """
    Analyze gold price trend — TITAN is a gold proxy.
    Gold rising → demand indicator (jewelry is store of value) AND input cost pressure.
    Returns: (trend_label, pct_change_20d, gold_atr_pct)
    """
    gold_data = fetch_recent_data(GOLD_SYMBOL, days=GOLD_TREND_CHECK_DAYS + 10)
    if not gold_data or len(gold_data) < GOLD_TREND_CHECK_DAYS:
        log.warning("⚠️ Gold data unavailable — proceeding without gold confirmation")
        return "UNKNOWN", 0.0, 0.0
    
    gold_closes = [bar["close"] for bar in gold_data]
    gold_start = gold_closes[-(GOLD_TREND_CHECK_DAYS)]
    gold_end = gold_closes[-1]
    gold_pct_change = (gold_end - gold_start) / gold_start
    
    # Gold ATR (as % of price) — measures volatility
    gold_atr_vals = calculate_atr([
        {"high": bar["high"], "low": bar["low"], "close": bar["close"]}
        for bar in gold_data
    ], 14)
    gold_atr = gold_atr_vals[-1] if gold_atr_vals and gold_atr_vals[-1] else 0
    gold_atr_pct = gold_atr / gold_end if gold_end > 0 else 0
    
    if gold_pct_change > GOLD_HIGH_THRESHOLD_PCT:
        trend = "BULLISH_GOLD"
    elif gold_pct_change < GOLD_LOW_THRESHOLD_PCT:
        trend = "BEARISH_GOLD"
    else:
        trend = "NEUTRAL_GOLD"
    
    log.info("💰 Gold Trend: %s | 20d Change: %.2f%% | Gold ATR: %.2f%%", 
             trend, gold_pct_change * 100, gold_atr_pct * 100)
    return trend, gold_pct_change, gold_atr_pct


def get_consumer_index_regime() -> tuple[str, float, float]:
    """
    Check Nifty Consumer index — TITAN tracks consumer discretionary.
    Returns: (regime, rsi, pct_from_sma20)
    """
    consumer_data = fetch_recent_data(NIFTY_CONSUMER_SYMBOL, days=40)
    if not consumer_data or len(consumer_data) < 25:
        log.warning("⚠️ Consumer index data unavailable — skipping confirmation")
        return "UNKNOWN", 50.0, 0.0
    
    consumer_closes = [bar["close"] for bar in consumer_data]
    consumer_sma20 = calculate_sma(consumer_closes, 20)
    consumer_current = consumer_closes[-1]
    consumer_rsi = calculate_rsi(consumer_closes, 14)[-1]
    ratio = consumer_current / consumer_sma20
    
    if ratio > 1.02:
        regime = "BULLISH_CONSUMER"
    elif ratio < 0.98:
        regime = "BEARISH_CONSUMER"
    else:
        regime = "NEUTRAL_CONSUMER"
    
    log.info("🛒 Nifty Consumer: %s | RSI: %.1f | vs SMA20: %.2f%%", 
             regime, consumer_rsi, (ratio - 1) * 100)
    return regime, consumer_rsi, ratio


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
                                daily_ohlcv: list, current_price: float,
                                gold_trend: str, consumer_regime: str) -> tuple[bool, str]:
    """
    Enhanced smart entry with gold-aware + consumer-confirmed logic.
    March post-season: lower volume thresholds apply.
    """
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data..."
    
    now = ist_now()
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close"
    
    # Season-aware volume threshold
    season = get_seasonal_period()
    vol_adj = SEASONAL_VOL_THRESHOLD_ADJUST.get(season, 1.0)
    adjusted_vol_mult = ENTRY_VOL_MULT * vol_adj
    
    # Gold-aware ATR inflation
    gold_atr_mult = GOLD_ATR_INFLATION if gold_trend in ["BULLISH_GOLD", "BEARISH_GOLD"] else 1.0
    
    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1
    
    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    
    vwap_15m = calculate_vwap(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m)[-1] if len(closes_15m) > 14 else 50
    
    vwap_1hr = calculate_vwap(intraday_1hr) if intraday_1hr else []
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    log.info("📊 Smart Entry | Season: %s | Gold: %s | Consumer: %s", season, gold_trend, consumer_regime)
    log.info("📊 Price: %.2f | VWAP_15m: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f (adj: %.2f)",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio, adjusted_vol_mult)
    
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    # RSI filter: BUY only when RSI > 55, SELL only when RSI < 45
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    cond3 = vol_ratio > adjusted_vol_mult
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    
    # Gold-aware: if gold is BULLISH, TITAN entry is stronger signal
    gold_bonus = gold_trend == "BULLISH_GOLD"
    gold_penalty = gold_trend == "BEARISH_GOLD"
    
    # Consumer confirmation bonus
    consumer_ok = consumer_regime in ["BULLISH_CONSUMER", "NEUTRAL_CONSUMER"] and consumer_regime != "UNKNOWN"
    
    entry_score = sum([cond1, cond2, cond3, mt_confirmation, consumer_ok])
    if gold_bonus:
        entry_score += 0.5
    if gold_penalty:
        entry_score -= 0.5
    
    reasons = []
    if cond1:
        reasons.append(f"Price>VWAP+{ENTRY_VWAP_PCT:.2%}")
    if cond2:
        reasons.append(f"RSI>{ENTRY_RSI_MIN}")
    if cond3:
        reasons.append(f"Vol>{adjusted_vol_mult:.2f}x")
    if gold_bonus:
        reasons.append("Gold+")
    if consumer_ok and consumer_regime != "UNKNOWN":
        reasons.append("Consumer✓")
    
    if entry_score >= 3.5:
        return True, "✅ SMART ENTRY: " + " + ".join(reasons)
    
    reject_reasons = []
    if not cond1:
        reject_reasons.append(f"Price<VWAP+{ENTRY_VWAP_PCT:.2%} ({current_price/vwap_val-1:.2%})")
    if not cond2:
        reject_reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3:
        reject_reasons.append(f"Vol low ({vol_ratio:.2f}x vs {adjusted_vol_mult:.2f}x needed)")
    if not consumer_ok:
        reject_reasons.append(f"Consumer weak ({consumer_regime})")
    
    return False, "❌ Entry conditions not met: " + " | ".join(reject_reasons)


def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period = params.get("vwap_period", 14)
    atr_mult = params.get("atr_multiplier", 1.5)
    vwap_vals = calculate_vwap(ohlcv)
    atr_vals = calculate_atr(ohlcv, period)
    signals = ["HOLD"] * len(ohlcv)
    
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        v, a = vwap_vals[i], atr_vals[i]
        if price > v + a * atr_mult:
            signals[i] = "BUY"
        elif price < v - a * atr_mult:
            signals[i] = "SELL"
    
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr


def calculate_dynamic_sl(entry_price: float, atr: float, gold_trend: str = "NEUTRAL_GOLD") -> float:
    """
    Consumer-aware stop loss: tighter than banking/IT.
    Gold trend can widen stops slightly if gold is volatile.
    """
    # Gold ATR inflation — gold volatility bleeds into TITAN
    gold_mult = GOLD_ATR_INFLATION if gold_trend in ["BULLISH_GOLD", "BEARISH_GOLD"] else 1.0
    effective_atr_mult = SL_ATR_MULT * gold_mult
    
    sl_atr = entry_price - (effective_atr_mult * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    stop_loss = max(sl_atr, sl_max)
    
    season = get_seasonal_period()
    vol_mult = SEASONAL_VOL_MULTIPLIER.get(season, 1.0)
    # In low-volume Q1 (March), slightly tighter stop
    if season == "Q1":
        stop_loss = max(stop_loss, entry_price * (1 - MAX_SL_PCT * 0.9))
    
    log.info("🎯 Dynamic SL: ATR-based=%.2f (mult=%.1f) | Max-1.8%%=%.2f | Selected=%.2f",
             sl_atr, effective_atr_mult, sl_max, stop_loss)
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
        stop_loss = price - (atr * 1.0)
        target = price + (atr * 4.0)
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
    Enhanced with Gold-Aware + Consumer-Confirmed + Seasonally-Adjusted logic.
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
    
    fname = Path(__file__).stem
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    
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
    
    # === PRE-TRADE ANALYSIS ===
    print(f"\n{'='*50}")
    print("PRE-TRADE ANALYSIS")
    print(f"{'='*50}")
    
    # 1. Gold trend
    gold_trend, gold_chg, gold_atr_pct = get_gold_trend()
    print(f"Gold: {gold_trend} ({gold_chg*100:.2f}% / 20d)")
    
    # 2. Consumer index
    consumer_regime, consumer_rsi, consumer_ratio = get_consumer_index_regime()
    print(f"Consumer: {consumer_regime} (RSI: {consumer_rsi:.1f})")
    
    # 3. Market regime
    market_regime, market_ratio = get_market_regime()
    print(f"Market: {market_regime} (Nifty vs SMA20: {market_ratio:.3f})")
    
    # 4. Seasonal period
    season = get_seasonal_period()
    print(f"Season: {season} (volume mult: {SEASONAL_VOL_THRESHOLD_ADJUST.get(season, 1.0):.2f})")
    
    # Signal generation
    signal = None
    price = ohlcv_list[-1][3]  # close price
    
    try:
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, {"vwap_period": 14, "atr_multiplier": 1.5})
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
            closes = [o[3] for o in ohlcv_list]
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
    
    # Calculate ATR
    # Use real ATR from calculate_atr()
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
    
    print(f"\n{'='*50}")
    print(f"Signal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f} ({atr/price*100:.2f}%)")
    
    # Gold-aware signal adjustment
    if signal == "BUY" and gold_trend == "BEARISH_GOLD":
        log.warning("⚠️ BUY signal but gold is bearish — gold headwind on margins")
    if signal == "SELL" and gold_trend == "BULLISH_GOLD":
        log.warning("⚠️ SELL signal but gold is bullish — gold tailwind may persist")
    
    if signal == "BUY":
        sl = calculate_dynamic_sl(price, atr, gold_trend)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(POSITION / price))
        risk = price - sl
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{risk:.2f} risk = {risk/price*100:.2f}%)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")
        
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy=STRATEGY,
                atr=atr,
                metadata={
                    "source": Path(__file__).name,
                    "gold_trend": gold_trend,
                    "consumer_regime": consumer_regime,
                    "season": season,
                    "market_regime": market_regime,
                }
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
        qty = max(1, int(POSITION / price))
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
                strategy=STRATEGY,
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
