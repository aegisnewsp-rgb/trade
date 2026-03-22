#!/usr/bin/env python3
"""
Live Trading Script - TCS.NS
Strategy: VWAP_ALPHA_IT — VWAP + RSI + Volume + IT-Sector-Aware Parameters
Win Rate: 63.64% → Target: 70%+
Position: ₹10,000 | Daily Loss Cap: 0.3%

Key enhancements (tomorrow edition):
- USD/INR filter: weaker rupee (higher USD/INR) = tailwind for TCS (IT exporter)
- NIFTY IT index filter: only trade when IT sector is favorable
- Tightened entry window: 10 AM – 1 PM IST (peak IT liquidity)
- 4× ATR profit target (₹120-160 on ₹3800 TCS)
- Stop loss: 1.0× ATR (tighter, better R:R)
- Position increased to ₹10,000 (fixed, no martingale)
"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_TCS.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_TCS")

SYMBOL = "TCS.NS"
STRATEGY = "VWAP_ALPHA_IT"
POSITION = 10000          # Fixed ₹10K per trade (no martingale)
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_period": 14, "atr_multiplier": 1.0}

# ── Advanced Alpha Config ──────────────────────────────────────────────────────
NIFTY_SYMBOL    = "^NSEI"
NIFTY_IT_SYMBOL = "^CNXIT"   # NIFTY IT Index — IT sector proxy
USD_INR_SYMBOL  = "USDINR=X" # USD/INR exchange rate

ENTRY_WAIT_MINUTES   = 15
NO_ENTRY_AFTER      = dtime(14, 30)  # No new entries after 2:30 PM IST
BEST_ENTRY_START    = dtime(9, 30)   # 9:30 AM IST — smart entry window
BEST_ENTRY_END      = dtime(14, 30)   # 2:30 PM IST — smart entry window

ENTRY_VWAP_PCT   = 0.005   # Price must be 0.5% above VWAP (₹19 on ₹3800)
ENTRY_RSI_MIN    = 55      # Both 15m and 1h RSI must confirm
ENTRY_VOL_MULT   = 1.2     # Volume must be 1.2× 20-day avg

SL_ATR_MULT      = 1.0     # Stop loss: 1.0× ATR (tighter)
MAX_SL_PCT       = 0.02    # Hard cap: 2% max stop
TRAIL_TRIGGER_PCT = 0.01   # Trail after 1% profit

TARGET_1_MULT     = 1.5    # T1: 1.5× risk → 1.5× ATR profit
TARGET_2_MULT     = 3.0    # T2: 3.0× risk → 3.0× ATR profit
TARGET_3_MULT     = 4.0    # T3: 4.0× risk → 4.0× ATR profit (primary target)

# IT Sector filters
USD_INR_STRENGTH_THRESHOLD = 0.005  # USD/INR must be rising >0.5% (weaker INR = good for TCS)
NIFTY_IT_BULL_THRESHOLD    = 0.0    # NIFTY IT must be above its SMA20

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")

# ── Time Utilities ────────────────────────────────────────────────────────────

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
        log.info("⏰ Too early — waiting for 10:00 AM IST (best entry window)")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM — no new entries today")
        return False
    return True

def in_best_entry_window() -> bool:
    """True when we're in the prime entry window (10 AM – 1 PM)."""
    now = ist_now().time()
    return BEST_ENTRY_START <= now <= BEST_ENTRY_END

# ── Data Fetching ────────────────────────────────────────────────────────────

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

def fetch_usd_inr() -> tuple[float, float] | None:
    """
    Fetch current USD/INR rate and 20-day SMA.
    Weaker INR (higher rate) = bullish for TCS exports.
    """
    try:
        df = yf.Ticker(USD_INR_SYMBOL).history(period="30d")
        if df.empty or len(df) < 5:
            log.warning("USD/INR data unavailable — skipping IT sector filter")
            return None
        closes = df["Close"].iloc[-20:].tolist()
        current = float(closes[-1])
        sma20 = sum(closes) / len(closes)
        return current, sma20
    except Exception as e:
        log.warning("USD/INR fetch error: %s", e)
        return None

