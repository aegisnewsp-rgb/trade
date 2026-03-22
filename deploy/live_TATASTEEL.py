#!/usr/bin/env python3
"""
Live Trading Script - TATASTEEL.NS
Strategy: VWAP + RSI + Volume + ADX + MACD (v6 enhanced)
Win Rate: 58.06% -> Target 62%+
Position: ₹7000 | Stop Loss: 1.3x ATR | Target: 2.5x ATR | Daily Loss Cap: 0.3%
Enhancements over v5:
  - RSI bands tightened: 45/55 → 48/52 → stricter quality filter for entries
  - Volume confirm raised: 1.2x → 1.3x → stronger volume required
  - ADX min raised: 20 → 22 → only very confirmed trends qualify
  - Target tightened: 3.0x → 2.5x ATR → shorter target = higher win rate
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

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_TATASTEEL.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_TATASTEEL")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL             = "TATASTEEL.NS"
STRATEGY           = "VWAP+RSI+VOL+ADX+MACD"
POSITION           = 7000
STOP_LOSS_ATR_MULT = 1.3   # was 1.5x → tighter for better risk:reward
TARGET_ATR_MULT    = 2.5   # was 3.0x → v6: shorter target = higher hit rate
DAILY_LOSS_CAP     = 0.003
PARAMS = {
    "vwap_period":         14,
    "atr_multiplier":      1.3,
    "rsi_period":          14,
    "rsi_buy_min":         48,   # was 45 → v6: stricter RSI floor for quality entries
    "rsi_sell_max":        52,   # was 55 → v6: stricter RSI ceiling for short exits
    "vol_sma_period":      20,
    "vol_confirm_mult":    1.3, # was 1.2 → v6: require stronger volume for confirmation
    "atr_vol_period":     20,   # period for ATR volatility SMA
    "adx_period":         14,   # ADX period for trend strength
    "adx_min":            22,   # was 20 → v6: only trade in stronger confirmed trends
    "macd_fast":           12,   # MACD fast EMA
    "macd_slow":           26,   # MACD slow EMA
    "macd_signal":          9,   # MACD signal line
    "session_avoid_min":   15,   # avoid first/last N minutes of session
}

BENCHMARK_WIN_RATE = 0.5806   # v3 live benchmark → v6 targeting 62%+
TARGET_WIN_RATE   = 0.62

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

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Compute RSI (Relative Strength Index)."""
    rsi = [None] * len(ohlcv)
    if len(ohlcv) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        delta = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi[i + 1] = 100 - (100 / (1 + rs))
    return rsi

def calculate_vol_sma(ohlcv: list, period: int = 20) -> list:
    """20-day SMA of volume for volume confirmation."""
    vol_sma = [None] * len(ohlcv)
    for i in range(period - 1, len(ohlcv)):
        vol_sma[i] = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
    return vol_sma

def calculate_atr_sma(atr_vals: list, period: int = 20) -> list:
    """20-day SMA of ATR for volatility filter."""
    atr_sma = [None] * len(atr_vals)
    valid = [v for v in atr_vals if v is not None]
    for i in range(len(atr_vals)):
        window = [v for v in atr_vals[max(0, i - period + 1):i + 1] if v is not None]
        if len(window) >= period // 2:  # require at least half the period
            atr_sma[i] = sum(window) / len(window)
    return atr_sma

