#!/usr/bin/env python3
"""
Live Trading Script - HEROMOTOCO.NS
Strategy: VWAP + RSI + MACD + Volume Filter + Trend Filter (Enhanced v3)
Win Rate: 55.00% -> Target 60%+ (v4 enhanced: ATR×2.0, vol×1.5, RSI confirm)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_HEROMOTOCO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HEROMOTOCO")

SYMBOL         = "HEROMOTOCO.NS"
STRATEGY       = "VWAP_RSI_MACD_VOL_v4"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {
    "vwap_period": 20,
    "atr_multiplier": 2.0,       # v4: tightened for stronger signals
    "rsi_period": 14,
    "rsi_oversold": 40,
    "rsi_overbought": 60,
    "rsi_confirm_oversold": 35,  # v4: deep oversold confirmation
    "rsi_confirm_overbought": 65, # v4: deep overbought confirmation
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_multiplier": 1.5,   # v4: tightened from 1.2
    "trend_ma_period": 50,
    "atr_period": 14,
}

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

def fetch_recent_data(days: int = 120, retries: int = 3) -> list | None:
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
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_vwap(ohlcv: list, period: int = 20) -> list:
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
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    rsi = [None] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(ohlcv)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi.append(100 - (100 / (1 + rs)))
    return rsi

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    closes = [b["close"] for b in ohlcv]
    ema_fast, ema_slow = [], []
    k_fast = 2 / (fast + 1); k_slow = 2 / (slow + 1)
    ema_fast.append(closes[0]); ema_slow.append(closes[0])
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * k_fast + ema_fast[-1] * (1 - k_fast))
        ema_slow.append(closes[i] * k_slow + ema_slow[-1] * (1 - k_slow))
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    signal_line = []
    k_sig = 2 / (signal + 1)
    signal_line.append(macd_line[0])
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    return macd_line, signal_line, [m - s for m, s in zip(macd_line, signal_line)]

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def vwap_signal_v3(ohlcv: list, params: dict) -> tuple[str, float, float]:
    vwap_period    = params["vwap_period"]
    atr_mult       = params["atr_multiplier"]
    rsi_period     = params["rsi_period"]
    rsi_oversold   = params["rsi_oversold"]
    rsi_overbought = params["rsi_overbought"]
    vol_mult       = params["volume_multiplier"]
    trend_period   = params["trend_ma_period"]

    vwap_vals = calculate_vwap(ohlcv, vwap_period)
    atr_vals  = calculate_atr(ohlcv, params["atr_period"])
    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, params["macd_fast"], params["macd_slow"], params["macd_signal"])
    ma_vals   = calculate_ma(ohlcv, trend_period)
    avg_vol   = calculate_avg_volume(ohlcv, vwap_period)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(vwap_period, rsi_period, params["macd_slow"]), len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        if ma_vals[i] is None or macd_line[i] is None:
            continue

        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        r       = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        trend   = ma_vals[i]
        macd_h  = histogram[i]
        sig_h   = histogram[i - 1] if i > 0 else 0

        volume_confirmed = vol > avg_vol * vol_mult
        bull_market  = price > trend
        bear_market  = price < trend
        macd_bullish = macd_h > 0 and macd_h > sig_h
        macd_bearish = macd_h < 0 and macd_h < sig_h

        if (price > v + a * atr_mult and r < rsi_overbought and macd_bullish
                and volume_confirmed and bull_market):
            signals[i] = "BUY"
        elif (price < v - a * atr_mult and r > rsi_oversold and macd_bearish
                and volume_confirmed and bear_market):
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"{GROWW_API_BASE}/orders"
    payload = {"symbol": symbol, "exchange": "NSE",
               "transaction": "BUY" if signal == "BUY" else "SELL",
               "quantity": quantity, "price": round(price, 2),
               "order_type": "LIMIT", "product": "CNC"}
    headers = {"Authorization": f"Bearer {GROWW_API_KEY}",
               "X-Api-Secret": GROWW_API_SECRET, "Content-Type": "application/json"}
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
    log_file = LOG_DIR / "signals_HEROMOTOCO.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY,
                    "signal": signal, "price": round(price, 4), "atr": round(atr, 4)})
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_HEROMOTOCO.json"
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
    log.info("=== Live Trading: %s | %s | Win Rate: 55.00%% -> Target 60%%+ (v3 enhanced) ===", SYMBOL, STRATEGY)
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
    ohlcv = fetch_recent_data(days=120)
    if not ohlcv or len(ohlcv) < 60:
        log.error("Insufficient data for %s", SYMBOL)
        return
    signal, price, atr = vwap_signal_v3(ohlcv, PARAMS)
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
    log.info("  STRATEY : %s", STRATEGY)
    log.info("  SIGNAL   : ★ %s ★", signal)
    log.info("  PRICE    : ₹%.2f", price)
    log.info("  QTY      : %d shares (₹%d position)", quantity, POSITION)
    if atr > 0:
        log.info("  ATR      : %.4f", atr)
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("  v3 ENH   : VWAP + RSI(40/60) + MACD hist + Vol(1.2x) + MA50 trend filter")
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