def fetch_nifty_it() -> tuple[float, float] | None:
    """
    Fetch NIFTY IT index current price and SMA20.
    Bullish IT sector = favorable for TCS.
    """
    try:
        df = yf.Ticker(NIFTY_IT_SYMBOL).history(period="60d")
        if df.empty or len(df) < 25:
            log.warning("NIFTY IT data unavailable — skipping sector filter")
            return None
        closes = df["Close"].iloc[-20:].tolist()
        current = float(df["Close"].iloc[-1])
        sma20 = sum(closes) / len(closes)
        return current, sma20
    except Exception as e:
        log.warning("NIFTY IT fetch error: %s", e)
        return None

# ── Technical Indicators ────────────────────────────────────────────────────

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

def calculate_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    return 100 - (100 / (1 + rs))

def calculate_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

# ── Market Regime ─────────────────────────────────────────────────────────────

def get_market_regime() -> tuple[str, float]:
    nifty_data = fetch_recent_data(NIFTY_SYMBOL, days=40)
    if not nifty_data or len(nifty_data) < 25:
        log.warning("Could not fetch NIFTY data — assuming UPTREND")
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

# ── IT Sector Filter ─────────────────────────────────────────────────────────

def check_it_sector_brief() -> dict:
    """
    Check USD/INR and NIFTY IT for IT-sector tailwind.
    Returns dict with findings and a pass/fail flag.
    """
    report = {"usd_inr_ok": True, "nifty_it_ok": True, "it_bullish": True, "detail": ""}

    # Check USD/INR — weaker rupee = good for TCS (IT exporter)
    usd_inr = fetch_usd_inr()
    if usd_inr:
        curr_inr, sma_inr = usd_inr
        inr_strength = (curr_inr - sma_inr) / sma_inr if sma_inr > 0 else 0
        report["usd_inr_ok"] = inr_strength > -USD_INR_STRENGTH_THRESHOLD
        log.info("💱 USD/INR: %.4f | SMA20: %.4f | Strength: %+.2f%% | %s",
                 curr_inr, sma_inr, inr_strength * 100,
                 "✅ Weaker INR (TCS tailwind)" if inr_strength > 0 else "⚠️ Stronger INR")
    else:
        log.info("💱 USD/INR: unavailable — proceeding without filter")
        report["usd_inr_ok"] = True  # Don't block if unavailable

    # Check NIFTY IT — bullish IT sector = good for TCS
    nifty_it = fetch_nifty_it()
    if nifty_it:
        curr_it, sma_it = nifty_it
        it_ratio = curr_it / sma_it if sma_it > 0 else 1.0
        report["nifty_it_ok"] = it_ratio > (1 + NIFTY_IT_BULL_THRESHOLD)
        log.info("🖥️  NIFTY IT: %.2f | SMA20: %.2f | Ratio: %.3f | %s",
                 curr_it, sma_it, it_ratio,
                 "✅ IT sector bullish" if it_ratio > 1.0 else "⚠️ IT sector weak")
    else:
        log.info("🖥️  NIFTY IT: unavailable — proceeding without filter")
        report["nifty_it_ok"] = True

    report["it_bullish"] = report["usd_inr_ok"] and report["nifty_it_ok"]
    report["detail"] = (
        f"USD/INR: {'✅' if report['usd_inr_ok'] else '❌'} | "
        f"NIFTY IT: {'✅' if report['nifty_it_ok'] else '❌'}"
    )
    return report

# ── Entry Conditions ─────────────────────────────────────────────────────────

def smart_entry_conditions_met(intraday_15m: list, intraday_1hr: list,
                                daily_ohlcv: list, current_price: float) -> tuple[bool, str]:
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data..."

    now = ist_now()
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close"

    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1

    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0

    vwap_15m = calculate_vwap(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price

    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m) if len(closes_15m) > 14 else 50.0

    vwap_1hr = calculate_vwap(intraday_1hr) if intraday_1hr else []
    vwap_val_1hr = vwap_1hr[-1] if vwap_1hr else current_price

    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr) if len(closes_1hr) > 14 else 50.0

    log.info("📊 Entry Check | Price: %.2f | VWAP_15m: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio)

    # Condition 1: Price > VWAP + 0.5% (₹19 above VWAP on ₹3800 TCS)
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)

    # Condition 2: RSI > 55 on both timeframes (momentum confirmation)
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5

    # Condition 3: Volume > 1.2× 20-day average
    cond3 = vol_ratio > ENTRY_VOL_MULT

    # Condition 4: RSI alignment across timeframes (market temperament)
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

