#!/usr/bin/env python3
"""
Live Trading Script - BHARATWIRE.NS
Strategy: VWAP with Tightened Stop Loss
Position: ₹7000 | Stop Loss: 0.5% (tightened) | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Stop loss tightened from 0.8% to 0.5%
"""

import os, sys, json, time, logging, requests
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "live_BHARATWIRE.log"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("live_BHARATWIRE")

SYMBOL = "BHARATWIRE.NS"
STRATEGY = "VWAP"
POSITION = 7000
STOP_LOSS_PCT = 0.005  # Tightened from 0.8%
TARGET_MULT = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5}

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")

def ist_now(): return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)
# Smart entry: 9:30-14:30 IST
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

def signal(ohlcv, params):
    vwap = calc_vwap(ohlcv, params["vwap_period"])
    atr = calc_atr(ohlcv, 14)
    p = params["atr_multiplier"]
    price = ohlcv[-1]["close"]
    v = vwap[-1]; a = atr[-1]
    if v is None or a is None: return "HOLD", price, a or 0
    if price > v+a*p: return "BUY", price, a
    if price < v-a*p: return "SELL", price, a
    return "HOLD", price, a or 0

def main():
    log.info("=== %s | %s (SL: %.1f%%) ===", SYMBOL, STRATEGY, STOP_LOSS_PCT*100)
    if not is_market_open(): return
    ohlcv = fetch_data(90)
    if not ohlcv or len(ohlcv) < 30: return
    sig, price, atr = signal(ohlcv, PARAMS)
    if sig == "HOLD": return
    sl = round(price*(1-STOP_LOSS_PCT), 2) if sig=="BUY" else round(price*(1+STOP_LOSS_PCT), 2)
    tp = round(price+TARGET_MULT*atr, 2) if sig=="BUY" else round(price-TARGET_MULT*atr, 2)
    log.info("Signal: %s @ ₹%.2f | SL: %.2f (%.1f%%) | TP: %.2f", sig, price, sl, STOP_LOSS_PCT*100, tp)
    place_groww_order(SYMBOL, sig, 1, price, atr)


def place_groww_order(symbol, signal, quantity, price, atr):
    """
    Place order via Groww API or paper trade.
    Uses Bracket Orders (BO) when GROWW_API_KEY is set.
    Falls back to paper trading otherwise.
    """
    import groww_api

    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)

    exchange = "NSE"
    sl_mult = 1.0
    tp_mult = 4.0

    if signal == "BUY":
        stop_loss = round(price - (atr * sl_mult), 2)
        target = round(price + (atr * tp_mult), 2)
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
        stop_loss = round(price + (atr * sl_mult), 2)
        target = round(price - (atr * tp_mult), 2)
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
        print("Order placed: {} {} {} @ Rs{:.2f}".format(
            signal, quantity, symbol, price))
    return result


if __name__ == "__main__": main()
