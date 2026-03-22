#!/usr/bin/env python3
"""
Live Trading Script - PERSISTENT.NS
Strategy: VWAP (Volume Weighted Average Price) + RSI 55/45 Filter + Volume 1.2x
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%
Entry Window: 9:30–14:30 IST | TRAIL_ATR_MULT=0.3
"""

import os
import sys
import json
import time
import logging
import groww_api
import requests
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True yf

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_PERSISTENT.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_PERSISTENT")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "PERSISTENT.NS"
STRATEGY       = "VWAP"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {"vwap_period": 14, "atr_multiplier": 1.5}

# ── NEW FILTERS ───────────────────────────────────────────────────────────────
TRAIL_ATR_MULT = 0.3      # Trailing stop ATR multiplier
RSI_OB_LEVEL   = 55       # RSI above this → BUY allowed
RSI_OS_LEVEL   = 45       # RSI below this → SELL allowed
VOL_MULTIPLIER = 1.2      # Volume must be this x average
ENTRY_START    = dtime(9, 30)   # 9:30 AM IST
ENTRY_END      = dtime(14, 30)  # 2:30 PM IST
NO_ENTRY_AFTER = dtime(14, 30) # No new entries after 2:30 PM

# 3-TIER EXIT SYSTEM
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit
TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

def can_new_entry() -> bool:
    """Only allow entries during best entry window."""
    now = ist_now().time()
    if now < ENTRY_START:
        log.info("⏰ Too early — waiting for 9:30 AM IST entry window")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM IST — no new entries today")
        return False
    return True

def in_entry_window() -> bool:
    now = ist_now().time()
    return ENTRY_START <= now <= ENTRY_END

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(SYMBOL)
            df = ticker.history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {
                    "date":   str(idx.date()),
                    "open":   float(row["Open"]),
                    "high":   float(row["High"]),
                    "low":    float(row["Low"]),
                    "close":  float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
                for idx, row in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching data: %s", attempt + 1, retries, e)
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

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Calculate RSI values for the OHLCV data."""
    rsi = [None] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi[i + 1] = 100 - (100 / (1 + rs))
    return rsi

def calculate_avg_volume(ohlcv: list, lookback: int = 20) -> float:
    """Calculate average volume over lookback period."""
    if len(ohlcv) < lookback:
        return float(sum(b["volume"] for b in ohlcv)) / max(len(ohlcv), 1)
    return float(sum(b["volume"] for b in ohlcv[-lookback:])) / lookback

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
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

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    vwap_vals     = calculate_vwap(ohlcv, period)
    atr_vals      = calculate_atr(ohlcv, period)
    rsi_vals      = calculate_rsi(ohlcv, period)
    signals       = ["HOLD"] * len(ohlcv)

    avg_vol = calculate_avg_volume(ohlcv)

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        price    = ohlcv[i]["close"]
        v        = vwap_vals[i]
        a        = atr_vals[i]
        r        = rsi_vals[i]
        bar_vol  = ohlcv[i]["volume"]
        vol_ok_i = bar_vol >= avg_vol * VOL_MULTIPLIER

        # Volume filter: skip if volume < 1.2x average
        if not vol_ok_i:
            continue

        # RSI 55/45 filter: BUY only if RSI > 55, SELL only if RSI < 45
        if price > v + a * atr_mult and r > RSI_OB_LEVEL:
            signals[i] = "BUY"
        elif price < v - a * atr_mult and r < RSI_OS_LEVEL:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

def place_groww_order(symbol, signal, quantity, price, atr=None):
    """
    Place order via Groww API or paper trade.
    Uses Bracket Orders (BO) when GROWW_API_KEY is set.
    Falls back to paper trading otherwise.
    """
    import groww_api
    if atr is None:
        atr = 0.0

    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)

    exchange = "NSE"

    if signal == "BUY":
        stop_loss = price - (atr * SL_ATR_MULT)
        target    = price + (atr * TARGET_MULT)
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="BUY",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=TRAIL_ATR_MULT,
            trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = price + (atr * SL_ATR_MULT)
        target    = price - (atr * TARGET_MULT)
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="SELL",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=TRAIL_ATR_MULT,
            trailing_target=0.5
        )
    else:
        return None

    if result:
        print("Order placed: {} {} {} @ Rs{:.2f}".format(
            signal, quantity, symbol, price))
    return result

def main():
    """
    Universal main() — detects strategy type and runs appropriate signal.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        import yfinance
YFINANCE_AVAILABLE = True yf
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return

    fname = Path(__file__).stem
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")

    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix

    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym})")
    print(f"{'='*60}")

    # Check entry window
    if not in_entry_window():
        now = ist_now().time()
        print(f"Outside entry window (9:30–14:30 IST). Current: {now.strftime('%H:%M:%S')}")
        print("No new entries — HOLD")
        return

    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
        ohlcv = [[r[0], r[1], r[2], r[3], r[4]] for r in data.itertuples()]
        print(f"Loaded {len(ohlcv)} candles")
    except Exception as e:
        print(f"Data fetch error: {e}")
        return

    ohlcv_list = []
    for idx, row in data.iterrows():
        ohlcv_list.append([
            float(row['Open']),
            float(row['High']),
            float(row['Low']),
            float(row['Close']),
            float(row['Volume'])
        ])

    if not ohlcv_list:
        print("No OHLCV data")
        return

    signal = None
    price  = ohlcv_list[-1][2]

    try:
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'adx_signal' in dir():
            sig_result = adx_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'rsi_signal' in dir():
            sig_result = rsi_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'macd_signal' in dir():
            sig_result = macd_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
            for func_name in ['signal', 'get_signal', 'generate_signal']:
                if func_name in dir():
                    func = eval(func_name)
                    if callable(func):
                        result = func(ohlcv_list)
                        if isinstance(result, tuple):
                            signal, price = result[0], float(result[1])
                        elif isinstance(result, str):
                            signal = result
                        break

        if not signal:
            closes = [o[4] for o in ohlcv_list]
            if len(closes) >= 20:
                sma20 = sum(closes[-20:]) / 20
                current = closes[-1]
                if current > sma20 * 1.005:
                    signal = "BUY"
                    price = current
                elif current < sma20 * 0.995:
                    signal = "SELL"
                    price = current
                else:
                    signal = "HOLD"
                    price = current

    except Exception as e:
        print(f"Signal generation error: {e}")
        signal = "HOLD"
        price = ohlcv_list[-1][4]

    if len(ohlcv_list) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_list))):
            h = ohlcv_list[i][1]
            l = ohlcv_list[i][2]
            prev_c = ohlcv_list[i-1][4]
            tr = max(h-l, abs(h-prev_c), abs(l-prev_c))
            trs.append(tr)
        if trs:
            atr = sum(trs) / len(trs)

    print(f"\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")

    if signal == "BUY":
        sl = round(price - atr * SL_ATR_MULT, 2)
        tgt = round(price + atr * TARGET_MULT, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr,
                metadata={"source": Path(__file__).name}
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("BUY", ticker_sym, price, qty)
            except:
                pass

    elif signal == "SELL":
        sl = round(price + atr * SL_ATR_MULT, 2)
        tgt = round(price - atr * TARGET_MULT, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{price-tgt:.2f} reward)")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="SELL",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("SELL", ticker_sym, price, qty)
            except:
                pass

    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()