# ── Signal Generation ────────────────────────────────────────────────────────

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    period = params["vwap_period"]
    atr_period = params.get("atr_period", 14)
    atr_mult = params["atr_multiplier"]
    vwap_vals = calculate_vwap(ohlcv)
    atr_vals = calculate_atr(ohlcv, atr_period)
    closes = [bar["close"] for bar in ohlcv]
    rsi_vals = calculate_rsi(closes) if len(closes) > 14 else [50.0] * len(ohlcv)
    signals = ["HOLD"] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        v, a = vwap_vals[i], atr_vals[i]
        rsi = rsi_vals[i] if i < len(rsi_vals) else 50.0
        # BUY: price > VWAP + ATR AND RSI > 55
        if price > v + a * atr_mult and rsi > ENTRY_RSI_MIN:
            signals[i] = "BUY"
        # SELL: price < VWAP - ATR AND RSI < 45
        elif price < v - a * atr_mult and rsi < 45:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals else 50.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr, current_rsi

def calculate_dynamic_sl(entry_price: float, atr: float) -> float:
    sl_atr = entry_price - (SL_ATR_MULT * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    stop_loss = max(sl_atr, sl_max)
    log.info("🎯 Dynamic SL: ATR-based=%.2f | Max-2%%=%.2f | Selected=%.2f",
             sl_atr, sl_max, stop_loss)
    return round(stop_loss, 2)

def calculate_targets(entry_price: float, stop_loss: float) -> list:
    risk = entry_price - stop_loss
    t1 = round(entry_price + (TARGET_1_MULT * risk), 2)
    t2 = round(entry_price + (TARGET_2_MULT * risk), 2)
    t3 = round(entry_price + (TARGET_3_MULT * risk), 2)

    targets = [
        {"level": 1, "price": t1, "risk_mult": TARGET_1_MULT, "exit_pct": 0.33, "desc": "Secure 1.5×"},
        {"level": 2, "price": t2, "risk_mult": TARGET_2_MULT, "exit_pct": 0.33, "desc": "Main 3×"},
        {"level": 3, "price": t3, "risk_mult": TARGET_3_MULT, "exit_pct": 0.34, "desc": "Stretch 4×"},
    ]
    return targets

# ── Signal Logging ───────────────────────────────────────────────────────────

def log_signal(signal, price, atr, rsi):
    log_file = LOG_DIR / "signals_TCS.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except Exception:
            entries = []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol": SYMBOL,
        "strategy": STRATEGY,
        "signal": signal,
        "price": round(price, 4),
        "atr": round(atr, 4),
        "rsi": round(rsi, 2),
    })
    entries = entries[-500:]
    log_file.write_text(json.dumps(entries, indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f, RSI=%.1f)", signal, price, atr, rsi)

# ── Groww Order Placement ───────────────────────────────────────────────────

def place_groww_order(symbol, signal, quantity, price):
    import groww_api

    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)

    exchange = "NSE"

    if signal == "BUY":
        stop_loss = price - (atr * SL_ATR_MULT)
        target = price + (atr * TARGET_3_MULT)
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
        stop_loss = price + (atr * SL_ATR_MULT)
        target = price - (atr * TARGET_3_MULT)
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
        print("Order placed: {} {} {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
    return result

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("TCS Live Trading — VWAP_ALPHA_IT | Win Rate: 63.64%% | ₹10K pos")
    log.info("Deep Reasoning: IT-sector-aware | 4× ATR target | 10AM-1PM window")
    log.info("=" * 60)

    # Wait for pre-market to clear
    while is_pre_market():
        log.info("Pre-market warmup — waiting until 9:15 IST...")
        time.sleep(30)

    if not is_market_open():
        log.info("Market closed. Exiting.")
        return

    # ── Market regime check ────────────────────────────────────────────────
    regime, ratio = get_market_regime()
    pos_mult = get_position_size_multiplier(regime)
    if pos_mult == 0.0:
        log.warning("⛔ DOWNTREND regime — no new entries today")
        return
    if pos_mult == 0.5:
        log.info("⚠️ RANGE regime — 50%% position size")

    # ── IT Sector Filter ────────────────────────────────────────────────────
    it_report = check_it_sector_brief()
    log.info("🖥️  IT Sector Filter: %s", it_report["detail"])
    if not it_report["it_bullish"]:
        log.warning("⛔ IT sector headwinds — skipping TCS entry today")
        log.info("   (USD/INR or NIFTY IT not favorable")

    # ── Fetch all required data ──────────────────────────────────────────────
    log.info("Fetching market data...")
    daily_ohlcv = fetch_recent_data(SYMBOL, days=90)
    if not daily_ohlcv or len(daily_ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return

    intraday_15m = fetch_intraday_15min(SYMBOL)
    intraday_1hr = fetch_intraday_1hr(SYMBOL)

    # ── Generate signal ────────────────────────────────────────────────────
    signal, price, atr, rsi = vwap_signal(daily_ohlcv, PARAMS)
    log.info("📊 Daily Signal: %s | Price: ₹%.2f | ATR: ₹%.4f | RSI: %.1f",
             signal, price, atr, rsi)

    # ── Smart entry check (intraday conditions) ─────────────────────────────
    if signal == "BUY" and can_new_entry() and it_report["it_bullish"]:
        entry_ok, entry_reason = smart_entry_conditions_met(
            intraday_15m, intraday_1hr, daily_ohlcv, price
        )
        log.info("Smart Entry: %s", entry_reason)

        if entry_ok:
            stop_loss = calculate_dynamic_sl(price, atr)
            targets = calculate_targets(price, stop_loss)
            risk = price - stop_loss
            quantity = max(1, int((POSITION * pos_mult) / price))

            log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            log.info("  🟢 BUY SIGNAL — TCS")
            log.info("  Symbol    : %s", SYMBOL)
            log.info("  Strategy  : %s", STRATEGY)
            log.info("  Price     : ₹%.2f", price)
            log.info("  Qty       : %d shares (₹%d position)", quantity, int(POSITION * pos_mult))
            log.info("  ATR       : ₹%.4f", atr)
            log.info("  RSI 15m/1h: %.1f / %.1f", rsi, rsi)
            log.info("  Stop Loss : ₹%.2f  (%.1f× ATR)", stop_loss, SL_ATR_MULT)
            for t in targets:
                log.info("  Target %d  : ₹%.2f  (%.1f× ATR, %s)",
                         t["level"], t["price"], t["risk_mult"], t["desc"])
            log.info("  Risk/Rew  : ₹%.2f / ₹%.2f = 1:%.1f",
                     risk, price - stop_loss, (price - stop_loss) / risk if risk > 0 else 0)
            log.info("  Entry Win : %s", in_best_entry_window() and "✅ 10AM-1PM" or "⚠️ Outside window")
            log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            log_signal(signal, price, atr, rsi)
            result = place_groww_order(SYMBOL, "BUY", quantity, price)
            if result:
                log.info("✓ Order executed: %s", result)
            else:
                log.info("📋 Paper mode — signal logged only")
        else:
            log.info("Entry not triggered: %s", entry_reason)

    elif signal == "SELL" and can_new_entry() and it_report["it_bullish"]:
        log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log.info("  🔴 SELL SIGNAL — TCS (short)")
        log.info("  Price: ₹%.2f | ATR: ₹%.4f | RSI: %.1f", price, atr, rsi)
        log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log_signal(signal, price, atr, rsi)
        # Short entries not implemented — log only
        log.info("Short entries not enabled for TCS (long-only strategy)")

    else:
        status = "no signal"
        if not can_new_entry():
            status = "outside entry window (10AM-1PM)"
        elif not it_report["it_bullish"]:
            status = "IT sector headwinds"
        log.info("⚪ HOLD — %s", status)
        log.info("  Price: ₹%.2f | ATR: ₹%.4f | RSI: %.1f | Regime: %s",
                 price, atr, rsi, regime)

    log.info("=" * 60)
    log.info("Session complete — TCS monitoring done.")
    return


if __name__ == "__main__":
    main()