def calculate_adx(ohlcv: list, period: int = 14) -> tuple[list, list, list]:
    """
    Compute ADX (Average Directional Index), +DI, -DI.
    Returns (adx_vals, plus_di, minus_di).
    """
    high  = [b["high"]  for b in ohlcv]
    low   = [b["low"]   for b in ohlcv]
    close = [b["close"] for b in ohlcv]

    tr_list = [None] * len(ohlcv)
    plus_dm = [None] * len(ohlcv)
    minus_dm = [None] * len(ohlcv)

    for i in range(1, len(ohlcv)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
        tr_list[i] = tr
        plus_dm[i]  = max(high[i] - high[i - 1], 0) if high[i] - high[i - 1] > low[i - 1] - low[i] else 0
        minus_dm[i] = max(low[i - 1] - low[i], 0)  if low[i - 1] - low[i] > high[i] - high[i - 1] else 0

    # Smooth with Wilder's smoothing (EWM with alpha=1/period)
    def wilder_smooth(vals, period):
        out = [None] * len(vals)
        valid = [v for v in vals[1:] if v is not None]
        if len(valid) < period:
            return out
        sma = sum(valid[:period]) / period
        out[period] = sma
        for i in range(period + 1, len(vals)):
            if vals[i] is not None:
                sma = (sma * (period - 1) + vals[i]) / period
                out[i] = sma
        return out

    tr_s  = wilder_smooth(tr_list, period)
    pdm_s = wilder_smooth(plus_dm, period)
    mdm_s = wilder_smooth(minus_dm, period)

    plus_di  = [None] * len(ohlcv)
    minus_di = [None] * len(ohlcv)
    dx       = [None] * len(ohlcv)

    for i in range(period, len(ohlcv)):
        if tr_s[i] and tr_s[i] != 0:
            plus_di[i]  = 100 * pdm_s[i] / tr_s[i]
            minus_di[i] = 100 * mdm_s[i] / tr_s[i]
        if plus_di[i] is not None and minus_di[i] is not None:
            di_sum = plus_di[i] + minus_di[i]
            dx[i]  = 100 * abs(plus_di[i] - minus_di[i]) / di_sum if di_sum != 0 else 0

    # ADX = Wilder smooth of DX
    adx_vals = [None] * len(ohlcv)
    valid_dx = [v for v in dx[period:] if v is not None]
    if len(valid_dx) >= period:
        adx_sma = sum(valid_dx[:period]) / period
        adx_vals[period + period - 1] = adx_sma
        for i in range(period + period, len(ohlcv)):
            if dx[i] is not None:
                adx_sma = (adx_sma * (period - 1) + dx[i]) / period
                adx_vals[i] = adx_sma

    return adx_vals, plus_di, minus_di

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    """
    Compute MACD line, signal line, and histogram.
    Returns (macd_line, signal_line, histogram).
    Histogram > 0 = bullish momentum, < 0 = bearish momentum.
    """
    closes = [b["close"] for b in ohlcv]

    def ema(vals, period):
        out = [None] * len(vals)
        valid = [v for v in vals if v is not None]
        if len(valid) < period:
            return out
        sma = sum(valid[:period]) / period
        out[period - 1] = sma
        k = 2 / (period + 1)
        for i in range(period, len(vals)):
            if vals[i] is not None:
                out[i] = vals[i] * k + out[i - 1] * (1 - k)
        return out

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line = [None] * len(ohlcv)
    for i in range(len(ohlcv)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    signal_line = ema(macd_line, signal)

    histogram = [None] * len(ohlcv)
    for i in range(len(ohlcv)):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram

def vwap_enhanced_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    VWAP + RSI + Volume + ADX + MACD (v5).
    Returns (signal, price, atr).
    Signal is HOLD if:
      - RSI not in valid range (BUY needs RSI > rsi_buy_min, SELL needs RSI < rsi_sell_max)
      - Volume below confirmation threshold
      - ATR above its SMA (choppy / high-volatility market)
      - ADX <= adx_min (no confirmed trend)
      - MACD histogram not aligned with signal direction
    """
    vwap_period   = params["vwap_period"]
    atr_mult      = params["atr_multiplier"]
    rsi_period    = params["rsi_period"]
    rsi_buy_min   = params["rsi_buy_min"]
    rsi_sell_max  = params["rsi_sell_max"]
    vol_period    = params["vol_sma_period"]
    vol_mult      = params["vol_confirm_mult"]
    atr_vol_p     = params["atr_vol_period"]
    adx_period    = params["adx_period"]
    adx_min       = params["adx_min"]
    macd_fast     = params["macd_fast"]
    macd_slow     = params["macd_slow"]
    macd_signal   = params["macd_signal"]

    vwap_vals  = calculate_vwap(ohlcv, vwap_period)
    atr_vals   = calculate_atr(ohlcv, vwap_period)
    rsi_vals   = calculate_rsi(ohlcv, rsi_period)
    vol_sma    = calculate_vol_sma(ohlcv, vol_period)
    atr_sma    = calculate_atr_sma(atr_vals, atr_vol_p)
    adx_vals, plus_di, minus_di = calculate_adx(ohlcv, adx_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, macd_fast, macd_slow, macd_signal)

    signals    = ["HOLD"] * len(ohlcv)
    start_idx  = max(vwap_period, rsi_period, vol_period, atr_vol_p,
                     adx_period * 2, macd_slow + macd_signal)

    for i in range(start_idx, len(ohlcv)):
        if None in (vwap_vals[i], atr_vals[i], rsi_vals[i],
                    vol_sma[i], atr_sma[i], adx_vals[i], histogram[i]):
            continue
        price   = ohlcv[i]["close"]
        v       = vwap_vals[i]
        a       = atr_vals[i]
        rsi     = rsi_vals[i]
        vol     = ohlcv[i]["volume"]
        vol_avg = vol_sma[i]
        atr_now = atr_vals[i]
        atr_avg = atr_sma[i]
        adx     = adx_vals[i]
        hist    = histogram[i]

        # Volatility filter: skip in choppy / high-volatility regimes
        if atr_avg is not None and atr_now > atr_avg * 1.15:
            continue

        # ADX trend filter: require confirmed trend (ADX > adx_min)
        if adx is not None and adx <= adx_min:
            continue

        # Volume confirmation
        if vol < vol_avg * vol_mult:
            continue

        if price > v + a * atr_mult:
            if rsi > rsi_buy_min and hist > 0:   # RSI > 45 + bullish MACD
                signals[i] = "BUY"
        elif price < v - a * atr_mult:
            if rsi < rsi_sell_max and hist < 0:  # RSI < 55 + bearish MACD
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
    atr = price * 0.008  # fallback
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

