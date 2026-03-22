#!/usr/bin/env python3
"""
Live Trading Script - ALKEM.NS
Strategy: PARABOLIC_SAR
Win Rate: 57.92%
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
        logging.FileHandler(LOG_DIR / "live_ALKEM.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ALKEM")

SYMBOL         = "ALKEM.NS"
STRATEGY       = "PARABOLIC_SAR"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"af_start": 0.02, "af_increment": 0.02, "af_max": 0.2}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"
IST_TZ_OFFSET = 5.5

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
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty: raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(row["Open"]),
                 "high": float(row["High"]), "low": float(row["Low"]),
                 "close": float(row["Close"]), "volume": int(row["Volume"])}
                for idx, row in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
    return None

def calculate_atr(ohlcv: list, period: int = 14) -> list:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if prev_close is None else max(
            bar["high"] - bar["low"],
            abs(bar["high"] - prev_close),
            abs(bar["low"]  - prev_close),
        )
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_psar(ohlcv: list, af_start: float = 0.02, af_inc: float = 0.02, af_max: float = 0.2) -> tuple[list, list]:
    highs  = [b["high"]  for b in ohlcv]
    lows    = [b["low"]   for b in ohlcv]
    psar    = [0.0] * len(ohlcv)
    trend   = [1] * len(ohlcv)
    ep      = [highs[0]] * len(ohlcv)
    af_list = [af_start] * len(ohlcv)
    psar[0] = lows[0]
    for i in range(1, len(ohlcv)):
        prev_psar  = psar[i - 1]
        prev_trend = trend[i - 1]
        prev_ep    = ep[i - 1]
        prev_af    = af_list[i - 1]
        if prev_trend == 1:
            psar[i] = prev_psar + prev_af * (prev_ep - prev_psar)
            if lows[i] < psar[i]:
                trend[i] = -1; psar[i] = prev_ep; ep[i] = lows[i]; af_list[i] = af_start
            else:
                trend[i] = 1; ep[i] = max(ep[i - 1], highs[i]); af_list[i] = min(prev_af + af_inc, af_max)
        else:
            psar[i] = prev_psar - prev_af * (prev_psar - prev_ep)
            if highs[i] > psar[i]:
                trend[i] = 1; psar[i] = ep[i - 1]; ep[i] = highs[i]; af_list[i] = af_start
            else:
                trend[i] = -1; ep[i] = min(ep[i - 1], lows[i]); af_list[i] = min(prev_af + af_inc, af_max)
    return psar, trend

def psar_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    af_start = params["af_start"]
    af_inc   = params["af_increment"]
    af_max   = params["af_max"]
    psar_vals, trend = calculate_psar(ohlcv, af_start, af_inc, af_max)
    signals = ["HOLD"] * len(ohlcv)
    for i in range(2, len(ohlcv)):
        if trend[i] == 1 and trend[i - 1] == -1:
            signals[i] = "BUY"
        elif trend[i] == -1 and trend[i - 1] == 1:
            signals[i] = "SELL"
    atr_vals       = calculate_atr(ohlcv)
    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def place_groww_order(symbol: str, signal: str, quantity: int, price: float) -> dict | None:
    if not GROWW_API_KEY or not GROWW_API_SECRET: return None
    url = f"GROWW_API_BASE/orders"
    payload = {"symbol": symbol, "exchange": "NSE",
               "transaction": "BUY" if signal == "BUY" else "SELL",
               "quantity": quantity, "price": round(price, 2),
               "order_type": "LIMIT", "product": "CNC"}
    headers = {"Authorization": f"Bearer GROWW_API_KEY", "X-Api-Secret": GROWW_API_SECRET, "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                log.info("Groww order placed: %s", resp.json()); return resp.json()
            log.warning("Groww API attempt %d: HTTP %d – %s", attempt + 1, resp.status_code, resp.text)
        except Exception as e:
            log.warning("Groww order attempt %d failed: %s", attempt + 1, e)
        time.sleep(2 ** attempt)
    log.error("Groww order failed after 3 retries for %s", symbol); return None

def log_signal(signal: str, price: float, atr: float):
    log_file = LOG_DIR / "signals_ALKEM.json"
    entries = []
    if log_file.exists():
        try: entries = json.loads(log_file.read_text())
        except Exception: pass
    entries.append({"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY, "signal": signal, "price": round(price, 4), "atr": round(atr, 4)})
    entries[-500:]
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_ALKEM.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception: pass
    return False

def main():
    log.info("=== Live Trading: %s | %s | Win Rate: 57.92%% ===", SYMBOL, STRATEGY)
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST..."); time.sleep(30)
    if not is_market_open():
        log.info("Market is closed. Exiting."); return
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today."); return
    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL); return
    signal, price, atr = psar_signal(ohlcv, PARAMS)
    if signal == "BUY":
        stop_loss  = round(price * (1 - STOP_LOSS_PCT), 2)
        target_prc = round(price + TARGET_MULT * atr, 2)
    elif signal == "SELL":
        stop_loss  = round(price * (1 + STOP_LOSS_PCT), 2)
        target_prc = round(price - TARGET_MULT * atr, 2)
    else:
        stop_loss = target_prc = 0.0
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
        if result: log.info("✓ Order executed via Groww: %s", result)
        else: log.warning("⚠ Groww order could not be placed.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials – signal printed only (paper mode).")


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


if __name__ == "__main__": main()
