#!/usr/bin/env python3
"""Live Trading Script - CYIENT.BO
Strategy: VWAP | Win Rate: 63.64% | Position: ₹7000 | Stop: 0.8% ATR | Target: 4.0× ATR"""

import os, sys, json, time, logging, requests
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "CYIENT.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("CYIENT")

SYMBOL         = "CYIENT.BO"
EXCHANGE       = "BSE"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

{GROWW_API_KEY}    = os.getenv("{GROWW_API_KEY}")
{GROWW_API_SECRET} = os.getenv("{GROWW_API_SECRET}")
{GROWW_API_BASE}   = "https://api.groww.in/v1"
IST_TZ_OFFSET    = 5.5

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty: raise ValueError("Empty dataframe")
            ohlcv = [{
                "date": str(idx.date()), "open": float(row["Open"]),
                "high": float(row["High"]), "low": float(row["Low"]),
                "close": float(row["Close"]), "volume": int(row["Volume"]),
            } for idx, row in df.iterrows()]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt+1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
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

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1: vwap.append(None)
        else:
            tp_sum  = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3 for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period = params["vwap_period"]; atr_mult = params["atr_multiplier"]
    vwap_vals = calculate_vwap(ohlcv, period); atr_vals = calculate_atr(ohlcv, period)
    signals = ["HOLD"] * len(ohlcv)
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None: continue
        price = ohlcv[i]["close"]; v = vwap_vals[i]; a = atr_vals[i]
        if price > v + a * atr_mult: signals[i] = "BUY"
        elif price < v - a * atr_mult: signals[i] = "SELL"
    return (signals[-1] if signals else "HOLD", ohlcv[-1]["close"],
            atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0)

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not {GROWW_API_KEY} or not {GROWW_API_SECRET}: return None
    url = f"{GROWW_API_BASE}/orders"
    payload = {"symbol": symbol, "exchange": EXCHANGE, "transaction": "BUY" if signal == "BUY" else "SELL",
                "quantity": quantity, "price": round(price, 2), "order_type": "LIMIT", "product": "CNC"}
    headers = {"Authorization": f"Bearer {GROWW_API_KEY}", "X-Api-Secret": "{GROWW_API_SECRET}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201): log.info("Groww order: %s", resp.json()); return resp.json()
            log.warning("Groww attempt %d: HTTP %d - %s", attempt+1, resp.status_code, resp.text)
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt+1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol); return None

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_CYIENT.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY, "signal": signal,
                     "price": round(price, 4), "atr": round(atr, 4)})
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ Rs.%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_CYIENT.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP: return True
        except Exception: pass
    return False

def main():
    log.info("=== Live Trading: %s | %s | Win Rate: 63.64%% ===", SYMBOL, STRATEGY)
    while is_pre_market():
        log.info("Pre-market warmup - waiting until 9:15 IST..."); time.sleep(30)
    if not is_market_open(): log.info("Market is closed. Exiting."); return
    if daily_loss_limit_hit(): log.warning("Daily loss cap (0.3%%) hit - skipping today."); return
    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30: log.error("Insufficient data for %s", SYMBOL); return
    signal, price, atr = vwap_signal(ohlcv, PARAMS)
    if signal == "BUY":
        stop_loss = round(price * (1 - STOP_LOSS_PCT), 2); target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss = round(price * (1 + STOP_LOSS_PCT), 2); target_prc = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss = 0.0; target_prc = 0.0
    quantity = max(1, int(POSITION / price))
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL   : %s", SYMBOL)
    log.info("  STRATEGY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : Rs.%.2f", price)
    log.info("  QTY      : %d shares (Rs.%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : Rs.%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : Rs.%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log_signal(signal, price, atr)
    if signal != "HOLD" and {GROWW_API_KEY} and {GROWW_API_SECRET}:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result: log.info("✓ Order executed via Groww: %s", result)
        else: log.warning("⚠ Groww order could not be placed - signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials found - signal printed only (paper mode).")

if __name__ == "__main__": main()
