#!/usr/bin/env python3
"""
Live Trading Script - TATASTEEL.NS
Strategy: VWAP + RSI + Volume + ADX + MACD (v6 enhanced)
Win Rate: 58.06% -> Target 62%+
Position: ₹7000 | Stop Loss: 1.3x ATR | Target: 2.5x ATR | Daily Loss Cap: 0.3%
Enhancements over v5:
  - RSI bands tightened: 45/55 → 48/52 → stricter quality filter for entries
  - Volume confirm raised: 1.2x → 1.3x → stronger volume required
  - ADX min raised: 20 → 22 → only very confirmed trends qualify
  - Target tightened: 3.0x → 2.5x ATR → shorter target = higher win rate
"""

import os

import sys
from pathlib import Path
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
        logging.FileHandler(LOG_DIR / "live_TATASTEEL.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_TATASTEEL")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL             = "TATASTEEL.NS"
STRATEGY           = "VWAP+RSI+VOL+ADX+MACD"
POSITION           = 7000
STOP_LOSS_ATR_MULT = 1.3   # was 1.5x → tighter for better risk:reward
TARGET_ATR_MULT    = 2.5   # was 3.0x → v6: shorter target = higher hit rate
DAILY_LOSS_CAP     = 0.003
PARAMS = {
    "vwap_period":         14,
    "atr_multiplier":      1.3,
    "rsi_period":          14,
    "rsi_buy_min":         48,   # was 45 → v6: stricter RSI floor for quality entries
    "rsi_sell_max":        52,   # was 55 → v6: stricter RSI ceiling for short exits
    "vol_sma_period":      20,
    "vol_confirm_mult":    1.3, # was 1.2 → v6: require stronger volume for confirmation
    "atr_vol_period":     20,   # period for ATR volatility SMA
    "adx_period":         14,   # ADX period for trend strength
    "adx_min":            22,   # was 20 → v6: only trade in stronger confirmed trends
    "macd_fast":           12,   # MACD fast EMA
    "macd_slow":           26,   # MACD slow EMA
    "macd_signal":          9,   # MACD signal line
    "session_avoid_min":   15,   # avoid first/last N minutes of session
}

