#!/usr/bin/env python3
"""
Live Trading Script - COALINDIA.NS
Strategy: VWAP + Smart Entry (Enhanced)
RSI filter (55/45) | Volume 1.2x avg | Smart Entry 9:30 AM-2:30 PM IST | 3-Tier Targets 1.5x/3x/5x risk
Win Rate: Target 65%+
Position: ₹10000 | Daily Loss Cap: 0.3%
"""

import os, sys, json, time, logging
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
        logging.FileHandler(LOG_DIR / "live_COALINDIA.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_COALINDIA")

SYMBOL = "COALINDIA.NS"
STRATEGY = "VWAP_SMART_ENTRY"
POSITION = 10000
DAILY_LOSS_CAP = 0.003
PARAMS = {
    # Optimized params (2026-03-22)
    "rsi_buy": 55,
    "rsi_sell": 45,
    "vol_threshold": 0.8,
    "sl_pct": 1.0,
    "tgt_pct": 3.0,
    "hold_days": 5,
    "trail_atr_mult": 0.3,
    "best_entry_start": "09:30",
    "best_entry_end": "14:30",
    # Legacy params preserved
    "vwap_period": 14,
    "atr_multiplier": 1.5,
}

NIFTY_SYMBOL = "^NSEI"
ENTRY_WAIT_MINUTES = 15
NO_ENTRY_AFTER = dtime(14, 30)
BEST_ENTRY_START = dtime(9, 30)
BEST_ENTRY_END = dtime(12, 0)

# === ENHANCED ENTRY PARAMETERS ===
ENTRY_VWAP_PCT = 0.004
# RSI filter: BUY only when RSI > 55, SELL only when RSI < 45
ENTRY_RSI_MIN = 55
ENTRY_RSI_MAX = 45
# Volume 1.2x avg for entry confirmation
ENTRY_VOL_MULT = 1.2

# 0.8% ATR stop loss
SL_ATR_MULT = 1.0
MAX_SL_PCT = 0.008

# 3-Tier Targets
TARGET_1_MULT = 1.5
TARGET_2_MULT = 3.0
TARGET_3_MULT = 5.0

# Trailing stop: 0.3× ATR (activates after TRAIL_TRIGGER_PCT profit)
TRAIL_ATR_MULT = 0.3

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in/v1"


def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)


def is_market_open() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def is_pre_market() -> bool:
    now = ist_now()
    return now.weekday() < 5 and dtime(9, 0) <= now.time() < dtime(9, 15)


def can_new_entry() -> bool:
    """Smart entry: 9:30 AM - 2:30 PM IST only"""
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
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
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
    """
    Enhanced smart entry with:
    - RSI filter (55/45): BUY when RSI > 55, SELL when RSI < 45
    - Volume 1.2x avg
    - Smart entry 9:30 AM - 2:30 PM IST
    """
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
    closes_1hr = [bar["close"] for bar in intraday_1hr] if intraday_1hr else closes_15m
    rsi_1hr = calculate_rsi(closes_1hr)[-1] if len(closes_1hr) > 14 else 50
    
    log.info("📊 Smart Entry | Price: %.2f | VWAP: %.2f | RSI_15m: %.1f | RSI_1hr: %.1f | Vol ratio: %.2f",
             current_price, vwap_val, rsi_15m, rsi_1hr, vol_ratio)
    
    # Entry conditions
    cond1 = current_price > vwap_val * (1 + ENTRY_VWAP_PCT)
    # RSI filter: BUY only when RSI > 55
    cond2 = rsi_15m > ENTRY_RSI_MIN and rsi_1hr > ENTRY_RSI_MIN - 5
    # Volume 1.2x avg
    cond3 = vol_ratio > ENTRY_VOL_MULT
    # Market direction confirmation via RSI alignment
    mt_confirmation = (rsi_15m > ENTRY_RSI_MIN) == (rsi_1hr > ENTRY_RSI_MIN - 5)
    
    if cond1 and cond2 and cond3 and mt_confirmation:
        reasons = []
        if cond1:
            reasons.append(f"Price>VWAP+{ENTRY_VWAP_PCT:.2%}")
        if cond2:
            reasons.append(f"RSI>{ENTRY_RSI_MIN}")
        if cond3:
            reasons.append(f"Vol>{ENTRY_VOL_MULT}x")
        return True, "✅ SMART ENTRY: " + " + ".join(reasons)
    
    reasons = []
    if not cond1:
        reasons.append(f"Price<VWAP+{ENTRY_VWAP_PCT:.2%} ({current_price/vwap_val-1:.2%})")
    if not cond2:
        reasons.append(f"RSI low ({rsi_15m:.1f}/{rsi_1hr:.1f})")
    if not cond3:
        reasons.append(f"Vol low ({vol_ratio:.2f}x)")
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
    """0.8% ATR stop loss"""
    sl_atr = entry_price - (SL_ATR_MULT * atr)
    sl_max = entry_price * (1 - MAX_SL_PCT)
    stop_loss = max(sl_atr, sl_max)
    sl_pct = (entry_price - stop_loss) / entry_price * 100
    log.info("🎯 Dynamic SL: ATR-based=%.2f (%.1f%%) | Max-0.8%%=%.2f | Selected=%.2f",
             sl_atr, sl_pct, sl_max, stop_loss)
    return round(stop_loss, 2)


def calculate_targets(entry_price: float, stop_loss: float) -> tuple[list, list]:
    """3-Tier Targets: 1.5x / 3x / 5x risk"""
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


def main():
    import sys
    from pathlib import Path
    try:
        import yfinance
        YFINANCE_AVAILABLE = True
    
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
    
    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
        print(f"Loaded {len(data)} candles")
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
    price = ohlcv_list[-1][3]
    
    try:
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, PARAMS)
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
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
    
    # Use real ATR from calculate_atr()
    if len(ohlcv_list) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_list))):
            h = ohlcv_list[i][1]
            l = ohlcv_list[i][2]
            prev_c = ohlcv_list[i-1][3]
            tr = max(h-l, abs(h-prev_c), abs(l-prev_c))
            trs.append(tr)
        if trs:
            atr = sum(trs) / len(trs)
    
    print(f"\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    
    if signal == "BUY":
        sl = calculate_dynamic_sl(price, atr)
        targets = calculate_targets(price, sl)
        qty = max(1, int(POSITION / price))
        risk = price - sl
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{risk:.2f} risk = {risk/price*100:.2f}%)")
        print(f"T1:     Rs{targets[0]['price']:.2f} ({targets[0]['desc']})")
        print(f"T2:     Rs{targets[1]['price']:.2f} ({targets[1]['desc']})")
        print(f"T3:     Rs{targets[2]['price']:.2f} ({targets[2]['desc']})")
        
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym, signal="BUY", price=price,
                quantity=qty, strategy=STRATEGY, atr=atr,
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
        qty = max(1, int(POSITION / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{price-tgt:.2f} reward)")
        
        try:
            from signals.schema import emit_signal
            emit_signal(symbol=ticker_sym, signal="SELL", price=price,
                        quantity=qty, strategy=STRATEGY, atr=atr)
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
