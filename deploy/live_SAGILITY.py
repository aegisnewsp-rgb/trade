#!/usr/bin/env python3
"""
Live Trading Script - SAGILITY.NS
Strategy: RSI Reversal + Volume Spike (mean reversion near 52-week low)
Position: ₹5000 | Stop Loss: 1.2% ATR | Target: 3.5x ATR | Daily Loss Cap: 0.4%
Research: deploy/research/2026-03-22_sagility_research.md
"""

import os, sys, json, time, logging, requests

import sys
from pathlib import Path
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_SAGILITY.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SAGILITY")

SYMBOL         = "SAGILITY.NS"
STRATEGY       = "RSI_REVERSAL_VOLUME"
POSITION       = 5000
STOP_LOSS_PCT  = 0.012
TARGET_MULT    = 3.5
DAILY_LOSS_CAP = 0.004
PARAMS         = {
    "rsi_period": 14, "rsi_oversold": 35, "rsi_overbought": 65,
    "atr_period": 14, "volume_ma_period": 20, "volume_spike_mult": 1.5,
}

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
                {
                    "date": str(idx.date()),
                    "open": float(r["Open"]), "high": float(r["High"]),
                    "low": float(r["Low"]), "close": float(r["Close"]),
                    "volume": int(r["Volume"])
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
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi.append(100 - (100 / (1 + rs)))
    return rsi

def calculate_volume_ma(ohlcv: list, period: int = 20) -> list:
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            vol_ma.append(sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period)
    return vol_ma

def rsi_reversal_signal(ohlcv: list, params: dict) -> tuple:
    rsi_period   = params["rsi_period"]
    rsi_os       = params["rsi_oversold"]
    rsi_ob       = params["rsi_overbought"]
    atr_period   = params["atr_period"]
    vol_ma_period = params["volume_ma_period"]
    vol_spike    = params["volume_spike_mult"]

    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    atr_vals  = calculate_atr(ohlcv, atr_period)
    vol_ma    = calculate_volume_ma(ohlcv, vol_ma_period)

    signals = ["HOLD"] * len(ohlcv)
    for i in range(max(rsi_period, vol_ma_period), len(ohlcv)):
        if rsi_vals[i] is None or atr_vals[i] is None or vol_ma[i] is None:
            continue
        price     = ohlcv[i]["close"]
        prev_price = ohlcv[i - 1]["close"]
        rsi       = rsi_vals[i]
        atr       = atr_vals[i]
        vol_today = ohlcv[i]["volume"]
        vol_avg   = vol_ma[i]

        # BUY: RSI oversold + price bounce + volume spike
        if rsi < rsi_os and price > prev_price and vol_today > vol_avg * vol_spike:
            signals[i] = "BUY"
        # SELL: RSI overbought + price drop + volume spike
        elif rsi > rsi_ob and price < prev_price and vol_today > vol_avg * vol_spike:
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    current_vol = ohlcv[-1]["volume"] if ohlcv else 0
    vol_avg_val = vol_ma[-1] if vol_ma and vol_ma[-1] is not None else 1
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr, current_rsi, current_vol, vol_avg_val

def log_signal(signal: str, price: float, atr: float, rsi: float, vol: int, vol_avg: float):
    log_file = LOG_DIR / "signals_SAGILITY.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append({
        "timestamp": ist_now().isoformat(),
        "symbol": SYMBOL,
        "strategy": STRATEGY,
        "signal": signal,
        "price": round(price, 4),
        "atr": round(atr, 4),
        "rsi": round(rsi, 2),
        "volume": vol,
        "vol_ma": round(vol_avg, 0),
    })
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f, RSI=%.1f, Vol=%.0f, VolMA=%.0f)",
             signal, price, atr, rsi, vol, vol_avg)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_SAGILITY.json"
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
    log.info("=== Live Trading Script: %s | %s | Position: ₹%d ===", SYMBOL, STRATEGY, POSITION)
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)
    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.4%%) hit – skipping trading today.")
        return
    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return
    signal, price, atr, rsi, vol, vol_avg = rsi_reversal_signal(ohlcv, PARAMS)
    if signal == "BUY":
        stop_loss  = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price * (1 + STOP_LOSS_PCT), 2)
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
        log.info("  RSI      : %.1f", rsi)
        log.info("  VOLUME   : %.0f (MA20: %.0f, ratio: %.1fx)", vol, vol_avg, vol / vol_avg if vol_avg > 0 else 0)
        log.info("  STOP     : ₹%.2f  (%.1f%%)", stop_loss, STOP_LOSS_PCT * 100)
        log.info("  TARGET   : ₹%.2f  (%.1f× ATR)", target_prc, TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log_signal(signal, price, atr, rsi, vol, vol_avg)
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