#!/usr/bin/env python3
"""
Live Trading Script - TCS.NS
Strategy: VWAP + ADVANCED ALPHA
Enhanced: Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime Filter
Win Rate: 63.64% → Target: 70%+
Position: ₹7000 | Daily Loss Cap: 0.3%
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
        logging.FileHandler(LOG_DIR / "live_TCS.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_TCS")

SYMBOL = "TCS.NS"
STRATEGY = "VWAP_ALPHA"
POSITION = 7000
DAILY_LOSS_CAP = 0.003
PARAMS = {"vwap_period": 14, "atr_multiplier": 1.5}

# ADVANCED ALPHA CONFIG
NIFTY_SYMBOL = "^NSEI"
ENTRY_WAIT_MINUTES = 15
NO_ENTRY_AFTER = dtime(14, 30)
BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END = dtime(12, 0)

ENTRY_VWAP_PCT = 0.005
ENTRY_RSI_MIN = 55
ENTRY_VOL_MULT = 1.2

SL_ATR_MULT = 1.5
MAX_SL_PCT = 0.02
TRAIL_TRIGGER_PCT = 0.01

TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in/v1"

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def can_new_entry() -> bool:
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early - waiting for 9:30 AM candle close")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM - no new entries today")
        return False
    return True

def fetch_recent_data(symbol: str, days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(symbol).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", symbol)
    return None

def fetch_intraday_15min(symbol: str, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval="15m", period="1d")
            if df.empty:
                return None
            ohlcv = [
                {"time": idx, "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d for intraday %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
    return None

def fetch_intraday_1hr(symbol: str, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(interval="1h", period="5d")
            if df.empty:
                return None
            ohlcv = [
                {"time": idx, "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d for 1hr %s: %s", attempt + 1, retries, symbol, e)
            time.sleep(2 ** attempt)
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

def calculate_vwap(ohlcv: list) -> list:
    vwap, cum_pv, cum_vol = [], 0.0, 0
    for bar in ohlcv:
        tp = (bar["high"] + bar["low"] + bar["close"]) / 3
        cum_pv += tp * bar["volume"]
        cum_vol += bar["volume"]
        vwap.append(cum_pv / cum_vol if cum_vol > 0 else 0.0)
    return vwap

def calculate_rsi(prices: list, period: int = 14) -> list:
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    return [100 - (100 / (1 + rs))]

def calculate_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return sum(prices[-period:]) / period

def get_market_regime() -> tuple[str, float]:
    nifty_data = fetch_recent_data(NIFTY_SYMBOL, days=40)
    if not nifty_data or len(nifty_data) < 25:
        log.warning("Could not fetch NIFTY data - assuming UPTREND")
        return "UPTREND", 1.0
    
    nifty_closes = [bar["close"] for bar in nifty_data]
    nifty_sma20 = calculate_sma(nifty_closes, 20)
    nifty_current = nifty_closes[-1]
    ratio = nifty_current / nifty_sma20
    
    if ratio > 1.02:
        regime = "UPTREND"
    elif ratio < 0.98:
        regime = "DOWNTREND"
    else:
        regime = "RANGE"
    
    log.info("📊 NIFTY Regime: %s | Current: %.2f | SMA20: %.2f | Ratio: %.3f", 
             regime, nifty_current, nifty_sma20, ratio)
    return regime, ratio

def get_position_size_multiplier(regime: str) -> float:
    if regime == "DOWNTREND":
        return 0.0
    elif regime == "RANGE":
        return 0.5
    return 1.0

def smart_entry_conditions_met(intraday_15m: list, intraday_1hr: list, 
                                daily_ohlcv: list, current_price: float) -> tuple[bool, str]:
    if not intraday_15m or len(intraday_15m) < 2:
        return False, "Waiting for 15min data..."
    
    now = ist_now()
    if now.hour == 9 and now.minute < 30:
        return False, "⏳ Waiting for 9:30 AM candle close"
    
    vols = [bar["volume"] for bar in daily_ohlcv[-20:]]
    avg_vol_20 = sum(vols) / len(vols) if vols else 1
    
    current_vol = intraday_15m[-1]["volume"] if intraday_15m else 0
    vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
    
    vwap_15m = calculate_vwap(intraday_15m)
    vwap_val = vwap_15m[-1] if vwap_15m else current_price
    
    closes_15m = [bar["close"] for bar in intraday_15m]
    rsi_15m = calculate_rsi(closes_15m)[-1] if len(closes_15m) > 14 else 50
    
    vwap_1hr = calculate_vwap(intraday_1hr) if intraday_1hr else []
    vwap_val_1hr = vwap_1hr[-1] if vwap_1hr else current_price
    
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    log.info("📊 Smart Entry Check | Price: %.2f | VWAP_15m: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio)
    
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    cond3 = vol_ratio > ENTRY_VOL_MULT
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    
    if cond1 and cond2 and cond3 and mt_confirmation:
        reasons = []
        if cond1: reasons.append(f"Price>VWAP+0.5%")
        if cond2: reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond3: reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        return True, "✅ SMART ENTRY: " + " + ".join(reasons)
    
    reasons = []
    if not cond1: reasons.append(f"Price<VWAP+0.5% ({current_price/vwap_val-1:.2%})")
    if not cond2: reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3: reasons.append(f"Vol low ({vol_ratio:.2f}x)")
    return False, "❌ Entry conditions not met: " + " | ".join(reasons)

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period = params["vwap_period"]
    atr_mult = params["atr_multiplier"]
    vwap_vals = calculate_vwap(ohlcv)
    atr_vals = calculate_atr(ohlcv, period)
    signals = ["HOLD"] * len(ohlcv)
    
    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue
        price = ohlcv[i]["close"]
        v, a = vwap_vals[i], atr_vals[i]
        if price > v + a * atr_mult:
            signals[i] = "BUY"
        elif price < v - a * atr_mult:
            signals[i] = "SELL"
    
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr

def calculate_dynamic_sl(entry_price: float, atr: float) -> float:
    sl_atr = entry_price - (SL_ATR_MULT * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    stop_loss = max(sl_atr, sl_max)
    log.info("🎯 Dynamic SL: ATR-based=%.2f | Max-2%%=%.2f | Selected=%.2f", sl_atr, sl_max, stop_loss)
    return round(stop_loss, 2)

def calculate_targets(entry_price: float, stop_loss: float) -> tuple[list, list]:
    risk = entry_price - stop_loss
    t1 = round(entry_price + (TARGET_1_MULT * risk), 2)
    t2 = round(entry_price + (TARGET_2_MULT * risk), 2)
    t3 = round(entry_price + (TARGET_3_MULT * risk), 2)
    
    targets = [
        {"level": 1, "price": t1, "risk_mult": TARGET_1_MULT, "exit_pct": 0.33, "desc": "Secure 1.5×"},
        {"level": 2, "price": t2, "risk_mult": TARGET_2_MULT, "exit_pct": 0.33, "desc": "Main 3×"},
        {"level": 3, "price": t3, "risk_mult": TARGET_3_MULT, "exit_pct": 0.34, "desc": "Stretch 5×"},
    ]
    return targets

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

def log_signal(signal: str, price: float, atr: float, targets: list = None, regime: str = "UNKNOWN"):
    log_file = LOG_DIR / "signals_TCS.json"
    entries = json.loads(log_file.read_text()) if log_file.exists() else []
    entry = {"timestamp": ist_now().isoformat(), "symbol": SYMBOL, "strategy": STRATEGY,
             "signal": signal, "price": round(price, 4), "atr": round(atr, 4),
             "regime": regime}
    if targets:
        entry["targets"] = [{"t"+str(t["level"]): t["price"]} for t in targets]
    entries.append(entry)
    log_file.write_text(json.dumps(entries[-500:], indent=2))
    log.info("Signal logged: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)

def daily_loss_limit_hit() -> bool:
    cap_file = LOG_DIR / "daily_pnl_TCS.json"
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
    log.info("=" * 70)
    log.info("🚀 ADVANCED ALPHA - TCS.NS | VWAP Strategy Enhanced")
    log.info("   Smart Entry | Dynamic ATR Stops | 3-Tier Targets | Market Regime")
    log.info("=" * 70)
    
    while is_pre_market():
        log.info("Pre-market warmup – waiting until 9:15 IST...")
        time.sleep(30)
    
    if not is_market_open():
        log.info("Market is closed. Exiting.")
        return
    
    today_str = ist_now().strftime("%Y-%m-%d")
    if daily_loss_limit_hit():
        log.warning("Daily loss cap (0.3%%) hit – skipping trading today.")
        return
    
    log.info("\n📊 [STEP 1] Checking Market Regime (NIFTY)...")
    regime, regime_ratio = get_market_regime()
    pos_mult = get_position_size_multiplier(regime)
    
    if regime == "DOWNTREND":
        log.warning("🔴 DOWNTREND - No new entries. Will hold existing positions only.")
    
    log.info("Market is open. Fetching data...")
    
    daily_ohlcv = fetch_recent_data(SYMBOL, days=90)
    if not daily_ohlcv or len(daily_ohlcv) < 30:
        log.error("Insufficient data for %s", SYMBOL)
        return
    
    intraday_15m = fetch_intraday_15min(SYMBOL)
    intraday_1hr = fetch_intraday_1hr(SYMBOL)
    
    signal, price, atr = vwap_signal(daily_ohlcv, PARAMS)
    log.info("\n📊 [STEP 2] VWAP Signal: %s @ ₹%.2f (ATR=%.4f)", signal, price, atr)
    
    entry_allowed = True
    entry_reason = ""
    
    if signal == "BUY" and pos_mult > 0:
        if not can_new_entry():
            entry_allowed = False
            entry_reason = "Time filter blocked entry"
        else:
            entry_allowed, entry_reason = smart_entry_conditions_met(
                intraday_15m, intraday_1hr, daily_ohlcv, price)
    
    if signal == "BUY" and not entry_allowed:
        log.info("🚫 SMART ENTRY BLOCKED: %s", entry_reason)
        signal = "HOLD"
    
    stop_loss = 0.0
    targets = []
    
    if signal == "BUY" and entry_allowed:
        stop_loss = calculate_dynamic_sl(price, atr)
        targets = calculate_targets(price, stop_loss)
        log.info("\n🎯 [STEP 3] Dynamic Stop Loss: ₹%.2f", stop_loss)
        log.info("🎯 [STEP 4] Target Management:")
        for t in targets:
            log.info("   Target %d: ₹%.2f (%.1f× risk, exit %.0f%%)", 
                     t["level"], t["price"], t["risk_mult"], t["exit_pct"] * 100)
    
    adjusted_position = int(POSITION * pos_mult)
    quantity = max(1, int(adjusted_position / price))
    
    log.info("\n" + "=" * 70)
    log.info("  SYMBOL      : %s", SYMBOL)
    log.info("  STRATEGY    : %s", STRATEGY)
    log.info("  SIGNAL      : ★ %s ★", signal)
    log.info("  REGIME      : %s (size mult: %.0f%%)", regime, pos_mult * 100)
    log.info("  SMART ENTRY : %s", entry_reason if signal == "HOLD" else "PASSED")
    log.info("  PRICE       : ₹%.2f", price)
    log.info("  QTY         : %d shares (₹%d position)", quantity, adjusted_position)
    log.info("  ATR          : %.4f", atr)
    if stop_loss > 0:
        log.info("  STOP LOSS   : ₹%.2f  (%.1f%% from entry)", stop_loss, (price - stop_loss) / price * 100)
        log.info("  TARGETS     : T1=₹%.2f | T2=₹%.2f | T3=₹%.2f", 
                 targets[0]["price"], targets[1]["price"], targets[2]["price"])
    log.info("=" * 70)
    
    log_signal(signal, price, atr, targets, regime)
    
    if signal != "HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result = place_groww_order(SYMBOL, signal, quantity, price)
        if result:
            log.info("✓ Order executed via Groww: %s", result)
        else:
            log.warning("⚠ Groww order could not be placed – signal still printed/logged.")
    elif signal != "HOLD":
        log.info("📋 No Groww credentials – paper mode (signal logged).")
def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API (real) or paper trade.
    Uses Bracket Order (BO) for BUY/SELL with target + stop loss built-in.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008  # 0.8% of price as ATR approximation
    
    if signal == "BUY":
        stop_loss = round(price - atr * 1.0, 2)
        target = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="BUY", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = round(price + atr * 1.0, 2)
        target = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="SELL", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, stop_loss, target))
    return result
    Place order via Groww API (real) or paper trade.
    Uses Bracket Order (BO) for BUY/SELL with target + stop loss built-in.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008  # 0.8% of price as ATR approximation
    
    if signal == "BUY":
        stop_loss = round(price - atr * 1.0, 2)
        target = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="BUY", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = round(price + atr * 1.0, 2)
        target = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="SELL", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, stop_loss, target))
    return result

if __name__ == "__main__":
    main()
