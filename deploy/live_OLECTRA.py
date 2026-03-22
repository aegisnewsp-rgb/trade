#!/usr/bin/env python3
"""
Live Trading Script - OLECTRA.NS (Olectra Greentech Limited)
Strategy: ADX_TREND (Average Directional Index)
Selected: +9.65% momentum on 2026-03-20
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests, math
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_OLECTRA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_OLECTRA")

SYMBOL         = "OLECTRA.NS"
STRATEGY       = "ADX_TREND"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"adx_period": 14, "adx_threshold": 25}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
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

def adx_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    ADX Trend strategy: BUY when +DI > -DI with strong trend (ADX > threshold),
    SELL when -DI > +DI. Directional movement crossover.
    """
    period    = params["adx_period"]
    threshold = params["adx_threshold"]

    high  = [bar["high"]  for bar in ohlcv]
    low   = [bar["low"]   for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]

    tr_list = [high[0] - low[0]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(ohlcv))
    ]

    plus_dm  = [0.0] * len(ohlcv)
    minus_dm = [0.0] * len(ohlcv)
    for i in range(1, len(ohlcv)):
        up_move   = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i]  = up_move   if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(ohlcv) < period * 2:
        return "HOLD", close[-1], 0.0

    tr_smooth   = ema(tr_list, period)
    plus_dm_sm  = ema(plus_dm, period)
    minus_dm_sm = ema(minus_dm, period)

    plus_di  = [100 * plus_dm_sm[i]  / tr_smooth[i] if tr_smooth[i]  else 0 for i in range(len(ohlcv))]
    minus_di = [100 * minus_dm_sm[i] / tr_smooth[i] if tr_smooth[i]  else 0 for i in range(len(ohlcv))]

    dx = [100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          if (plus_di[i] + minus_di[i]) else 0 for i in range(len(ohlcv))]
    adx_vals = ema(dx, period)

    if len(adx_vals) < 2:
        return "HOLD", close[-1], 0.0

    if adx_vals[-1] > threshold:
        if plus_di[-1] > minus_di[-1] and plus_di[-2] <= minus_di[-2]:
            signal = "BUY"
        elif minus_di[-1] > plus_di[-1] and minus_di[-2] <= plus_di[-2]:
            signal = "SELL"
        else:
            signal = "HOLD"
    else:
        signal = "HOLD"

    atr_vals  = calculate_atr(ohlcv, period)
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, close[-1], current_atr

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"GROWW_API_BASE/orders"
    payload = {
        "symbol": symbol, "exchange": "NSE",
        "transaction": "BUY" if signal == "BUY" else "SELL",
        "quantity": quantity, "price": round(price, 2),
        "order_type": "LIMIT", "product": "CNC"
    }
    headers = {
        "Authorization": f"Bearer GROWW_API_KEY",
        "X-Api-Secret": GROWW_API_SECRET,
        "Content-Type": "application/json"
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
    log_file = LOG_DIR / "signals_OLECTRA.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol": SYMBOL, "strategy": STRATEGY,
        "signal": signal, "price": round(price, 4), "atr": round(atr, 4)
    })
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_OLECTRA.json"
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
    log.info("=== Live Trading Script: %s | %s ===", SYMBOL, STRATEGY)
    log.info("Selected: +9.65%% momentum on 2026-03-20 | Green Energy / EV sector")
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
    signal, price, atr = adx_signal(ohlcv, PARAMS)
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
