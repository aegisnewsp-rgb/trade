#!/usr/bin/env python3
"""
Live Trading Script - COROMANDEL.BO
Strategy: MEAN_REVERSION (RSI-only + VWAP bounce) - v9 LOWWR
Position: ₹7000 | Stop Loss: 0.6% | Target: 4.0x | Daily Loss Cap: 0.3%
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
YFINANCE_AVAILABLE = True
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_COROMANDEL_BO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_COROMANDEL_BO")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "COROMANDEL.BO"
STRATEGY = "MEAN_REVERSION_RSI_V9"  # COROMANDEL.BO  # COROMANDEL.BO
POSITION       = 7000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.006
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "vwap_period": 14,
    "atr_multiplier": 1.5,
    "rsi_period": 14,
    "rsi_overbought": 62,
    "rsi_oversold": 38,
    "rsi_confirm_overbought": 62,
    "rsi_confirm_oversold": 38,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_multiplier": 1.3,   # v8: require above-2x avg volume
    "trend_ma_period": 50,      # v8: trend filter
    "atr_period": 14,
    "bb_period": 20,            # v8: Bollinger Band period
    "bb_std": 2.0,             # v8: Bollinger Band std dev
}

GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5

# ── Helpers ────────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)

# Smart entry: 9:30-14:30 IST
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
    """Index-based ATR: ohlcv[i] = [open, high, low, close, volume]"""
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high, low = bar[1], bar[2]
        close     = bar[3]
        tr = high - low if prev_close is None else max(
            high - low, abs(high - prev_close), abs(low - prev_close))
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = close
    return atr

def calculate_vwap(ohlcv: list, period: int = 14) -> list:
    """Index-based VWAP: ohlcv[i] = [open, high, low, close, volume]"""
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            tp_sum  = sum((ohlcv[j][1] + ohlcv[j][2] + ohlcv[j][3]) / 3
                          for j in range(i - period + 1, i + 1))
            vol_sum = sum(ohlcv[j][4] for j in range(i - period + 1, i + 1))
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0.0)
    return vwap

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Index-based RSI: ohlcv[i] = [open, high, low, close, volume]"""
    rsi_values = [50.0] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi_values
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i][3] - ohlcv[i - 1][3]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100 - (100 / (1 + rs))
    return rsi_values

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    """Index-based MACD: ohlcv[i] = [open, high, low, close, volume]"""
    closes = [b[3] for b in ohlcv]
    ema_fast, ema_slow, macd_line = [], [], []
    k_fast = 2 / (fast + 1); k_slow = 2 / (slow + 1)
    ema_fast.append(closes[0]); ema_slow.append(closes[0])
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * k_fast + ema_fast[-1] * (1 - k_fast))
        ema_slow.append(closes[i] * k_slow + ema_slow[-1] * (1 - k_slow))
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    signal_line = []
    k_sig = 2 / (signal + 1)
    signal_line.append(macd_line[0])
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    histogram = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]
    return macd_line, signal_line, histogram

def calculate_ma(ohlcv: list, period: int) -> list:
    """Index-based SMA: ohlcv[i] = [open, high, low, close, volume]"""
    ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(ohlcv[j][3] for j in range(i - period + 1, i + 1)) / period)
    return ma

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    """Index-based avg volume: ohlcv[i] = [open, high, low, close, volume]"""
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j][4] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_bollinger_bands(ohlcv: list, period: int = 20, std_dev: float = 2.0) -> tuple[list, list, list]:
    """Index-based Bollinger Bands: ohlcv[i] = [open, high, low, close, volume]"""
    middle = calculate_ma(ohlcv, period)
    upper, lower = [], []
    for i in range(len(ohlcv)):
        if middle[i] is None:
            upper.append(None); lower.append(None)
        else:
            window = ohlcv[max(0, i - period + 1):i + 1]
            mean = middle[i]
            variance = sum((b[3] - mean) ** 2 for b in window) / len(window)
            std = variance ** 0.5
            upper.append(mean + std_dev * std)
            lower.append(mean - std_dev * std)
    return upper, middle, lower

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, float]:
    """MEAN_REVERSION v9: RSI-only bounce + VWAP proximity + Volume confirmation.
    No trend filter (fails for consistently downtrending stocks).
    """
    period     = params["vwap_period"]
    atr_mult   = params["atr_multiplier"]
    rsi_period = params["rsi_period"]
    rsi_oversold   = params.get("rsi_oversold", 38)
    rsi_overbought = params.get("rsi_overbought", 62)
    vol_mult   = params.get("volume_multiplier", 1.5)

    vwap_vals  = calculate_vwap(ohlcv, period)
    atr_vals   = calculate_atr(ohlcv, period)
    rsi_vals   = calculate_rsi(ohlcv, rsi_period)
    avg_vol    = calculate_avg_volume(ohlcv, period)

    start_idx = max(period, rsi_period, 5)
    signals   = ["HOLD"] * len(ohlcv)

    for i in range(start_idx, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue

        price = ohlcv[i][3]
        v      = vwap_vals[i]
        a      = atr_vals[i]
        rsi    = rsi_vals[i]
        vol    = ohlcv[i][4]

        # Mean reversion: oversold + price near/at VWAP support
        oversold      = rsi < rsi_oversold
        near_vwap     = abs(price - v) < a * 1.0
        vol_confirmed = vol > avg_vol * vol_mult

        # Overbought: overbought + price near/at VWAP resistance
        overbought    = rsi > rsi_overbought
        at_resistance = abs(price - v) < a * 1.0

        if oversold and near_vwap and vol_confirmed:
            signals[i] = "BUY"
        elif overbought and at_resistance and vol_confirmed:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1][3]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals else 50.0
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
    print(f"Running: {ticker_sym} ({yahoo_sym})")
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
    price = ohlcv_list[-1][2]  # close price
    
    try:
        # Try strategy functions in priority order
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, PARAMS)
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

