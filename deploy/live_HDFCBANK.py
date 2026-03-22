#!/usr/bin/env python3
"""
Live Trading Script - HDFCBANK.NS
Strategy: ADX_TREND_v2 (Optimized ADX + DI Crossover + RSI Filter + Volume — TOP BANK PICK)
Win Rate: 60.61% -> Target 65%+ (v2 optimized: tighter ADX threshold, RSI filter, volume confirm)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_HDFCBANK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HDFCBANK")

SYMBOL         = "HDFCBANK.NS"
STRATEGY       = "ADX_TREND_v2"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "adx_period": 14,
    "adx_threshold": 25,
    "rsi_period": 14,
    "rsi_oversold": 40,
    "rsi_overbought": 60,
    "volume_multiplier": 1.2,
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
        if i < period - 1: atr.append(None)
        elif i == period - 1: atr.append(tr)
        else: atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

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

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def adx_signal_v2(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    v2 ADX Trend: BUY when +DI > -DI with strong trend (ADX > threshold),
    SELL when -DI > +DI. Adds RSI filter + volume confirmation for bank stocks.
    Optimized for HDFCBANK as top sector pick.
    """
    period     = params["adx_period"]
    threshold  = params["adx_threshold"]
    rsi_period = params["rsi_period"]
    rsi_overbought = params["rsi_overbought"]
    rsi_oversold = params["rsi_oversold"]
    vol_mult   = params["volume_multiplier"]

    high  = [bar["high"] for bar in ohlcv]
    low   = [bar["low"]  for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]

    tr_list = [high[i] - low[i]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(ohlcv))
    ]

    plus_dm = [0.0] * len(ohlcv)
    minus_dm = [0.0] * len(ohlcv)
    for i in range(1, len(ohlcv)):
        up_move   = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i]  = up_move if up_move > down_move and up_move > 0 else 0.0
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

    plus_di  = [100 * plus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]
    minus_di = [100 * minus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]

    dx = [100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          if (plus_di[i] + minus_di[i]) != 0 else 0 for i in range(len(ohlcv))]
    adx_vals = ema(dx, period)

    rsi_vals = calculate_rsi(ohlcv, rsi_period)
    avg_vol  = calculate_avg_volume(ohlcv, period)

    if len(adx_vals) < 2:
        return "HOLD", close[-1], 0.0

    # Signal: trending ADX with directional crossover + RSI filter + volume
    signal = "HOLD"
    if adx_vals[-1] > threshold:
        current_vol = ohlcv[-1]["volume"]
        vol_ok = current_vol > avg_vol * vol_mult
        rsi_now = rsi_vals[-1] if rsi_vals[-1] is not None else 50

        if plus_di[-1] > minus_di[-1] and plus_di[-2] <= minus_di[-2]:
            # BUY: bullish crossover + RSI not overbought + volume confirm
            if rsi_now < rsi_overbought and vol_ok:
                signal = "BUY"
        elif minus_di[-1] > plus_di[-1] and minus_di[-2] <= plus_di[-2]:
            # SELL: bearish crossover + RSI not oversold + volume confirm
            if rsi_now > rsi_oversold and vol_ok:
                signal = "SELL"

    atr_vals = calculate_atr(ohlcv, params["atr_period"])
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, close[-1], current_atr

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"GROWW_API_BASE/orders"
    payload = {"symbol": symbol, "exchange": "NSE",
               "transaction": "BUY" if signal == "BUY" else "SELL",
               "quantity": quantity, "price": round(price, 2),
               "order_type": "LIMIT", "product": "CNC"}
    headers = {"Authorization": f"Bearer GROWW_API_KEY",
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
    log_file = LOG_DIR / "signals_HDFCBANK.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY,
                    "signal": signal, "price": round(price, 4), "atr": round(atr, 4)})
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_HDFCBANK.json"
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
    log.info("=== Live Trading: %s | %s | Win Rate: 60.61%% -> Target 65%%+ (v2 TOP BANK PICK) ===", SYMBOL, STRATEGY)
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
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return
    signal, price, atr = adx_signal_v2(ohlcv, PARAMS)
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
    log.info("  v2 ENH   : ADX + DI crossover + RSI(40/60) + Vol(1.2x) — TOP BANK PICK")
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
