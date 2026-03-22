#!/usr/bin/env python3
"""
Live Trading Script - BANKINDIA.NS (Bank of India)
Strategy: VWAP + Multi-Timeframe Confirmation
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Enhanced: Multi-timeframe confirmation (daily + 4hr VWAP alignment)
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
        logging.FileHandler(LOG_DIR / "live_BANKINDIA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_BANKINDIA")

SYMBOL         = "BANKINDIA.NS"
STRATEGY       = "VWAP_MTF"
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
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {
                    "date": str(idx.date()),
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
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

def fetch_4hr_data(days: int = 30, retries: int = 3) -> list | None:
    """Fetch 4-hourly data for multi-timeframe confirmation"""
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(interval="4h", period=f"{days}d")
            if df.empty:
                raise ValueError("Empty 4hr dataframe")
            ohlcv = [
                {
                    "date": str(idx.date()),
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
                    "close": float(r["Close"]),
                    "volume": int(r["Volume"]),
                }
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d 4hr candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching 4hr data: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All 4hr fetch attempts failed for %s", SYMBOL)
    return None

def calculate_vwap(ohlcv: list, params: dict) -> list:
    """Compute VWAP using cumulative typical price * volume."""
    period = params.get("vwap_period", 14)
    vwap_vals = []
    cum_pv, cum_vol = 0.0, 0.0
    for i, bar in enumerate(ohlcv):
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        cum_pv += typical * bar["volume"]
        cum_vol += bar["volume"]
        vwap_vals.append(cum_pv / cum_vol if cum_vol > 0 else typical)
    return vwap_vals

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

def vwap_signal_mtf(ohlcv: list, ohlcv_4hr: list, params: dict) -> tuple[str, float, float]:
    """
    VWAP with Multi-Timeframe Confirmation:
    - Daily VWAP for primary trend
    - 4hr VWAP for entry confirmation
    - Both must align for a valid signal
    """
    vwap_daily = calculate_vwap(ohlcv, params)
    vwap_4hr = calculate_vwap(ohlcv_4hr, params) if ohlcv_4hr else vwap_daily
    atr_vals  = calculate_atr(ohlcv, 14)
    
    if len(vwap_daily) < 2 or len(vwap_4hr) < 2:
        return "HOLD", ohlcv[-1]["close"], 0.0

    price_d = ohlcv[-1]["close"]
    vwap_d = vwap_daily[-1]
    prev_vwap_d = vwap_daily[-2]
    
    vwap_4 = vwap_4hr[-1]
    prev_vwap_4 = vwap_4hr[-2]

    # Daily crossover
    daily_cross_up = price_d > vwap_d and prev_vwap_d <= vwap_d
    daily_cross_dn = price_d < vwap_d and prev_vwap_d >= vwap_d
    
    # 4hr confirmation
    tf4_cross_up = price_d > vwap_4 and prev_vwap_4 <= vwap_4
    tf4_cross_dn = price_d < vwap_4 and prev_vwap_4 >= vwap_4
    
    # Both timeframes must agree
    if daily_cross_up and tf4_cross_up:
        signal = "BUY"
    elif daily_cross_dn and tf4_cross_dn:
        signal = "SELL"
    else:
        signal = "HOLD"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, price_d, current_atr

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        return None
    url = f"GROWW_API_BASE/orders"
    payload = {
        "symbol": symbol,
        "exchange": "NSE",
        "transaction": "BUY" if signal == "BUY" else "SELL",
        "quantity": quantity,
        "price": round(price, 2),
        "order_type": "LIMIT",
        "product": "CNC",
    }
    headers = {
        "Authorization": f"Bearer GROWW_API_KEY",
        "X-Api-Secret": GROWW_API_SECRET,
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("Groww order placed: %s", resp.json())
                return resp.json()
            log.warning(
                "Groww API attempt %d: HTTP %d – %s",
                attempt + 1,
                resp.status_code,
                resp.text,
            )
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol)
    return None

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_BANKINDIA.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entries.append(
        {
            "timestamp": ist_now().isoformat(),
            "symbol": SYMBOL,
            "strategy": STRATEGY,
            "signal": signal,
            "price": round(price, 4),
            "atr": round(atr, 4),
        }
    )
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_BANKINDIA.json"
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
        "=== Live Trading Script: %s | %s (Multi-Timeframe Conf.) ===",
        SYMBOL,
        STRATEGY,
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
    
    # Fetch 4hr data for multi-timeframe confirmation
    ohlcv_4hr = fetch_4hr_data(days=30)
    
    signal, price, atr = vwap_signal_mtf(ohlcv, ohlcv_4hr, PARAMS)
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
    log.info("  STRATEGY : %s (MTF Conf.)", STRATEGY)
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
        log.info(
            "📋 No Groww credentials found – signal printed only (paper mode)."
        )


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
    main()
