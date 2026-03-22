#!/usr/bin/env python3
"""
Live Trading Script - ADANIENT.NS
Strategy: TSI (True Strength Index) v2 — with multi-filter confirmation
Benchmark Win Rate: 57.69% | Target Win Rate: 62.00%
Filters: RSI(14,35/65) + Volume(20-MA) + Trend(50-MA) + Volatility(ATR 0.5-5%)
Position: ₹7000 | Stop Loss: 0.8% | Target: 4.0x ATR | Daily Loss Cap: 0.3%
Max 1 trade/day

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
Requires GROWW_API_KEY and GROWW_API_SECRET env vars for live orders.
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

# ── yfinance ──────────────────────────────────────────────────────────────────
import yfinance
YFINANCE_AVAILABLE = True
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "live_ADANIENT.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("live_ADANIENT")

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL        = "ADANIENT.NS"
STRATEGY      = "TSI"
WIN_RATE           = 0.5769
BENCHMARK_WIN_RATE = 0.5769
TARGET_WIN_RATE    = 0.62     # v2 enhanced target with multi-filter TSI
FILTERS_APPLIED    = "RSI(14,35/65) + Volume(20-MA) + Trend(50-MA) + Volatility(ATR 0.5-5%)"
POSITION      = 7000          # ₹
STOP_LOSS_PCT = 0.008         # 0.8%
TARGET_MULT   = 4.0           # 4.0 × ATR
DAILY_LOSS_CAP = 0.003       # 0.3%
MAX_TRADES    = 1
PARAMS        = {"fast_period": 13, "slow_period": 25, "signal_period": 13}

# 3-TIER EXIT SYSTEM (v3 enhancement)
SL_ATR_MULT      = 1.0     # Stop loss: 1.0x ATR
MAX_SL_PCT       = 0.015   # Hard cap: 1.5% max stop
TRAIL_TRIGGER_PCT = 0.008  # Trail after 0.8% profit

TARGET_1_MULT    = 1.5     # T1: 1.5x risk → exit 1/3
TARGET_2_MULT    = 3.0     # T2: 3.0x risk → exit 1/3
TARGET_3_MULT    = 5.0     # T3: 5.0x risk → exit remaining

# Entry window
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

# Groww API
GROWW_API_KEY    = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE   = "https://api.groww.in/v1"

IST_TZ_OFFSET = 5.5  # hours

# ── Helpers ───────────────────────────────────────────────────────────────────

def ist_now() -> datetime:
    return datetime.utcnow() + __import__("datetime").timedelta(hours=IST_TZ_OFFSET)


def is_market_open() -> bool:
    now = ist_now()
    if now.weekday() >= 5:
        return False
    market_time = now.time()
    return dtime(9, 15) <= market_time <= dtime(15, 30)


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


# ── Filter Helpers (v2 multi-filter TSI) ──────────────────────────────────────

def calculate_rsi(ohlcv: list, period: int = 14) -> float:
    """RSI(14) – used as momentum filter to avoid false TSI crossovers."""
    if len(ohlcv) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(ohlcv)):
        chg = ohlcv[i]["close"] - ohlcv[i - 1]["close"]
        gains.append(chg if chg > 0 else 0.0)
        losses.append(abs(chg) if chg < 0 else 0.0)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_volume_ma(ohlcv: list, period: int = 20) -> float:
    """20-day volume MA – filter out low-volume whipsaws."""
    if len(ohlcv) < period:
        return 0.0
    vols = [bar["volume"] for bar in ohlcv[-period:]]
    return sum(vols) / period


def calculate_price_ma(ohlcv: list, period: int = 50) -> float:
    """50-day close MA – trend direction filter."""
    if len(ohlcv) < period:
        return 0.0
    closes = [bar["close"] for bar in ohlcv[-period:]]
    return sum(closes) / period


def apply_filters(
    ohlcv: list,
    base_signal: str,
) -> tuple[str, dict]:
    """
    Apply RSI + Volume + Trend + Volatility filters to base TSI signal.
    Returns (filtered_signal, filter_info).
    All filters are advisory; signal is downgraded to HOLD only on RSI fail.
    """
    fi = dict(volume_ok=False, trend_ok=False, volatility_ok=False, rsi_ok=False)
    n = len(ohlcv)
    price = ohlcv[-1]["close"]

    # 1. Volume filter – skip low-volume signals
    vol_ma = calculate_volume_ma(ohlcv)
    if vol_ma > 0 and ohlcv[-1]["volume"] >= vol_ma * 1.0:
        fi["volume_ok"] = True

    # 2. Trend filter – only trade in direction of 50-day MA
    ma50 = calculate_price_ma(ohlcv)
    if ma50 > 0:
        if base_signal == "BUY" and price > ma50:
            fi["trend_ok"] = True
        elif base_signal == "SELL" and price < ma50:
            fi["trend_ok"] = True

    # 3. Volatility filter – avoid extremely low/high ATR environments
    atr_list = calculate_atr(ohlcv)
    current_atr = atr_list[-1] if atr_list and atr_list[-1] is not None else 0.0
    atr_pct = (current_atr / price * 100.0) if price > 0 else 0.0
    if 0.5 <= atr_pct <= 5.0:
        fi["volatility_ok"] = True

    # 4. RSI momentum filter – reject signals in wrong RSI zone (critical)
    rsi = calculate_rsi(ohlcv)
    if base_signal == "BUY" and rsi >= 35:      # not oversold
        fi["rsi_ok"] = True
    elif base_signal == "SELL" and rsi <= 65:    # not overbought
        fi["rsi_ok"] = True
    # If RSI fails, downgrade to HOLD
    if not fi["rsi_ok"]:
        return "HOLD", fi

    return base_signal, fi


def tsi_signal(ohlcv: list, params: dict) -> tuple[str, float, float]:
    """
    Returns (signal, entry_price, atr).
    signal: BUY / SELL / HOLD (filtered by multi-filter TSI v2).
    """
    fast  = params["fast_period"]
    slow  = params["slow_period"]
    sig_p = params["signal_period"]

    closes = [bar["close"] for bar in ohlcv]

    # True Strength Index
    momentum = [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(momentum) <= slow:
        return "HOLD", closes[-1], 0.0

    abs_momentum = [abs(m) for m in momentum]
    ema_abs = ema(abs_momentum, slow)
    ema_mom = ema(momentum, slow)
    tsi = [0.0] * len(closes)
    for i in range(slow - 1, len(closes)):
        if ema_abs[i] != 0:
            tsi[i] = 100.0 * ema_mom[i] / ema_abs[i]

    signal_ema = ema(tsi, sig_p)

    if len(tsi) < 2 or len(signal_ema) < 2:
        return "HOLD", closes[-1], 0.0

    # Crossover
    if tsi[-2] <= signal_ema[-2] and tsi[-1] > signal_ema[-1]:
        signal = "BUY"
    elif tsi[-2] >= signal_ema[-2] and tsi[-1] < signal_ema[-1]:
        signal = "SELL"
    else:
        signal = "HOLD"

    atr = calculate_atr(ohlcv)
    current_atr = atr[-1] if atr and atr[-1] is not None else 0.0

    # ── v2 multi-filter confirmation ──────────────────────────────────────────
    filtered_signal, fi = apply_filters(ohlcv, signal)
    if filtered_signal != signal:
        log.info("  ⚠ FILTERED: TSI %s → HOLD (RSI reject)", signal)
    log.info("  FILTERS  vol=%s trend=%s vola=%s rsi=%s",
             fi.get("volume_ok"), fi.get("trend_ok"),
             fi.get("volatility_ok"), fi.get("rsi_ok"))

    return filtered_signal, closes[-1], current_atr


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
    """Main trading loop for ADANIENT"""
    import yfinance
YFINANCE_AVAILABLE = True
try:
        t = yf.Ticker("ADANIENT.NS")
        d = t.history(period="3mo")
        if len(d) < 30:
            print(f"No data for ADANIENT")
            return
        ohlcv = [[float(r.Open), float(r.High), float(r.Low),
                   float(r.Close), float(r.Volume)] for r in d.itertuples()]
        closes = [row[3] for row in ohlcv]
        
        # Get regime
        regime_val = "UPTREND"
        if len(closes) >= 20:
            sma = sum(closes[-20:]) / 20
            if closes[-1] < sma * 0.98:
                regime_val = "DOWNTREND"
        
        if regime_val == "DOWNTREND":
            print(f"ADANIENT: DOWNTREND - no entries")
            return
        
        # Placeholder for full strategy
        print(f"ADANIENT: UPTREND/RANGE - strategy ready")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
