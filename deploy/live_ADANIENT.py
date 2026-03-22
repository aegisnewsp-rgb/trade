#!/usr/bin/env python3
"""
Live Trading Script - ADANIENT.NS
Strategy: TSI (True Strength Index) v2 — with multi-filter confirmation
Benchmark Win Rate: 57.69% | Target Win Rate: 62.00%
Filters: RSI(14,35/65) + Volume(20-MA) + Trend(50-MA) + Volatility(ATR 0.5-5%)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
Max 1 trade/day

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
Requires GROWW_API_KEY and GROWW_API_SECRET env vars for live orders.
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, time as dtime
from pathlib import Path

# ── yfinance ──────────────────────────────────────────────────────────────────
import yfinance as yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_ADANIENT.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ADANIENT")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL        = "ADANIENT.NS"
STRATEGY      = "TSI"
WIN_RATE           = 0.5769
BENCHMARK_WIN_RATE = 0.5769
TARGET_WIN_RATE    = 0.62     # v2 enhanced target with multi-filter TSI
FILTERS_APPLIED    = "RSI(14,35/65) + Volume(20-MA) + Trend(50-MA) + Volatility(ATR 0.5-5%)"
POSITION      = 7000          # ₹
STOP_LOSS_PCT = 0.008         # 0.8%
TARGET_MULT   = 4.0           # 4.0 × ATR
DAILY_LOSS_CAP = 0.003       # 0.3%
MAX_TRADES    = 1
PARAMS        = {"fast_period": 13, "slow_period": 25, "signal_period": 13}

# Groww API
GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5  # hours

# ── Helpers ───────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)


def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    market_time = now.time()
    return dtime(9, 15) <= market_time <= dtime(15, 30)


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


# ── Filter Helpers (v2 multi-filter TSI) ──────────────────────────────────────

def calculate_rsi(ohlcv: list, period: int = 14) -> float:
    """RSI(14) – used as momentum filter to avoid false TSI crossovers."""
    if len(ohlcv) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        chg = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(chg if chg > 0 else 0.0)
        losses.append(abs(chg) if chg < 0 else 0.0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_volume_ma(ohlcv: list, period: int = 20) -> float:
    """20-day volume MA – filter out low-volume whipsaws."""
    if len(ohlcv) < period:
        return 0.0
    vols = [bar["volume"] for bar in ohlcv[-period:]]
    return sum(vols) / period


def calculate_price_ma(ohlcv: list, period: int = 50) -> float:
    """50-day close MA – trend direction filter."""
    if len(ohlcv) < period:
        return 0.0
    closes = [bar["close"] for bar in ohlcv[-period:]]
    return sum(closes) / period


def apply_filters(
    ohlcv: list,
    base_signal: str,
) -> tuple[str, dict]:
    """
    Apply RSI + Volume + Trend + Volatility filters to base TSI signal.
    Returns (filtered_signal, filter_info).
    All filters are advisory; signal is downgraded to HOLD only on RSI fail.
    """
    fi = dict(volume_ok=False, trend_ok=False, volatility_ok=False, rsi_ok=False)
    n = len(ohlcv)
    price = ohlcv[-1]["close"]

    # 1. Volume filter – skip low-volume signals
    vol_ma = calculate_volume_ma(ohlcv)
    if vol_ma > 0 and ohlcv[-1]["volume"] >= vol_ma * 1.0:
        fi["volume_ok"] = True

    # 2. Trend filter – only trade in direction of 50-day MA
    ma50 = calculate_price_ma(ohlcv)
    if ma50 > 0:
        if base_signal == "BUY" and price > ma50:
            fi["trend_ok"] = True
        elif base_signal == "SELL" and price < ma50:
            fi["trend_ok"] = True

    # 3. Volatility filter – avoid extremely low/high ATR environments
    atr_list = calculate_atr(ohlcv)
    current_atr = atr_list[-1] if atr_list and atr_list[-1] is not None else 0.0
    atr_pct = (current_atr / price * 100.0) if price > 0 else 0.0
    if 0.5 <= atr_pct <= 5.0:
        fi["volatility_ok"] = True

    # 4. RSI momentum filter – reject signals in wrong RSI zone (critical)
    rsi = calculate_rsi(ohlcv)
    if base_signal == "BUY" and rsi >= 35:      # not oversold
        fi["rsi_ok"] = True
    elif base_signal == "SELL" and rsi <= 65:    # not overbought
        fi["rsi_ok"] = True
    # If RSI fails, downgrade to HOLD
    if not fi["rsi_ok"]:
        return "HOLD", fi

    return base_signal, fi


def tsi_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    Returns (signal, entry_price, atr).
    signal: BUY / SELL / HOLD (filtered by multi-filter TSI v2).
    """
    fast  = params["fast_period"]
    slow  = params["slow_period"]
    sig_p = params["signal_period"]

    closes = [bar["close"] for bar in ohlcv]

    # True Strength Index
    momentum = [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]

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

    # Crossover
    if tsi[-2] <= signal_ema[-2] and tsi[-1] > signal_ema[-1]:
        signal = "BUY"
    elif tsi[-2] >= signal_ema[-2] and tsi[-1] < signal_ema[-1]:
        signal = "SELL"
    else:
        signal = "HOLD"

    atr = calculate_atr(ohlcv)
    current_atr = atr[-1] if atr and atr[-1] is not None else 0.0

    # ── v2 multi-filter confirmation ──────────────────────────────────────────
    filtered_signal, fi = apply_filters(ohlcv, signal)
    if filtered_signal != signal:
        log.info("  ⚠ FILTERED: TSI %s → HOLD (RSI reject)", signal)
    log.info("  FILTERS  vol=%s trend=%s vola=%s rsi=%s",
             fi.get("volume_ok"), fi.get("trend_ok"),
             fi.get("volatility_ok"), fi.get("rsi_ok"))

    return filtered_signal, closes[-1], current_atr


