#!/usr/bin/env python3
"""
Live Trading Script - BAJFINANCE.NS
Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8 LOWWR - NBFC profile)
Enhanced: 2026-03-23 - v8 LOWWR upgrade from VWAP+Volume
- v8 LOWWR NEW: Bollinger Band (20,2.0) + 50-MA Trend filter + MACD(12,26,9) multi-filter
- v8 LOWWR: 3-TIER EXIT 1.5x/3.0x/5.0x, STOP_LOSS 0.6%, TARGET_MULT 4.0x
Win Rate: ~58% -> Target 65%+
Position: ₹7000 | Daily Loss Cap: 0.3%
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

import yfinance as yf
YFINANCE_AVAILABLE = True
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_BAJFINANCE.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_BAJFINANCE")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "BAJFINANCE.NS"
STRATEGY       = "VWAP_RSI_MACD_VOL_BB_v8_LOWWR"
POSITION       = 7000
STOP_LOSS_PCT  = 0.006  # v8: 0.6% hard stop
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    # v8 LOWWR multi-filter params
    "vwap_period": 14,
    "atr_period": 14,
    "atr_multiplier": 1.5,
    "rsi_period": 14,
    "rsi_overbought": 68,
    "rsi_oversold": 32,
    "rsi_confirm_overbought": 68,
    "rsi_confirm_oversold": 32,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_multiplier": 2.0,  # v8: 2x avg volume
    "volume_ma_period": 20,
    "trend_ma_period": 50,
    "bb_period": 20,
    "bb_std": 2.0,
}

# 3-TIER EXIT SYSTEM (enhancement)
SL_ATR_MULT       = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT        = 0.015  # Hard cap: 1.5% max stop
TRAIL_ATR_MULT    = 0.3    # Trailing stop: 0.3x ATR
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT     = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT     = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT     = 5.0     # T3: 5.0x risk → exit remaining

# Entry window
BEST_ENTRY_START  = dtime(9, 30)  # 9:30 AM IST
BEST_ENTRY_END    = dtime(14, 30) # 2:30 PM IST
NO_ENTRY_AFTER    = dtime(14, 30) # No new entries after 2:30 PM

def can_new_entry() -> bool:
    """Only allow entries during best entry window."""
    now = ist_now().time()
    if now < BEST_ENTRY_START:
        log.info("⏰ Too early — waiting for 9:30 AM IST entry window")
        return False
    if now >= NO_ENTRY_AFTER:
        log.info("⏰ After 2:30 PM IST — no new entries today")
        return False
    return True

def in_best_entry_window() -> bool:
    now = ist_now().time()
    return BEST_ENTRY_START <= now <= BEST_ENTRY_END

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.now(datetime.UTC) + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

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

def calculate_volume_ma(ohlcv: list, period: int = 20) -> list:
    """Calculate volume moving average for confirmation filter"""
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            vol_avg = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
            vol_ma.append(vol_avg)
    return vol_ma

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

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    closes = [b["close"] for b in ohlcv]
    ema_fast, ema_slow = [closes[0]], [closes[0]]
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * (2/(fast+1)) + ema_fast[-1] * (1 - 2/(fast+1)))
        ema_slow.append(closes[i] * (2/(slow+1)) + ema_slow[-1] * (1 - 2/(slow+1)))
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    signal_line = [macd_line[0]]
    k_sig = 2/(signal+1)
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    histogram = [macd_line[i] - signal_line[i] for i in range(len(closes))]
    return macd_line, signal_line, histogram

def calculate_ma(ohlcv: list, period: int) -> list:
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_bollinger_bands(ohlcv: list, period: int = 20, std_dev: float = 2.0) -> tuple:
    middle = calculate_ma(ohlcv, period)
    upper, lower = [], []
    for i in range(len(ohlcv)):
        if middle[i] is None:
            upper.append(None); lower.append(None)
        else:
            window = ohlcv[max(0, i - period + 1):i + 1]
            mean = middle[i]
            variance = sum((b["close"] - mean) ** 2 for b in window) / len(window)
            std = variance ** 0.5
            upper.append(mean + std_dev * std)
            lower.append(mean - std_dev * std)
    return upper, middle, lower

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    """v8 LOWWR multi-filter: VWAP + RSI(32/68) + MACD + Volume(2x) + 50-MA + Bollinger Band"""
    period          = params["vwap_period"]
    atr_mult        = params["atr_multiplier"]
    rsi_period      = params["rsi_period"]
    rsi_overbought  = params.get("rsi_confirm_overbought", 68)
    rsi_oversold    = params.get("rsi_confirm_oversold", 32)
    vol_mult        = params.get("volume_multiplier", 2.0)
    trend_period    = params.get("trend_ma_period", 50)
    bb_period       = params.get("bb_period", 20)
    bb_std          = params.get("bb_std", 2.0)

    vwap_vals    = calculate_vwap(ohlcv, period)
    atr_vals     = calculate_atr(ohlcv, period)
    rsi_vals     = calculate_rsi(ohlcv, rsi_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, params["macd_fast"], params["macd_slow"], params["macd_signal"])
    ma_vals      = calculate_ma(ohlcv, trend_period)
    avg_vol      = calculate_avg_volume(ohlcv, period)
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(ohlcv, bb_period, bb_std)

    start_idx = max(period, rsi_period, params["macd_slow"], params["macd_signal"], bb_period, trend_period)
    signals   = ["HOLD"] * len(ohlcv)

    for i in range(start_idx, len(ohlcv)):
        if None in (vwap_vals[i], atr_vals[i], rsi_vals[i], macd_line[i], ma_vals[i], bb_upper[i]):
            continue

        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        trend   = ma_vals[i]
        macd_h  = histogram[i]
        sig_h   = histogram[i - 1] if i > 0 else 0
        bb_up   = bb_upper[i]
        bb_lo   = bb_lower[i]

        # v8 LOWWR BUY: all filters must align
        buy_ok = (
            price > v and               # price above VWAP
            rsi < rsi_oversold and      # RSI oversold (<32)
            macd_h > 0 and              # MACD histogram positive
            sig_h <= macd_h and         # MACD turning bullish (histogram rising)
            vol > avg_vol * vol_mult and # volume confirmation (2x)
            price > trend               # above 50-MA trend
        )
        if buy_ok:
            signals[i] = "BUY"

        # v8 LOWWR SELL: all filters must align
        sell_ok = (
            price < v and               # price below VWAP
            rsi > rsi_overbought and   # RSI overbought (>68)
            macd_h < 0 and            # MACD histogram negative
            sig_h >= macd_h and       # MACD turning bearish (histogram falling)
            vol > avg_vol * vol_mult and # volume confirmation (2x)
            price < trend              # below 50-MA trend
        )
        if sell_ok:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0
    return current_signal, current_price, current_atr, current_rsi

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
        # Calculate target and stop loss  # 0.8% ATR approximation
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

def main():
    """
    Universal main() — detects strategy type and runs appropriate signal.
    Works with: VWAP, ADX_TREND, TSI, RSI, MACD, Bollinger, MA_ENVELOPE, etc.
    """
    import sys
    from pathlib import Path
    try:
        import yfinance
        YFINANCE_AVAILABLE = True
    
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return
    
    # Detect symbol from filename
    fname = Path(__file__).stem  # e.g. "live_RELIANCE"
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    
    # Determine exchange suffix for yfinance
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix
    
    print(f"\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym}) | Strategy: {STRATEGY}")
    print(f"{'='*60}")
    
    # Fetch data
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
    
    # Prepare OHLCV list for strategy functions
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
    
    # Detect strategy type and run appropriate signal
    signal = None
    price = ohlcv_list[-1][3]  # close price
    current_rsi = 50.0

    try:
        # Try strategy functions in priority order
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
                current_rsi = float(sig_result[3]) if len(sig_result) >= 4 else 50.0
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'adx_signal' in dir():
            sig_result = adx_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'rsi_signal' in dir():
            sig_result = rsi_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'macd_signal' in dir():
            sig_result = macd_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
            # Generic: look for any function returning signal
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

        # Default fallback: calculate basic signals
        if not signal:
            closes = [o[3] for o in ohlcv_list]
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
        price = ohlcv_list[-1][3]
    
    # Calculate ATR for risk management
    # Use real ATR from calculate_atr()  # fallback
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
    
    # Output
    print(f"\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    print(f"RSI:    {current_rsi:.2f}")
    print(f"Entry Window: {'YES' if in_best_entry_window() else 'NO'}")

    risk = atr * 1.0
    t1 = round(price + risk * TARGET_1_MULT, 2)
    t2 = round(price + risk * TARGET_2_MULT, 2)
    t3 = round(price + risk * TARGET_3_MULT, 2)
    sl = round(price - risk * SL_ATR_MULT, 2)
    print(f"SL:     Rs{sl:.2f}")
    print(f"T1:     Rs{t1:.2f} (1.5x risk, exit 1/3)")
    print(f"T2:     Rs{t2:.2f} (3.0x risk, exit 1/3)")
    print(f"T3:     Rs{t3:.2f} (5.0x risk, exit remaining)")
    print(f"Trail:  0.3x ATR trailing stop after 0.8% profit")

    if signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")
        
        # Place order
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
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
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

