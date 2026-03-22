#!/usr/bin/env python3
"""
Live Trading Script - SCHAEFFLER.NS
Strategy: VWAP (Volume Weighted Average Price)
Day's Change: +5.75% (Top 10 NSE Gainer)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests
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
        logging.FileHandler(LOG_DIR / "live_SCHAEFFLER.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_SCHAEFFLER")

SYMBOL         = "SCHAEFFLER.NS"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

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
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d", auto_adjust=True)
            if df.empty:
                log.warning(f"[{SYMBOL}] No data returned (attempt {attempt+1})")
                time.sleep(2)
                continue
            return df.reset_index().to_dict("records")
        except Exception as e:
            log.error(f"[{SYMBOL}] Fetch error: {e}")
            time.sleep(2)
    return None

def calculate_vwap(data: list, period: int = 14) -> float | None:
    try:
        closes = [d["Close"] for d in data[-period:]]
        volumes = [d["Volume"] for d in data[-period:]]
        if not closes or not volumes:
            return None
        tp = [(c * v) for c, v in zip(closes, volumes)]
        avg = sum(tp) / sum(volumes)
        return avg
    except Exception as e:
        log.error(f"VWAP error: {e}")
        return None

def calculate_atr(data: list, period: int = 14) -> float | None:
    try:
        if len(data) < period + 1:
            return None
        trs = []
        for i in range(1, min(len(data), period + 1)):
            high = data[i].get("High", 0)
            low = data[i].get("Low", 0)
            prev_close = data[i-1].get("Close", 0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else None
    except Exception as e:
        log.error(f"ATR error: {e}")
        return None

def calculate_rsi(prices: list, period: int = 14) -> float | None:
    try:
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except Exception as e:
        log.error(f"RSI error: {e}")
        return None

def get_live_price() -> float | None:
    try:
        ticker = yf.Ticker(SYMBOL)
        tod = ticker.history(period="5d", auto_adjust=True)
        if tod.empty:
            return None
        return float(tod["Close"].iloc[-1])
    except Exception as e:
        log.error(f"Price fetch error: {e}")
        return None

def trade_signal(data: list, live_price: float, vwap: float, atr: float, rsi: float) -> str | None:
    try:
        if live_price > vwap + (atr * PARAMS["atr_multiplier"]) and rsi < 65:
            return "BUY"
        elif live_price < vwap - (atr * PARAMS["atr_multiplier"]) and rsi > 35:
            return "SELL"
        return None
    except Exception as e:
        log.error(f"Signal error: {e}")
        return None

def load_state() -> dict:
    state_file = Path(__file__).parent / f"state_{SYMBOL.replace('.', '_')}.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {"position": 0, "entries": [], "daily_pnl": 0, "date": ""}

def save_state(state: dict):
    state_file = Path(__file__).parent / f"state_{SYMBOL.replace('.', '_')}.json"
    try:
        with open(state_file, "w") as f:
            json.dump(state, f, default=str)
    except Exception as e:
        log.error(f"State save error: {e}")

def run_live_trade():
    log.info(f"[{SYMBOL}] Starting live trade loop — Strategy: {STRATEGY}")
    state = load_state()
    today = ist_now().strftime("%Y-%m-%d")

    if state.get("date") != today:
        state = {"position": 0, "entries": [], "daily_pnl": 0, "date": today}

    data = fetch_recent_data()
    if not data:
        log.error(f"[{SYMBOL}] Could not fetch data")
        return

    vwap = calculate_vwap(data, PARAMS["vwap_period"])
    atr  = calculate_atr(data, PARAMS["atr_period"])
    prices = [d["Close"] for d in data]
    rsi   = calculate_rsi(prices, 14)

    log.info(f"[{SYMBOL}] VWAP={vwap:.2f} | ATR={atr:.2f} | RSI={rsi:.2f}" if all([vwap, atr, rsi]) else "[{SYMBOL}] Indicators unavailable")

    if not is_market_open():
        log.info(f"[{SYMBOL}] Market closed. Waiting...")
        return

    live_price = get_live_price()
    if live_price is None:
        log.error(f"[{SYMBOL}] Could not fetch live price")
        return

    signal = trade_signal(data, live_price, vwap, atr, rsi)
    log.info(f"[{SYMBOL}] Price={live_price:.2f} | Signal={signal}")

    if signal == "BUY" and state["position"] == 0:
        qty = POSITION / live_price
        log.info(f"[{SYMBOL}] BUY signal —qty={qty:.2f} @ {live_price:.2f}")
        state["position"] = qty
        state["entries"].append({"price": live_price, "time": str(ist_now())})
        save_state(state)
    elif signal == "SELL" and state["position"] > 0:
        log.info(f"[{SYMBOL}] SELL signal — closing position")
        state["position"] = 0
        state["entries"].clear()
        save_state(state)


def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API or paper trade.
    Uses Bracket Orders (BO) when GROWW_API_KEY is set.
    Falls back to paper trading otherwise.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    
    if signal == "BUY":
        # Calculate target and stop loss
        atr = price * 0.008  # 0.8% ATR approximation
        stop_loss = price - (atr * 1.0)  # 1x ATR stop
        target = price + (atr * 4.0)  # 4x ATR target
        # Use bracket order for BUY with target + stop loss
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
        atr = price * 0.008
        stop_loss = price + (atr * 1.0)
        target = price - (atr * 4.0)
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


if __name__ == "__main__":
    run_live_trade()