BENCHMARK_WIN_RATE = 0.5806   # v3 live benchmark → v6 targeting 62%+
TARGET_WIN_RATE   = 0.62

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

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Compute RSI (Relative Strength Index)."""
    rsi = [None] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        delta = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi[i + 1] = 100 - (100 / (1 + rs))
    return rsi

def calculate_vol_sma(ohlcv: list, period: int = 20) -> list:
    """20-day SMA of volume for volume confirmation."""
    vol_sma = [None] * len(ohlcv)
    for i in range(period - 1, len(ohlcv)):
        vol_sma[i] = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
    return vol_sma

def calculate_atr_sma(atr_vals: list, period: int = 20) -> list:
    """20-day SMA of ATR for volatility filter."""
    atr_sma = [None] * len(atr_vals)
    valid = [v for v in atr_vals if v is not None]
    for i in range(len(atr_vals)):
        window = [v for v in atr_vals[max(0, i - period + 1):i + 1] if v is not None]
        if len(window) >= period // 2:  # require at least half the period
            atr_sma[i] = sum(window) / len(window)
    return atr_sma

def calculate_adx(ohlcv: list, period: int = 14) -> tuple[list, list, list]:
    """
    Compute ADX (Average Directional Index), +DI, -DI.
    Returns (adx_vals, plus_di, minus_di).
    """
    high  = [b["high"]  for b in ohlcv]
    low   = [b["low"]   for b in ohlcv]
    close = [b["close"] for b in ohlcv]

    tr_list = [None] * len(ohlcv)
    plus_dm = [None] * len(ohlcv)
    minus_dm = [None] * len(ohlcv)

    for i in range(1, len(ohlcv)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
        tr_list[i] = tr
        plus_dm[i]  = max(high[i] - high[i - 1], 0) if high[i] - high[i - 1] > low[i - 1] - low[i] else 0
        minus_dm[i] = max(low[i - 1] - low[i], 0)  if low[i - 1] - low[i] > high[i] - high[i - 1] else 0

    # Smooth with Wilder's smoothing (EWM with alpha=1/period)
    def wilder_smooth(vals, period):
        out = [None] * len(vals)
        valid = [v for v in vals[1:] if v is not None]
        if len(valid) < period:
            return out
        sma = sum(valid[:period]) / period
        out[period] = sma
        for i in range(period + 1, len(vals)):
            if vals[i] is not None:
                sma = (sma * (period - 1) + vals[i]) / period
                out[i] = sma
        return out

    tr_s  = wilder_smooth(tr_list, period)
    pdm_s = wilder_smooth(plus_dm, period)
    mdm_s = wilder_smooth(minus_dm, period)

    plus_di  = [None] * len(ohlcv)
    minus_di = [None] * len(ohlcv)
    dx       = [None] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if tr_s[i] and tr_s[i] != 0:
            plus_di[i]  = 100 * pdm_s[i] / tr_s[i]
            minus_di[i] = 100 * mdm_s[i] / tr_s[i]
        if plus_di[i] is not None and minus_di[i] is not None:
            di_sum = plus_di[i] + minus_di[i]
            dx[i]  = 100 * abs(plus_di[i] - minus_di[i]) / di_sum if di_sum != 0 else 0

    # ADX = Wilder smooth of DX
    adx_vals = [None] * len(ohlcv)
    valid_dx = [v for v in dx[period:] if v is not None]
    if len(valid_dx) >= period:
        adx_sma = sum(valid_dx[:period]) / period
        adx_vals[period + period - 1] = adx_sma
        for i in range(period + period, len(ohlcv)):
            if dx[i] is not None:
                adx_sma = (adx_sma * (period - 1) + dx[i]) / period
                adx_vals[i] = adx_sma

    return adx_vals, plus_di, minus_di

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    """
    Compute MACD line, signal line, and histogram.
    Returns (macd_line, signal_line, histogram).
    Histogram > 0 = bullish momentum, < 0 = bearish momentum.
    """
    closes = [b["close"] for b in ohlcv]

    def ema(vals, period):
        out = [None] * len(vals)
        valid = [v for v in vals if v is not None]
        if len(valid) < period:
            return out
        sma = sum(valid[:period]) / period
        out[period - 1] = sma
        k = 2 / (period + 1)
        for i in range(period, len(vals)):
            if vals[i] is not None:
                out[i] = vals[i] * k + out[i - 1] * (1 - k)
        return out

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line = [None] * len(ohlcv)
    for i in range(len(ohlcv)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    signal_line = ema(macd_line, signal)

    histogram = [None] * len(ohlcv)
    for i in range(len(ohlcv)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram

def vwap_enhanced_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    VWAP + RSI + Volume + ADX + MACD (v5).
    Returns (signal, price, atr).
    Signal is HOLD if:
      - RSI not in valid range (BUY needs RSI > rsi_buy_min, SELL needs RSI < rsi_sell_max)
      - Volume below confirmation threshold
      - ATR above its SMA (choppy / high-volatility market)
      - ADX <= adx_min (no confirmed trend)
      - MACD histogram not aligned with signal direction
    """
    vwap_period   = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    rsi_period    = params["rsi_period"]
    rsi_buy_min   = params["rsi_buy_min"]
    rsi_sell_max  = params["rsi_sell_max"]
    vol_period    = params["vol_sma_period"]
    vol_mult      = params["vol_confirm_mult"]
    atr_vol_p     = params["atr_vol_period"]
    adx_period    = params["adx_period"]
    adx_min       = params["adx_min"]
    macd_fast     = params["macd_fast"]
    macd_slow     = params["macd_slow"]
    macd_signal   = params["macd_signal"]

    vwap_vals  = calculate_vwap(ohlcv, vwap_period)
    atr_vals   = calculate_atr(ohlcv, vwap_period)
    rsi_vals   = calculate_rsi(ohlcv, rsi_period)
    vol_sma    = calculate_vol_sma(ohlcv, vol_period)
    atr_sma    = calculate_atr_sma(atr_vals, atr_vol_p)
    adx_vals, plus_di, minus_di = calculate_adx(ohlcv, adx_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, macd_fast, macd_slow, macd_signal)

    signals    = ["HOLD"] * len(ohlcv)
    start_idx  = max(vwap_period, rsi_period, vol_period, atr_vol_p,
                     adx_period * 2, macd_slow + macd_signal)

    for i in range(start_idx, len(ohlcv)):
        if None in (vwap_vals[i], atr_vals[i], rsi_vals[i],
                    vol_sma[i], atr_sma[i], adx_vals[i], histogram[i]):
            continue
        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        vol_avg = vol_sma[i]
        atr_now = atr_vals[i]
        atr_avg = atr_sma[i]
        adx     = adx_vals[i]
        hist    = histogram[i]

        # Volatility filter: skip in choppy / high-volatility regimes
        if atr_avg is not None and atr_now > atr_avg * 1.15:
            continue

        # ADX trend filter: require confirmed trend (ADX > adx_min)
        if adx is not None and adx <= adx_min:
            continue

        # Volume confirmation
        if vol < vol_avg * vol_mult:
            continue

        if price > v + a * atr_mult:
            if rsi > rsi_buy_min and hist > 0:   # RSI > 45 + bullish MACD
                signals[i] = "BUY"
        elif price < v - a * atr_mult:
            if rsi < rsi_sell_max and hist < 0:  # RSI < 55 + bearish MACD
                signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_TATASTEEL.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except Exception:
            entries = []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol":    SYMBOL,
        "strategy":  STRATEGY,
        "signal":    signal,
        "price":     round(price, 4),
        "atr":       round(atr, 4),
    })
    entries[-500:]
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_TATASTEEL.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception:
            pass
    return False

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Live Trading Script: %s | %s | Win Rate: %.2f%% -> Target: %.0f%% ===",
             SYMBOL, STRATEGY, BENCHMARK_WIN_RATE * 100, TARGET_WIN_RATE * 100)

    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)

    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return

    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return

    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=120)   # extra days for RSI + vol SMA warmup
    if not ohlcv or len(ohlcv) < 60:
        log.error("Insufficient data for %s", SYMBOL)
        return

    signal, price, atr = vwap_enhanced_signal(ohlcv, PARAMS)

    if signal == "BUY":
        stop_loss  = round(price - STOP_LOSS_ATR_MULT * atr, 2)
        target_prc = round(price + TARGET_ATR_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price + STOP_LOSS_ATR_MULT * atr, 2)
        target_prc = round(price - TARGET_ATR_MULT * atr, 2)
    else:
        stop_loss  = 0.0
        target_prc = 0.0

    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s (v6 enhanced)", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : ₹%.2f  (%.1f× ATR)", stop_loss, STOP_LOSS_ATR_MULT)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_ATR_MULT)
    log.info("  FILTERS  : RSI(%.0f-%.0f) | Vol>avg×%.1f | Vol-chop | ADX>%.0f | MACD hist | TGT=%.1fxATR",
             PARAMS["rsi_buy_min"], PARAMS["rsi_sell_max"], PARAMS["vol_confirm_mult"], PARAMS["adx_min"], TARGET_ATR_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    log_signal(signal, price, atr)

    if signal != "HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.warning("⚠ Groww order could not be placed – signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials found – signal printed only (paper mode).")

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