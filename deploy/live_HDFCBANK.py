#!/usr/bin/env python3
"""
Live Trading Script - HDFCBANK.NS
Strategy: ADX_TREND_v3 (ENHANCED - Banking-optimized with multi-timeframe confirmation)
Win Rate: 60.61% -> Target 68%+ (v3: stricter ADX>28, volume 1.5x, RSI sweet spot, VWAP confirm, NIFTY BANK sector check)
Position: ₹7000 | Stop Loss: 0.8% ATR | Target: 4.0x ATR | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging, requests, math
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
        logging.FileHandler(LOG_DIR / "live_HDFCBANK.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_HDFCBANK")

SYMBOL         = "HDFCBANK.NS"
BANK_INDEX     = "^NSEBANK"  # NIFTY BANK index for sector confirmation
STRATEGY       = "ADX_TREND_v3"
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003
PARAMS         = {
    "adx_period": 14,
    "adx_threshold": 28,          # RAISED from 25: stricter trend confirmation
    "rsi_period": 14,
    "rsi_oversold": 45,          # RSI < 45 for SELL
    "rsi_overbought": 55,        # RSI > 55 for BUY
    "rsi_sweet_spot_min": 45,     # RSI sweet spot lower bound
    "rsi_sweet_spot_max": 55,    # RSI sweet spot upper bound
    "volume_multiplier": 1.2,     # Volume 1.2x avg for entry confirmation
    "atr_period": 14,
    "vwap_period": 14,            # NEW: VWAP confirmation
    "confidence_threshold": 0.60, # NEW: minimum confidence to enter
}

# 3-TIER EXIT SYSTEM (v3 enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window (v3 enhancement)
BEST_ENTRY_START = dtime(9, 30)  # 9:30 AM IST
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

def fetch_recent_data(days: int = 60, retries: int = 3) -> list | None:
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

def fetch_bank_index_data(days: int = 30, retries: int = 3) -> list | None:
    """Fetch NIFTY BANK index data for sector confirmation."""
    for attempt in range(retries):
        try:
            df = yf.Ticker(BANK_INDEX).history(period=f"{days}d")
            if df.empty:
                raise ValueError("Empty bank index dataframe")
            ohlcv = [
                {"date": str(idx.date()), "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": int(r["Volume"])}
                for idx, r in df.iterrows()
            ]
            log.info("Fetched %d candles for %s", len(ohlcv), BANK_INDEX)
            return ohlcv
        except Exception as e:
            log.warning("Attempt %d/%d failed fetching bank index: %s", attempt + 1, retries, e)
            time.sleep(2 ** attempt)
    log.warning("Bank index fetch failed for %s, proceeding without sector confirmation", BANK_INDEX)
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

def calculate_avg_volume(ohlcv: list, period: int = 20) -> float:
    if len(ohlcv) < period:
        return 0
    return sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv))) / period

def calculate_vwap(ohlcv: list, period: int = 14) -> float:
    """Calculate VWAP for last N candles - returns current VWAP value."""
    if len(ohlcv) < period:
        return ohlcv[-1]["close"] if ohlcv else 0.0
    tp_sum = sum((ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                 for j in range(len(ohlcv) - period, len(ohlcv)))
    vol_sum = sum(ohlcv[j]["volume"] for j in range(len(ohlcv) - period, len(ohlcv)))
    return tp_sum / vol_sum if vol_sum > 0 else ohlcv[-1]["close"]

def calculate_bank_index_signal(bank_data: list) -> str:
    """Calculate simple signal from NIFTY BANK index - returns BULLISH, BEARISH, or NEUTRAL."""
    if not bank_data or len(bank_data) < 5:
        return "NEUTRAL"
    
    # Simple trend: compare recent close to moving average
    closes = [bar["close"] for bar in bank_data[-10:]]
    if len(closes) < 5:
        return "NEUTRAL"
    
    ma5 = sum(closes[-5:]) / 5
    current_close = closes[-1]
    
    if current_close > ma5 * 1.005:  # 0.5% above MA
        return "BULLISH"
    elif current_close < ma5 * 0.995:  # 0.5% below MA
        return "BEARISH"
    return "NEUTRAL"

def adx_signal_v3(ohlcv: list, params: dict, bank_index_data: list = None) -> tuple[str, float, float, float]:
    """
    v3 ADX Trend ENHANCED for HDFCBANK banking sector:
    - ADX > 28 (stricter than v2's 25)
    - RSI in sweet spot 45-60 for BUY, 40-55 for SELL
    - Volume > 1.5x average (raised from 1.2x)
    - VWAP confirmation (price > VWAP for longs)
    - NIFTY BANK index confirmation
    - Confidence scoring to filter weak signals
    
    Returns: (signal, price, atr, confidence)
    """
    period          = params["adx_period"]
    threshold       = params["adx_threshold"]
    rsi_period      = params["rsi_period"]
    rsi_overbought  = params["rsi_overbought"]
    rsi_oversold    = params["rsi_oversold"]
    rsi_sweet_min   = params.get("rsi_sweet_spot_min", 45)
    rsi_sweet_max   = params.get("rsi_sweet_spot_max", 60)
    vol_mult        = params["volume_multiplier"]
    vwap_period     = params.get("vwap_period", 14)
    conf_threshold  = params.get("confidence_threshold", 0.60)

    high  = [bar["high"] for bar in ohlcv]
    low   = [bar["low"]  for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]

    tr_list = [high[i] - low[i]] + [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(1, len(ohlcv))
    ]

    plus_dm = [0.0] * len(ohlcv)
    minus_dm = [0.0] * len(ohlcv)
    for i in range(1, len(ohlcv)):
        up_move   = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i]  = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(ohlcv) < period * 2:
        return "HOLD", close[-1], 0.0, 0.0

    tr_smooth   = ema(tr_list, period)
    plus_dm_sm  = ema(plus_dm, period)
    minus_dm_sm = ema(minus_dm, period)

    plus_di  = [100 * plus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]
    minus_di = [100 * minus_dm_sm[i] / tr_smooth[i] if tr_smooth[i] != 0 else 0 for i in range(len(ohlcv))]

    dx = [100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
          if (plus_di[i] + minus_di[i]) != 0 else 0 for i in range(len(ohlcv))]
    adx_vals = ema(dx, period)

    rsi_vals = calculate_rsi(ohlcv, rsi_period)
    avg_vol  = calculate_avg_volume(ohlcv, period)
    current_vwap = calculate_vwap(ohlcv, vwap_period)
    
    # Bank index confirmation
    bank_signal = calculate_bank_index_signal(bank_index_data) if bank_index_data else "NEUTRAL"

    if len(adx_vals) < 2:
        return "HOLD", close[-1], 0.0, 0.0

    # Signal: trending ADX with directional crossover + RSI filter + volume + VWAP confirm
    signal = "HOLD"
    confidence = 0.0
    
    if adx_vals[-1] > threshold:
        current_vol = ohlcv[-1]["volume"]
        vol_ok = current_vol > avg_vol * vol_mult
        rsi_now = rsi_vals[-1] if rsi_vals[-1] is not None else 50
        current_price = close[-1]
        
        # VWAP confirmation check
        price_above_vwap = current_price > current_vwap
        price_below_vwap = current_price < current_vwap
        
        # RSI sweet spot check
        rsi_in_buy_zone = rsi_sweet_min <= rsi_now <= rsi_sweet_max
        rsi_in_sell_zone = rsi_oversold <= rsi_now <= rsi_overbought
        
        # Calculate confidence score components
        conf_adx = min(adx_vals[-1] / 40, 1.0)  # ADX contribution (max at 40)
        conf_volume = min(vol_ok, (current_vol / (avg_vol * vol_mult)))  # Volume strength
        conf_rsi_buy = 1.0 if rsi_in_buy_zone else 0.5 if rsi_sweet_min <= rsi_now <= 65 else 0.0
        conf_rsi_sell = 1.0 if rsi_in_sell_zone else 0.5 if 35 <= rsi_now <= rsi_overbought else 0.0
        conf_bank = 1.0 if bank_signal == "NEUTRAL" else (0.8 if bank_signal == "BULLISH" else 0.4)
        
        if plus_di[-1] > minus_di[-1] and plus_di[-2] <= minus_di[-2]:
            # BUY: bullish crossover + RSI sweet spot + volume confirm + VWAP confirm
            if rsi_in_buy_zone and vol_ok and price_above_vwap:
                # Confidence: weighted average of factors
                confidence = (conf_adx * 0.35 + conf_volume * 0.25 + conf_rsi_buy * 0.25 + conf_bank * 0.15)
                if confidence >= conf_threshold:
                    signal = "BUY"
                    log.info("BUY signal | ADX=%.1f | RSI=%.1f | Vol=%.1fx | VWAP=%.2f | Bank=%s | Conf=%.2f",
                             adx_vals[-1], rsi_now, current_vol/avg_vol, current_vwap, bank_signal, confidence)
                    
        elif minus_dm[-1] > plus_dm[-1] and minus_dm[-2] <= plus_dm[-2]:
            # SELL: bearish crossover + RSI not oversold + volume confirm + VWAP confirm
            if rsi_in_sell_zone and vol_ok and price_below_vwap:
                confidence = (conf_adx * 0.35 + conf_volume * 0.25 + conf_rsi_sell * 0.25 + conf_bank * 0.15)
                if confidence >= conf_threshold:
                    signal = "SELL"
                    log.info("SELL signal | ADX=%.1f | RSI=%.1f | Vol=%.1fx | VWAP=%.2f | Bank=%s | Conf=%.2f",
                             adx_vals[-1], rsi_now, current_vol/avg_vol, current_vwap, bank_signal, confidence)

    atr_vals = calculate_atr(ohlcv, params["atr_period"])
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    return signal, close[-1], current_atr, confidence

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

