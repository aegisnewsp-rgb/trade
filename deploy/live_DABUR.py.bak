#!/usr/bin/env python3
"""
Live Trading Script - DABUR.NS
Strategy: ADX_TREND_v2 (Enhanced: lower threshold + volume + trend filter)
Win Rate: 57.32% -> Target 62%+ (v2 enhanced)
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
        logging.FileHandler(LOG_DIR / "live_DABUR.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_DABUR")

SYMBOL         = "DABUR.NS"
STRATEGY       = "ADX_TREND_v2"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS = {
    "adx_period": 14,
    "adx_threshold": 20,         # lowered from 25 for more signals
    "di_crossover": 8,           # lowered from 10 for more signals
    "volume_multiplier": 1.2,    # new: volume confirmation
    "trend_ma_period": 50,       # new: trend filter
    "atr_period": 14,
}

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

def fetch_recent_data(days: int = 120, retries: int = 3) -> list | None:
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

def calculate_adx(ohlcv: list, period: int = 14) -> tuple[list, list, list]:
    closes = [b["close"] for b in ohlcv]
    highs  = [b["high"]  for b in ohlcv]
    lows   = [b["low"]   for b in ohlcv]
    tr_list, plus_dm, minus_dm = [], [], []
    prev_high, prev_low = None, None
    for i, bar in enumerate(ohlcv):
        tr = bar["high"] - bar["low"] if i == 0 else max(bar["high"] - bar["low"], abs(bar["high"] - closes[i-1]), abs(bar["low"] - closes[i-1]))
        tr_list.append(tr)
        if i == 0:
            plus_dm.append(0.0); minus_dm.append(0.0)
        else:
            high_diff = bar["high"] - prev_high
            low_diff  = prev_low - bar["low"]
            plus_dm.append(max(high_diff, 0) if high_diff > low_diff else 0.0)
            minus_dm.append(max(low_diff, 0) if low_diff > high_diff else 0.0)
        prev_high = bar["high"]; prev_low = bar["low"]
    atr_smooth, plus_di, minus_di, adx_vals = [], [], [], []
    for i in range(len(ohlcv)):
        if i < period - 1:
            atr_smooth.append(None); plus_di.append(None); minus_di.append(None); adx_vals.append(None)
        elif i == period - 1:
            atr_smooth.append(sum(tr_list[i-period+1:i+1]))
            pdm = sum(plus_dm[i-period+1:i+1]); mdm = sum(minus_dm[i-period+1:i+1])
            plus_di.append((pdm/atr_smooth[-1]*100) if atr_smooth[-1] > 0 else 0)
            minus_di.append((mdm/atr_smooth[-1]*100) if atr_smooth[-1] > 0 else 0)
            dx = abs(plus_di[-1]-minus_di[-1])/(plus_di[-1]+minus_di[-1])*100 if (plus_di[-1]+minus_di[-1])>0 else 0
            adx_vals.append(dx)
        else:
            atr_smooth.append((atr_smooth[-1]*(period-1)+tr_list[i])/period)
            pdm = (plus_dm[i]+plus_dm[i-1])/2; mdm = (minus_dm[i]+minus_dm[i-1])/2
            pdi = (pdm/atr_smooth[-1]*100) if atr_smooth[-1]>0 else 0
            mdi = (mdm/atr_smooth[-1]*100) if atr_smooth[-1]>0 else 0
            plus_di.append(pdi); minus_di.append(mdi)
            dx = abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0
            adx_vals.append((adx_vals[-1]*(period-1)+dx)/period)
    return adx_vals, plus_di, minus_di

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

def adx_trend_signal_v2(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period       = params["adx_period"]
    threshold    = params["adx_threshold"]
    di_cross     = params["di_crossover"]
    trend_period = params["trend_ma_period"]
    vol_mult     = params["volume_multiplier"]

    adx_vals, plus_di, minus_di = calculate_adx(ohlcv, period)
    ma_vals   = calculate_ma(ohlcv, trend_period)
    avg_vol   = calculate_avg_volume(ohlcv, period)
    atr_vals  = calculate_atr(ohlcv, params["atr_period"])

    signals = ["HOLD"] * len(ohlcv)
    for i in range(period + trend_period, len(ohlcv)):
        if adx_vals[i] is None or plus_di[i] is None or minus_di[i] is None:
            continue
        if ma_vals[i] is None:
            continue

        price   = ohlcv[i]["close"]
        trend   = ma_vals[i]
        vol     = ohlcv[i]["volume"]
        volume_confirmed = vol > avg_vol * vol_mult

        # Trend filter: only trade in direction of MA
        bull_market = price > trend
        bear_market = price < trend

        # ADX must confirm trend strength
        if adx_vals[i] < threshold:
            continue

        di_gap = plus_di[i] - minus_di[i] if plus_di[i] > minus_di[i] else minus_di[i] - plus_di[i]

        if (plus_di[i] > minus_di[i] and di_gap > di_cross and bull_market and volume_confirmed):
            signals[i] = "BUY"
        elif (minus_di[i] > plus_di[i] and di_gap > di_cross and bear_market and volume_confirmed):
            signals[i] = "SELL"

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
    log_file = LOG_DIR / "signals_DABUR.json"
    entries = []
    if log_file.exists():
        try: entries = json.loads(log_file.read_text())
        except Exception: pass
    entries.append({"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY, "signal": signal, "price": round(price, 4), "atr": round(atr, 4)})
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_DABUR.json"
    today_str = ist_now().strftime("%Y-%m-%d")
    if cap_file.exists():
        try:
            data = json.loads(cap_file.read_text())
            if data.get("date") == today_str and data.get("loss_pct", 0) >= DAILY_LOSS_CAP:
                return True
        except Exception: pass
    return False

def main():
    log.info("=== Live Trading: %s | %s | Win Rate: 57.32%% -> Target 62%%+ (v2 enhanced) ===", SYMBOL, STRATEGY)
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST..."); time.sleep(30)
    if not is_market_open():
        log.info("Market is closed. Exiting."); return
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today."); return
    log.info("Market is open. Fetching data...")
    ohlcv = fetch_recent_data(days=120)
    if not ohlcv or len(ohlcv) < 60:
        log.error("Insufficient data for %s", SYMBOL); return
    signal, price, atr = adx_trend_signal_v2(ohlcv, PARAMS)
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
    log.info("  v2 ENH   : ADX(20) + DI-gap(8) + Vol(1.2x) + MA50 trend filter")
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
