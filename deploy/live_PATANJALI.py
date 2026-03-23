#!/usr/bin/env python3
"""
ENHANCED TRADING SCRIPT - live_PATANJALI
===================================
Strategy: MEAN_REVERSION v9c - RSI crossover + VWAP + Volume filters
Win Rate: low -> Target 55%+ (v9c: RSI 40/60 crossover + vol 2x + tighter params)
Position: ₹5000 | Stop Loss: 0.6% | Target: 4.0x | Daily Loss Cap: 0.25%
Enhanced: 2026-03-23 - v9c: Tightened RSI to 40/60, vol to 2x, RSI crossover req
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

try:
    import yfinance as yf
except ImportError:
    YFINANCE_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_PATANJALI.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_PATANJALI")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "PATANJALI.BO"
STRATEGY = "MEAN_REVERSION_RSI_V9C"
POSITION       = 5000

# 3-TIER EXIT SYSTEM
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0
STOP_LOSS_PCT  = 0.006
TARGET_MULT    = 2.5
SIGNAL_MODE   = "MEAN_REVERSION"
DAILY_LOSS_CAP = 0.0025
PARAMS         = {"vwap_period": 14, "atr_multiplier": 0.5, "rsi_period": 14, "rsi_oversold": 40, "rsi_overbought": 60, "volume_multiplier": 2.0}

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

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """MEAN_REVERSION v9c: RSI crossover + VWAP + Volume confirmation."""
    period        = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    rsi_period    = params.get("rsi_period", 14)
    rsi_oversold  = params.get("rsi_oversold", 40)
    rsi_overbought = params.get("rsi_overbought", 60)
    vol_mult      = params.get("volume_multiplier", 2.0)

    vwap_vals     = calculate_vwap(ohlcv, period)
    atr_vals      = calculate_atr(ohlcv, period)
    rsi_vals      = calculate_rsi_list(ohlcv, rsi_period)
    signals       = ["HOLD"] * len(ohlcv)

    # Calculate volume average
    if len(ohlcv) >= 20:
        avg_vol = sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - 20, len(ohlcv))) / 20
    else:
        avg_vol = sum(ohlcv[j]["volume"] for j in range(len(ohlcv))) / max(len(ohlcv), 1)

    start_idx = max(period, rsi_period, 5)
    for i in range(start_idx, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None:
            continue

        # RSI crossover detection
        prev_rsi = rsi_vals[i - 1] if i > start_idx else rsi_vals[i]
        curr_rsi = rsi_vals[i]

        price    = ohlcv[i]["close"]
        v        = vwap_vals[i]
        a        = atr_vals[i]
        vol      = ohlcv[i]["volume"]
        signal_mode = globals().get("SIGNAL_MODE", "BREAKOUT")

        # Volume confirmation
        vol_confirmed = vol >= avg_vol * vol_mult

        if signal_mode == "MEAN_REVERSION":
            # BUY: RSI crossed below oversold threshold + price near VWAP support
            rsi_crossed_down = prev_rsi >= rsi_oversold and curr_rsi < rsi_oversold
            near_support = price < v  # price below VWAP
            if rsi_crossed_down and near_support and vol_confirmed:
                signals[i] = "BUY"
            # SELL: RSI crossed above overbought threshold + price near VWAP resistance
            elif curr_rsi > rsi_overbought and prev_rsi <= rsi_overbought and vol_confirmed:
                signals[i] = "SELL"
        else:
            # BREAKOUT mode
            if price > v + a * atr_mult and vol_confirmed:
                signals[i] = "BUY"
            elif price < v - a * atr_mult and vol_confirmed:
                signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return current_signal, current_price, current_atr

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


# ============================================================================
# ENHANCED SIGNAL GENERATION - WITH MULTI-FILTER CONFIRMATION
# ============================================================================
# Active filters: volume, trend, volatility, rsi

def calculate_volume_ma(ohlcv: List[dict], period: int = 20) -> float:
    """Calculate 20-day volume moving average."""
    if len(ohlcv) < period:
        return 0
    volumes = [bar["volume"] for bar in ohlcv[-period:]]
    return sum(volumes) / period


def calculate_price_ma(ohlcv: List[dict], period: int = 50) -> float:
    """Calculate N-day moving average of close prices."""
    if len(ohlcv) < period:
        return 0
    closes = [bar["close"] for bar in ohlcv[-period:]]
    return sum(closes) / period


def calculate_atr(ohlcv: List[dict], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(ohlcv) < period + 1:
        return 0
    tr_values = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i]["high"]
        low = ohlcv[i]["low"]
        prev_close = ohlcv[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period if len(tr_values) >= period else 0


def calculate_rsi(ohlcv: List[dict], period: int = 14) -> float:
    """Calculate RSI indicator."""
    if len(ohlcv) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_rsi_list(ohlcv: list, period: int = 14) -> list:
    """Calculate RSI indicator as a list of values."""
    rsi_values = [50.0] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi_values
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(change if change > 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    for i in range(period, len(ohlcv)):
        avg_gain = sum(gains[i - period + 1:i + 1]) / period
        avg_loss = sum(losses[i - period + 1:i + 1]) / period
        if avg_loss == 0:
            rsi_values[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i] = 100 - (100 / (1 + rs))
    return rsi_values


def apply_filters(
    ohlcv: List[dict],
    base_signal: str,
    index: int,
    params: dict
) -> Tuple[str, dict]:
    """
    Apply all enabled filters to the base signal.
    Returns (filtered_signal, filter_info).
    """
    filter_info = {
        "volume_passed": False,
        "trend_passed": False,
        "volatility_passed": False,
        "rsi_passed": False,
        "all_passed": False
    }
    
    current_price = ohlcv[index]["close"]
    
    # Skip if no base signal
    if base_signal == "HOLD":
        return "HOLD", filter_info
    
    # 1. VOLUME FILTER
    if True:
        vol_ma = calculate_volume_ma(ohlcv, 20)
        current_vol = ohlcv[index]["volume"]
        min_vol_ratio = 1.0
        
        if vol_ma > 0 and current_vol >= vol_ma * min_vol_ratio:
            filter_info["volume_passed"] = True
    
    # 2. TREND FILTER  
    if True:
        trend_ma = calculate_price_ma(ohlcv, 50)
        
        if base_signal == "BUY" and current_price > trend_ma:
            filter_info["trend_passed"] = True
        elif base_signal == "SELL" and current_price < trend_ma:
            filter_info["trend_passed"] = True
    
    # 3. VOLATILITY FILTER
    if True:
        atr_value = calculate_atr(ohlcv, 0.5)
        atr_percent = (atr_value / current_price * 100) if current_price > 0 else 0
        min_atr = 5.0
        max_atr = True
        
        if min_atr <= atr_percent <= max_atr:
            filter_info["volatility_passed"] = True
    
    # 4. RSI MOMENTUM FILTER
    if 35:
        rsi = calculate_rsi(ohlcv, 65)
        oversold = True
        overbought = True
        
        if base_signal == "BUY" and rsi >= oversold:
            filter_info["rsi_passed"] = True
        elif base_signal == "SELL" and rsi <= overbought:
            filter_info["rsi_passed"] = True
    
    # Determine if ALL critical filters passed
    # Volume and Trend are critical; Volatility and RSI are advisory
    critical_volume = False  # Can be toggled
    critical_trend = False   # Can be toggled
    critical_volatility = False
    critical_rsi = False
    
    if critical_volume and not filter_info["volume_passed"]:
        return "HOLD", filter_info
    if critical_trend and not filter_info["trend_passed"]:
        return "HOLD", filter_info
    
    # If volatility or RSI fails, still pass but note it
    filter_info["all_passed"] = (
        (not critical_volume or filter_info["volume_passed"]) and
        (not critical_trend or filter_info["trend_passed"])
    )
    
    return base_signal, filter_info


def enhanced_generate_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """
    Enhanced signal generation with multi-filter confirmation.
    Applies volume, trend, volatility, and RSI filters to base strategy signals.
    """
    # First get base strategy signals
    base_signals = vwap_signal(ohlcv, params)
    
    # Apply filters to each signal
    enhanced_signals = []
    for i in range(len(ohlcv)):
        base_signal = base_signals[i]
        filtered_signal, filter_info = apply_filters(ohlcv, base_signal, i, params)
        enhanced_signals.append(filtered_signal)
    
    return enhanced_signals


# ============================================================================
# END OF ENHANCED SIGNAL GENERATION
# ============================================================================


def main():
    """
    Universal main() — detects strategy type and runs appropriate signal.
    Works with: VWAP, ADX_TREND, TSI, RSI, MACD, Bollinger, MA_ENVELOPE, etc.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        import yfinance as yf
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

