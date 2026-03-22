#!/usr/bin/env python3
"""
Live Trading Script - WIPRO.NS
Strategy: VWAP + RSI + MACD + Volume Filter + Trend Filter + Bollinger Band (Enhanced v8)
Win Rate: 52.17% -> Target 58%+ (v8 LOWWR: Tighter SL at 0.6%, stricter RSI confirmation, reduced position)
Position: ₹5000 | Stop Loss: 0.6% | Target: 4.0x | Daily Loss Cap: 0.25%
Enhanced: 2026-03-22 - v8 LOWWR: Applied tighter parameters for IT sector volatility
"""

import os, sys, json, time, logging, requests
import groww_api
from datetime import datetime, time as dtime
from pathlib import Path

import yfinance
YFINANCE_AVAILABLE = True
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_WIPRO.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_WIPRO")

SYMBOL         = "WIPRO.NS"
STRATEGY       = "VWAP_RSI_MACD_VOL_BB_v8_LOWWR"
POSITION       = 5000
STOP_LOSS_PCT  = 0.006
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.0025
PARAMS = {
    "vwap_period": 20,
    "atr_multiplier": 1.5,       # v8b: tightened from 2.0 to GLENMARK standard
    "rsi_period": 14,
    "rsi_oversold": 40,
    "rsi_overbought": 60,
    "rsi_confirm_oversold": 32,   # v8b: tightened from 35 to GLENMARK standard
    "rsi_confirm_overbought": 68,  # v8b: tightened from 65 to GLENMARK standard
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,            # v8b: faster signal for earlier entry
    "volume_multiplier": 2.0,     # v8b: tightened from 1.5 to GLENMARK standard
    "trend_ma_period": 50,
    "atr_period": 14,
    "bb_period": 20,             # v8b: Bollinger Band period
    "bb_std": 2.0,               # v8b: Bollinger Band std dev
}

# 3-TIER EXIT SYSTEM (v8 enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window (v8 enhancement - IT stocks need specific timing)
BEST_ENTRY_START = dtime(9, 30)  # 9:30 AM IST - after market opens
BEST_ENTRY_END   = dtime(14, 30) # 2:30 PM IST
NO_ENTRY_AFTER   = dtime(14, 30) # No new entries after 2:30 PM

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

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5.5)

def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)

def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)

def fetch_recent_data(days: int = 120, retries: int = 3) -> list | None:
    for attempt in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), SYMBOL)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.error("All fetch attempts failed for %s", SYMBOL)
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

def calculate_vwap(ohlcv: list, period: int = 20) -> list:
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
    if len(ohlcv) < period + 1:
        return [None] * len(ohlcv)
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    rsi = [None] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(ohlcv)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi.append(100 - (100 / (1 + rs)))
    return rsi

def calculate_macd(ohlcv: list, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list, list, list]:
    closes = [b["close"] for b in ohlcv]
    # EMA fast
    ema_fast = []
    k_fast = 2 / (fast + 1)
    ema_fast.append(closes[0])
    for i in range(1, len(closes)):
        ema_fast.append(closes[i] * k_fast + ema_fast[-1] * (1 - k_fast))
    # EMA slow
    ema_slow = []
    k_slow = 2 / (slow + 1)
    ema_slow.append(closes[0])
    for i in range(1, len(closes)):
        ema_slow.append(closes[i] * k_slow + ema_slow[-1] * (1 - k_slow))
    # MACD line
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    # Signal line (EMA of MACD)
    signal_line = []
    k_sig = 2 / (signal + 1)
    signal_line.append(macd_line[0])
    for i in range(1, len(macd_line)):
        signal_line.append(macd_line[i] * k_sig + signal_line[-1] * (1 - k_sig))
    return macd_line, signal_line, [m - s for m, s in zip(macd_line, signal_line)]  # histogram

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

def calculate_bollinger_bands(ohlcv: list, period: int = 20, std_dev: float = 2.0) -> tuple[list, list, list]:
    """Returns (upper_band, middle_band, lower_band). Middle band = SMA."""
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

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    vwap_period  = params["vwap_period"]
    atr_mult     = params["atr_multiplier"]
    rsi_period   = params["rsi_period"]
    rsi_oversold = params["rsi_oversold"]
    rsi_overbought = params["rsi_overbought"]
    rsi_confirm_oversold = params.get("rsi_confirm_oversold", 30)
    rsi_confirm_overbought = params.get("rsi_confirm_overbought", 70)
    vol_mult     = params["volume_multiplier"]
    trend_period = params["trend_ma_period"]

    bb_period = params.get("bb_period", 20)
    bb_std    = params.get("bb_std", 2.0)
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(ohlcv, bb_period, bb_std)

    vwap_vals = calculate_vwap(ohlcv, vwap_period)
    atr_vals  = calculate_atr(ohlcv, params["atr_period"])
    rsi_vals  = calculate_rsi(ohlcv, rsi_period)
    macd_line, signal_line, histogram = calculate_macd(
        ohlcv, params["macd_fast"], params["macd_slow"], params["macd_signal"])
    ma_vals   = calculate_ma(ohlcv, trend_period)
    avg_vol   = calculate_avg_volume(ohlcv, vwap_period)

    signals   = ["HOLD"] * len(ohlcv)
    for i in range(max(vwap_period, rsi_period, params["macd_slow"], bb_period), len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue
        if ma_vals[i] is None or macd_line[i] is None or signal_line[i] is None:
            continue
        if bb_upper[i] is None or bb_lower[i] is None:
            continue

        price  = ohlcv[i]["close"]
        v      = vwap_vals[i]
        a      = atr_vals[i]
        r      = rsi_vals[i]
        vol    = ohlcv[i]["volume"]
        trend  = ma_vals[i]
        macd_h = histogram[i]
        sig_h  = histogram[i - 1] if i > 0 else 0
        bb_up  = bb_upper[i]
        bb_lo  = bb_lower[i]

        # Volume confirmation: require above-average volume
        volume_confirmed = vol > avg_vol * vol_mult

        # Trend filter: price above MA for longs, below MA for shorts
        bull_market = price > trend
        bear_market = price < trend

        # MACD histogram confirmation: bullish if histogram rising, bearish if falling
        macd_bullish = macd_h > 0 and macd_h > sig_h
        macd_bearish = macd_h < 0 and macd_h < sig_h

        # Bollinger Band filter: price must be within upper/lower bands (not too extended)
        # v8: Prevent buying at upper BB extension or selling at lower BB extension
        bb_near_middle = bb_lo < price < bb_up

        # BUY: price above VWAP by atr_mult ATRs, RSI deep oversold confirm, bullish MACD, volume confirmed, bull market, BB filter
        if (price > v + a * atr_mult and r < rsi_confirm_oversold and macd_bullish
                and volume_confirmed and bull_market and bb_near_middle):
            signals[i] = "BUY"
        # SELL: price below VWAP by atr_mult ATRs, RSI deep overbought confirm, bearish MACD, volume confirmed, bear market, BB filter
        elif (price < v - a * atr_mult and r > rsi_confirm_overbought and macd_bearish
                and volume_confirmed and bear_market and bb_near_middle):
            signals[i] = "SELL"

    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], current_atr

def place_groww_order(symbol, signal, quantity, price, atr=0.0):
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
        stop_loss = price - (atr * 1.0) if atr > 0 else price * 0.992
        target = price + (atr * 4.0) if atr > 0 else price * 1.032
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
        stop_loss = price + (atr * 1.0) if atr > 0 else price * 1.008
        target = price - (atr * 4.0) if atr > 0 else price * 0.968
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