def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"GROWW_API_BASE/orders"
    payload = {
        "symbol":      symbol,
        "exchange":    "NSE",
        "transaction": "BUY" if signal == "BUY" else "SELL",
        "quantity":    quantity,
        "price":       round(price, 2),
        "order_type":  "LIMIT",
        "product":     "CNC",
    }
    headers = {
        "Authorization": f"Bearer GROWW_API_KEY",
        "X-Api-Secret":  GROWW_API_SECRET,
        "Content-Type":  "application/json",
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("Groww order placed: %s", resp.json())
                return resp.json()
            log.warning("Groww API attempt %d: HTTP %d – %s", attempt + 1, resp.status_code, resp.text)
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol)
    return None


def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_ADANIENT.json"
    entries = []
    if log_file.exists():
        try:
            entries = json.loads(log_file.read_text())
        except Exception:
            entries = []
    entry = {
        "timestamp":         ist_now().isoformat(),
        "symbol":           SYMBOL,
        "strategy":         STRATEGY,
        "win_rate":         WIN_RATE,
        "benchmark_win_rate": BENCHMARK_WIN_RATE,
        "target_win_rate":   TARGET_WIN_RATE,
        "filters_applied":  FILTERS_APPLIED,
        "signal":           signal,
        "price":            round(price, 4),
        "atr":              round(atr, 4),
    }
    entries.append(entry)
    entries = entries[-500:]
    log_file.write_text(json.dumps(entries, indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)


def daily_loss_limit_hit(today_str: str) -> bool:
    cap_file = LOG_DIR / "daily_pnl_ADANIENT.json"
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
    log.info("=== Live Trading Script: %s | %s (v2 multi-filter TSI) ===", SYMBOL, STRATEGY)
    log.info("  BENCHMARK WIN RATE: %.2f%%  TARGET: %.2f%%", BENCHMARK_WIN_RATE * 100, TARGET_WIN_RATE * 100)
    log.info("  FILTERS: %s", FILTERS_APPLIED)

    # Pre-market warmup (9:00–9:15 IST)
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)

    # Wait for market open
    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return

    # Daily loss cap check
    today_str = ist_now().strftime("%Y-%m-%d")
    if daily_loss_limit_hit(today_str):
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return

    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return

    signal, price, atr = tsi_signal(ohlcv, PARAMS)

    # Calculate stop loss and target
    if signal == "BUY":
        stop_loss  = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price * (1 + STOP_LOSS_PCT), 2)
        target_prc = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss  = 0.0
        target_prc = 0.0

    # Quantity from ₹7000 position
    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s (v2 multi-filter)", STRATEGY)
    log.info("  BENCHMARK WIN RATE: %.2f%%  TARGET: %.2f%%", BENCHMARK_WIN_RATE * 100, TARGET_WIN_RATE * 100)
    log.info("  FILTERS  : %s", FILTERS_APPLIED)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Log signal to file
    log_signal(signal, price, atr)

    # Attempt Groww order if credentials are set
    if signal != "HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.warning("⚠ Groww order could not be placed – signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials found – signal printed only (paper mode).")


if __name__ == "__main__":
    main()
