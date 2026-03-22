#!/usr/bin/env python3
"""
Live Trading Script - BHEL.NS
Strategy: VWAP + Multi-Timeframe Confirmation
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Daily + 4hr VWAP alignment for confirmation
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "live_BHEL.log"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("live_BHEL")

SYMBOL = "BHEL.NS"
STRATEGY = "VWAP_MTF"
POSITION = 7000
STOP_LOSS_PCT = 0.008
TARGET_MULT = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")

def ist_now(): return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)
def is_market_open():
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def fetch_data(days=60):
    for attempt in range(3):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty: raise ValueError("Empty")
            return [{"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()]
        except Exception as e:
            log.warning("Attempt %d failed: %s", attempt+1, e); time.sleep(2**attempt)
    return None

def fetch_4hr(days=30):
    for attempt in range(3):
        try:
            df = yf.Ticker(SYMBOL).history(interval="4h", period=f"{days}d")
            if df.empty: raise ValueError("Empty")
            return [{"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()]
        except Exception as e:
            log.warning("4hr attempt %d failed: %s", attempt+1, e); time.sleep(2**attempt)
    return None

def calc_vwap(ohlcv, period=14):
    vwap, cum_pv, cum_vol = [], 0.0, 0.0
    for bar in ohlcv:
        tp = (bar["high"]+bar["low"]+bar["close"])/3
        cum_pv += tp*bar["volume"]; cum_vol += bar["volume"]
        vwap.append(cum_pv/cum_vol if cum_vol > 0 else tp)
    return vwap

def calc_atr(ohlcv, period=14):
    atr, prev = [], None
    for bar in ohlcv:
        tr = bar["high"]-bar["low"] if prev is None else max(bar["high"]-bar["low"], abs(bar["high"]-prev), abs(bar["low"]-prev))
        atr.append(tr if len(atr)<period-1 else (atr[-1]*(period-1)+tr)/period)
        prev = bar["close"]
    return atr

def signal_mtf(ohlcv, ohlcv_4hr, params):
    vwap_d = calc_vwap(ohlcv, params["vwap_period"])
    vwap_4 = calc_vwap(ohlcv_4hr, params["vwap_period"]) if ohlcv_4hr else vwap_d
    atr = calc_atr(ohlcv, 14)
    p = params["atr_multiplier"]
    price = ohlcv[-1]["close"]
    vd = vwap_d[-1]; v4 = vwap_4[-1]; a = atr[-1]
    if vd is None or a is None or v4 is None: return "HOLD", price, a or 0
    # Daily + 4hr must both confirm
    if price > vd+a*p and price > v4+a*p: return "BUY", price, a
    if price < vd-a*p and price < v4-a*p: return "SELL", price, a
    return "HOLD", price, a or 0

def main():
    log.info("=== %s | %s (MTF Confirmed) ===", SYMBOL, STRATEGY)
    if not is_market_open(): return
    ohlcv = fetch_data(90)
    if not ohlcv or len(ohlcv) < 30: return
    ohlcv_4hr = fetch_4hr(30)
    sig, price, atr = signal_mtf(ohlcv, ohlcv_4hr, PARAMS)
    sl = round(price*(1-STOP_LOSS_PCT), 2) if sig=="BUY" else round(price*(1+STOP_LOSS_PCT), 2) if sig=="SELL" else 0
    tp = round(price+TARGET_MULT*atr, 2) if sig=="BUY" else round(price-TARGET_MULT*atr, 2) if sig=="SELL" else 0
    log.info("Signal: %s @ ₹%.2f | SL: %.2f | TP: %.2f", sig, price, sl, tp)

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

if __name__ == "__main__": main()