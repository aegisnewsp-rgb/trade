#!/usr/bin/env python3
"""
Live Trading Script - ADANIPORTS.NS
Strategy: VWAP with Infrastructure/Trade Sentiment
Win Rate: 66.67%
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x | Daily Loss Cap: 0.3%

Enhancements:
- VWAP entry: price > VWAP + 0.5%
- Baltic Dry Index sentiment check
- EXIM trade data awareness
- Capital allocation boost for high win rate
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
        logging.FileHandler(LOG_DIR / "live_ADANIPORTS.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ADANIPORTS")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL         = "ADANIPORTS.NS"
STRATEGY       = "VWAP_TRADE_AWARE"
WIN_RATE       = 66.67
POSITION       = 7000
STOP_LOSS_PCT  = 0.008
TARGET_MULT    = 4.0
DAILY_LOSS_CAP = 0.003

# VWAP entry threshold (price > VWAP + 0.5%)
VWAP_ENTRY_BUFFER = 0.005  # 0.5%

# Capital allocation boost for high win rate (>60%)
WIN_RATE_THRESHOLD = 60.0
CAPITAL_BOOST_MULT = 1.15  # 15% more capital given 66.67% win rate

PARAMS = {
    "vwap_period": 14,
    "atr_multiplier": 1.5,
    "vwap_entry_buffer": VWAP_ENTRY_BUFFER,
    "trade_sentiment_weight": 0.2,  # 20% weight to global trade data
    "bdi_check_enabled": True,
    "exim_check_enabled": True,
    "rsi_threshold": 55,
    "volume_multiplier": 1.2,
}

# ── Groww Production Enhancements ───────────────────────────────────────────
# 3-Tier Target System (1.5x / 3x / 5x risk multiples)
TARGET_1_MULT = 1.5   # Exit 1/3 at 1.5× risk — secure profit
TARGET_2_MULT = 3.0   # Exit 1/3 at 3× risk — main target
TARGET_3_MULT = 5.0   # Exit remaining at 5× risk — stretch target

# Smart Entry Window: 9:30 AM – 2:30 PM IST only
SMART_ENTRY_START = dtime(9, 30)
SMART_ENTRY_END   = dtime(14, 30)

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

def can_new_entry() -> bool:
    """HARD BLOCK: Only allow entries during smart session (9:30 AM - 2:30 PM IST)."""
    now = ist_now().time()
    if not (SMART_ENTRY_START <= now <= SMART_ENTRY_END):
        log.info("🛑 BLOCKED: Outside smart entry window (9:30 AM - 2:30 PM IST)")
        return False
    return True

def calculate_rsi(ohlcv: list, period: int = 14) -> list:
    """Calculate RSI for momentum confirmation."""
    rsi = [None] * period
    if len(ohlcv) < period + 1:
        return rsi
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    if len(gains) < period:
        return rsi + [None] * (len(ohlcv) - period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains) + 1):
        if i == period:
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
    return rsi

def get_avg_volume(ohlcv: list, lookback: int = 20) -> float:
    """Calculate average volume over lookback period."""
    if len(ohlcv) < lookback:
        return sum(ohlcv[j]["volume"] for j in range(len(ohlcv))) / len(ohlcv)
    return sum(ohlcv[j]["volume"] for j in range(-lookback, 0)) / lookback

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

def fetch_baltic_dry_index() -> float | None:
    """
    Fetch Baltic Dry Index (BDI) as a proxy for global trade sentiment.
    BDI > 2000 = strong trade activity
    BDI < 1000 = weak trade activity
    Returns normalized sentiment score 0.0-1.0
    """
    try:
        # BDI ticker on Yahoo Finance
        bdi_ticker = yf.Ticker("BDI.BK")
        data = bdi_ticker.history(period="5d")
        if data.empty:
            log.warning("BDI data empty, using neutral sentiment")
            return 0.5
        
        latest_bdi = float(data["Close"].iloc[-1])
        # Normalize: 500=0.0, 2500=1.0
        sentiment = max(0.0, min(1.0, (latest_bdi - 500) / 2000))
        log.info("Baltic Dry Index: %.0f -> Sentiment: %.2f", latest_bdi, sentiment)
        return sentiment
    except Exception as e:
        log.warning("Failed to fetch BDI: %s", e)
        return 0.5  # neutral fallback

def fetch_exim_sentiment() -> float:
    """
    Simple EXIM sentiment based on Indian trade data indicators.
    Uses USD/INR as proxy (weaker INR = stronger exports).
    Returns sentiment score 0.0-1.0
    """
    try:
        # USD/INR as proxy for trade competitiveness
        inr_ticker = yf.Ticker("USDINR=X")
        data = inr_ticker.history(period="5d")
        if data.empty:
            return 0.5
        
        current_inr = float(data["Close"].iloc[-1])
        # INR > 83 = weak (bearish for imports), < 82 = strong
        # Normalize: 84=0.0, 81=1.0
        sentiment = max(0.0, min(1.0, (84.0 - current_inr) / 3.0))
        log.info("USD/INR: %.2f -> EXIM Sentiment: %.2f", current_inr, sentiment)
        return sentiment
    except Exception as e:
        log.warning("Failed to fetch EXIM data: %s", e)
        return 0.5

def get_trade_sentiment() -> dict:
    """
    Aggregate global trade sentiment from multiple sources.
    Returns dict with overall sentiment and individual scores.
    """
    bdi_sentiment = 0.5
    exim_sentiment = 0.5
    
    if PARAMS.get("bdi_check_enabled", True):
        bdi_sentiment = fetch_baltic_dry_index() or 0.5
    
    if PARAMS.get("exim_check_enabled", True):
        exim_sentiment = fetch_exim_sentiment()
    
    # Weighted average: BDI (60%) + EXIM (40%)
    combined = (bdi_sentiment * 0.6) + (exim_sentiment * 0.4)
    
    return {
        "bdi": bdi_sentiment,
        "exim": exim_sentiment,
        "combined": combined,
        "bullish": combined > 0.55,
        "bearish": combined < 0.45,
    }

def calculate_effective_position(win_rate: float, base_position: int) -> int:
    """
    Adjust position size based on win rate.
    Higher win rate -> slightly more capital allocation.
    """
    if win_rate >= WIN_RATE_THRESHOLD:
        effective = int(base_position * CAPITAL_BOOST_MULT)
        log.info("Win rate %.2f%% > %.2f%% threshold: position boosted %d -> %d",
                 win_rate, WIN_RATE_THRESHOLD, base_position, effective)
        return effective
    return base_position

def vwap_signal(ohlcv: list, params: dict) -> tuple[str, float, float, dict]:
    """
    VWAP signal with trade sentiment filter.
    Enhanced with RSI filter (55/45) and volume confirmation (1.2x avg).

    Entry: price > VWAP + 0.5% AND trade sentiment bullish AND RSI > 55 AND volume > 1.2x avg
    Exit: price < VWAP - ATR OR RSI < 45 OR trade sentiment turns bearish
    """
    period         = params["vwap_period"]
    atr_mult       = params["atr_multiplier"]
    entry_buffer   = params.get("vwap_entry_buffer", 0.005)
    trade_weight   = params.get("trade_sentiment_weight", 0.2)
    rsi_threshold  = params.get("rsi_threshold", 55)
    vol_mult       = params.get("volume_multiplier", 1.2)

    vwap_vals  = calculate_vwap(ohlcv, period)
    atr_vals   = calculate_atr(ohlcv, period)
    rsi_vals   = calculate_rsi(ohlcv, period)
    avg_vol    = get_avg_volume(ohlcv)
    signals    = ["HOLD"] * len(ohlcv)

    # Get trade sentiment
    trade_sentiment = get_trade_sentiment()
    log.info("Trade sentiment: BDI=%.2f EXIM=%.2f Combined=%.2f",
             trade_sentiment["bdi"], trade_sentiment["exim"], trade_sentiment["combined"])

    for i in range(period, len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None or rsi_vals[i] is None:
            continue

        price  = ohlcv[i]["close"]
        vwap   = vwap_vals[i]
        atr    = atr_vals[i]
        rsi    = rsi_vals[i]
        volume = ohlcv[i]["volume"]
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0

        rsi_confirm = rsi > rsi_threshold
        vol_confirm = vol_ratio > vol_mult

        # BUY: price > VWAP + buffer AND bullish sentiment AND RSI > 55 AND volume > 1.2x
        if price > vwap * (1 + entry_buffer) and trade_sentiment["bullish"] and rsi_confirm and vol_confirm:
            signals[i] = "BUY"
        # SELL: price < VWAP - ATR OR RSI < 45 OR bearish sentiment
        elif price < vwap - atr * atr_mult or rsi < 45 or trade_sentiment["bearish"]:
            signals[i] = "SELL"

    current_signal = signals[-1] if signals else "HOLD"
    current_price  = ohlcv[-1]["close"]
    current_atr    = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
    current_rsi    = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else 50.0

    # Calculate VWAP premium/discount
    vwap_current = vwap_vals[-1] if vwap_vals and vwap_vals[-1] else 0.0
    vwap_premium = ((current_price - vwap_current) / vwap_current * 100) if vwap_current > 0 else 0.0

    metadata = {
        "vwap": vwap_current,
        "vwap_premium_pct": vwap_premium,
        "atr": current_atr,
        "rsi": current_rsi,
        "trade_sentiment": trade_sentiment,
        "entry_threshold": f"VWAP + {entry_buffer*100:.1f}% + RSI>{rsi_threshold} + Vol>{vol_mult}x",
    }

    return current_signal, current_price, current_atr, metadata

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
        atr = price * STOP_LOSS_PCT
        stop_loss = price - (atr * 1.0)
        target = price + (atr * TARGET_MULT)
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
        atr = price * STOP_LOSS_PCT
        stop_loss = price + (atr * 1.0)
        target = price - (atr * TARGET_MULT)
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
    ADANIPORTS VWAP strategy with trade sentiment overlay.
    - Entry: price > VWAP + 0.5% + bullish trade sentiment
    - Exit: price < VWAP - ATR OR bearish trade sentiment
    - Position boost: +15% given 66.67% win rate
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
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
    print(f"ADANIPORTS Trading System")
    print(f"Symbol: {ticker_sym} ({yahoo_sym})")
    print(f"Strategy: VWAP with Trade Sentiment")
    print(f"Win Rate: {WIN_RATE:.2f}%")
    print(f"{'='*60}")
    
    # Fetch data
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
    
    # Prepare OHLCV list
    ohlcv_list = []
    for idx, row in data.iterrows():
        ohlcv_list.append({
            "open":   float(row['Open']),
            "high":   float(row['High']),
            "low":    float(row['Low']),
            "close":  float(row['Close']),
            "volume": float(row['Volume'])
        })
    
    if not ohlcv_list:
        print("No OHLCV data")
        return
    
    # Get signal with trade sentiment
    signal, price, atr, metadata = vwap_signal(ohlcv_list, PARAMS)
    trade_sent = metadata["trade_sentiment"]
    
    # Calculate effective position based on win rate
    effective_position = calculate_effective_position(WIN_RATE, POSITION)
    
    # Output
    print(f"\n--- Market Analysis ---")
    print(f"Current Price:  Rs{price:.2f}")
    print(f"VWAP:           Rs{metadata['vwap']:.2f} ({metadata['vwap_premium_pct']:+.2f}%)")
    print(f"ATR:            Rs{metadata['atr']:.2f}")
    print(f"RSI:            {metadata.get('rsi', 50.0):.1f} (threshold: >55 bull / <45 bear)")
    print(f"Entry Window:   {'✅ 9:30 AM - 2:30 PM IST' if can_new_entry() else '❌ Outside window'}")
    print(f"Entry Buffer:   {metadata['entry_threshold']}")
    print(f"\n--- Trade Sentiment ---")
    print(f"BDI Sentiment:  {trade_sent['bdi']:.2f} ({'↑ Bullish' if trade_sent['bullish'] else '↓ Bearish' if trade_sent['bearish'] else '→ Neutral'})")
    print(f"EXIM Sentiment: {trade_sent['exim']:.2f}")
    print(f"Combined:       {trade_sent['combined']:.2f}")
    print(f"\n--- Signal ---")
    print(f"Signal:         {signal}")
    print(f"Base Position: Rs{POSITION}")
    print(f"Effective:      Rs{effective_position} (+{(effective_position/POSITION-1)*100:.0f}% for {WIN_RATE:.0f}% win rate)")

    if signal == "BUY" and can_new_entry():
        sl = round(price - atr * 1.0, 2)
        tgt1 = round(price + atr * TARGET_1_MULT, 2)
        tgt2 = round(price + atr * TARGET_2_MULT, 2)
        tgt3 = round(price + atr * TARGET_3_MULT, 2)
        qty = max(1, int(effective_position / price))
        print(f"Qty:            {qty}")
        print(f"Stop Loss:      Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target1:        Rs{tgt1:.2f} ({TARGET_1_MULT}× risk) - exit 1/3")
        print(f"Target2:        Rs{tgt2:.2f} ({TARGET_2_MULT}× risk) - exit 1/3")
        print(f"Target3:        Rs{tgt3:.2f} ({TARGET_3_MULT}× risk) - exit remaining")
        print(f"🎯 3-Tier Targets: {TARGET_1_MULT}× / {TARGET_2_MULT}× / {TARGET_3_MULT}× risk")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy=STRATEGY,
                atr=atr,
                metadata={
                    "source": Path(__file__).name,
                    "trade_sentiment": trade_sent,
                    "vwap_premium_pct": metadata["vwap_premium_pct"],
                    "effective_position": effective_position,
                    "win_rate": WIN_RATE,
                    "rsi": metadata.get("rsi", 50.0),
                    "targets": [tgt1, tgt2, tgt3],
                }
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("BUY", ticker_sym, price, qty)
            except:
                pass

    elif signal == "SELL" and can_new_entry():
        sl = round(price + atr * 1.0, 2)
        tgt1 = round(price - atr * TARGET_1_MULT, 2)
        tgt2 = round(price - atr * TARGET_2_MULT, 2)
        tgt3 = round(price - atr * TARGET_3_MULT, 2)
        qty = max(1, int(effective_position / price))
        print(f"Qty:            {qty}")
        print(f"Stop Loss:      Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target1:        Rs{tgt1:.2f} ({TARGET_1_MULT}× risk) - exit 1/3")
        print(f"Target2:        Rs{tgt2:.2f} ({TARGET_2_MULT}× risk) - exit 1/3")
        print(f"Target3:        Rs{tgt3:.2f} ({TARGET_3_MULT}× risk) - exit remaining")
        print(f"🎯 3-Tier Targets: {TARGET_1_MULT}× / {TARGET_2_MULT}× / {TARGET_3_MULT}× risk")

        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="SELL",
                price=price,
                quantity=qty,
                strategy=STRATEGY,
                atr=atr,
                metadata={
                    "source": Path(__file__).name,
                    "trade_sentiment": trade_sent,
                    "rsi": metadata.get("rsi", 50.0),
                    "targets": [tgt1, tgt2, tgt3],
                }
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("SELL", ticker_sym, price, qty)
            except:
                pass

    else:
        if signal != "HOLD":
            print(f"No trade — {signal} signal but outside smart entry window (9:30 AM - 2:30 PM IST)")
        else:
            print("No trade — HOLD signal")
            if not trade_sent["bullish"]:
                print("Reason: Trade sentiment not bullish")


if __name__ == "__main__":
    main()
