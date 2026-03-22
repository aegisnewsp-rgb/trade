#!/usr/bin/env python3
"""
Live Trading Script - SUNPHARMA.NS
Strategy: MOMENTUM (RSI + Price Position within ATR range)
Win Rate:  N/A (default source)
Position:  ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_SUNPHARMA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SUNPHARMA")

SYMBOL         = "SUNPHARMA.NS"
STRATEGY       = "MOMENTUM"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008      # 0.8% of entry price
TARGET_MULT    = 4.0        # 4× ATR
DAILY_LOSS_CAP = 0.003      # 0.3%
PARAMS         = {"rsi_period": 14, "atr_period": 14, "rsi_buy": 55, "rsi_sell": 45}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"


def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)


def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)


def fetch_recent_data(days: int = 90, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {
                    "date": str(idx.date()),
                    "open":  float(r["Open"]),
                    "high":  float(r["High"]),
                    "low":   float(r["Low"]),
                    "close": float(r["Close"]),
                    "volume": int(r["Volume"]),
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
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi.append(100 - 100 / (1 + rs))
    return rsi


def momentum_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    Momentum strategy:
    - BUY:  RSI > rsi_buy  AND price within upper ATR band (strong momentum)
    - SELL: RSI < rsi_sell AND price within lower ATR band
    - HOLD: otherwise
    Returns (signal, current_price, current_atr)
    """
    rsi_period = params["rsi_period"]
    atr_period = params["atr_period"]
    rsi_buy    = params["rsi_buy"]
    rsi_sell   = params["rsi_sell"]
    atr_mult   = 2.0   # band width for momentum envelope

    rsi_vals = calculate_rsi(ohlcv, rsi_period)
    atr_vals = calculate_atr(ohlcv, atr_period)

    n = len(ohlcv)
    signals = ["HOLD"] * n
    for i in range(max(rsi_period, atr_period), n):
        rsi = rsi_vals[i]
        atr = atr_vals[i]
        if rsi is None or atr is None or atr == 0:
            continue
        price    = ohlcv[i]["close"]
        recent_high = max(ohlcv[j]["high"] for j in range(i - atr_period + 1, i + 1))
        recent_low  = min(ohlcv[j]["low"]  for j in range(i - atr_period + 1, i + 1))
        range_size = recent_high - recent_low

        # Momentum: price close to recent high + ATR confirming uptrend
        if rsi > rsi_buy and (price - recent_low) / (range_size + 1e-9) > 0.6:
            signals[i] = "BUY"
        elif rsi < rsi_sell and (recent_high - price) / (range_size + 1e-9) > 0.6:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    log.info("RSI=%.1f  ATR=%.4f  Signal=%s", current_rsi, current_atr, signals[-1])
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr


def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"{GROWW_API_BASE}/orders"
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
        "Authorization":  f"Bearer {GROWW_API_KEY}",
        "X-Api-Secret":   GROWW_API_SECRET,
        "Content-Type":   "application/json",
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("Groww order placed: %s", resp.json())
                return resp.json()
            log.warning(
                "Groww API attempt %d: HTTP %d – %s",
                attempt + 1, resp.status_code, resp.text,
            )
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol)
    return None


def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_SUNPHARMA.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol":   SYMBOL,
        "strategy": STRATEGY,
        "signal":   signal,
        "price":    round(price, 4),
        "atr":      round(atr, 4),
    })
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)


def daily_loss_limit_hit() -> bool:
    cap_file  = LOG_DIR / "daily_pnl_SUNPHARMA.json"
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
    log.info(
        "=== Live Trading Script: %s | %s | ₹%d position | %.1f%% SL | %.1f× ATR Target ===",
        SYMBOL, STRATEGY, POSITION, STOP_LOSS_PCT * 100, TARGET_MULT,
    )

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
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return

    signal, price, atr = momentum_signal(ohlcv, PARAMS)

    if signal == "BUY":
        stop_loss = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss = round(price * (1 + STOP_LOSS_PCT), 2)
        target_prc = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss, target_prc = 0.0, 0.0

    quantity = max(1, int(POSITION / price))

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
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


if __name__ == "__main__":
    main()
