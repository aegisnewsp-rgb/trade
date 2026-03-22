#!/usr/bin/env python3
"""
Live Trading Script for SHREECEM.NS
Strategy: TSI + Multi-Filter (SMA Trend + EMA Confirm + RSI + Volume + Volatility)
Win Rate: 58.06% -> Enhanced target: 60%+ (v3)
Position Size: ₹7,000 | Stop Loss: 0.65% ATR | Target: 4.0x ATR
Daily Loss Cap: 0.3% of capital
Max 1 trade per day

v3 Enhancements applied:
- Added ADX(14) trend strength filter: require ADX > 20 for valid signals
- RSI thresholds tightened: oversold 42→45, overbought 60→58
- TSI threshold raised: 3.0→4.5 to filter weaker crossovers
- Added TSI momentum slope filter: slope must be positive for BUY, negative for SELL
- Volume threshold raised: 1.3x→1.5x for higher-quality confirm
- Added minimum TSI distance from zero line: |TSI| > 10 for stronger momentum

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
Requires GROWW_API_KEY and GROWW_API_SECRET env vars for live orders.
"""

import os
import sys
import logging
import json
import requests
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple
from pathlib import Path

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
SYMBOL = "SHREECEM.NS"
STRATEGY = "TSI_MULTI_FILTER"
BENCHMARK_WIN_RATE = 0.5806   # v3 enhanced: targeting 60%+
TARGET_WIN_RATE = 0.60

POSITION_SIZE = 7000
DAILY_LOSS_CAP = 0.003
MAX_TRADES_PER_DAY = 1
STOP_LOSS_ATR_MULT = 0.65  # v2: was 0.5 - too tight, cutting winners early
TARGET_ATR_MULT = 4.0

TSI_FAST = 13
TSI_SLOW = 25
TSI_SIGNAL = 9   # v2: was 13 - faster response, catch moves earlier
TSI_THRESHOLD = 4.5        # v3: was 3.0 - filter weaker crossovers
ADX_PERIOD = 14
ADX_THRESHOLD = 20.0       # v3: require ADX > 20 for trend strength confirmation
ATR_PERIOD = 14
SMA_PERIOD = 50             # Trend filter period
RSI_PERIOD = 14
RSI_OVERSOLD = 45           # v3: was 42 - tighter, only buy in stronger oversold
RSI_OVERBOUGHT = 58        # v3: was 60 - tighter, sell before overbought
VOLUME_MA_PERIOD = 20
VOLUME_THRESHOLD = 1.5     # v3: was 1.3 - higher quality volume confirm
MIN_ATR_PCT = 0.015         # Min ATR as % of price (1.5%) - avoid low vol

GROWW_API_KEY = os.getenv("GROWW_API_KEY")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
GROWW_API_BASE = "https://api.groww.in"
GROWW_API_TIMEOUT = 30

LOG_DIR = Path("/tmp")
STATE_FILE = Path("/home/node/workspace/trade-project/deploy/state_SHREECEM.json")

def setup_logging():
    log_file = LOG_DIR / f"trades_SHREECEM.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    return {"trades_today": 0, "last_trade_date": None, "daily_pnl": 0, "daily_loss": 0, "position": None, "last_signal": None}

def save_state(state: Dict):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def reset_daily_state(state: Dict) -> Dict:
    today = date.today().isoformat()
    if state.get("last_trade_date") != today:
        state["trades_today"] = 0
        state["last_trade_date"] = today
        state["daily_pnl"] = 0
        state["daily_loss"] = 0
    return state

def fetch_recent_data(symbol: str, days: int = 90) -> Optional[List[Dict]]:
    if not YFINANCE_AVAILABLE:
        logger.error("yfinance not available")
        return None
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d")
        if df.empty:
            logger.error(f"No data returned for {symbol}")
            return None
        ohlcv = []
        for idx, row in df.iterrows():
            ohlcv.append({"date": idx.isoformat(), "open": float(row["Open"]), "high": float(row["High"]), "low": float(row["Low"]), "close": float(row["Close"]), "volume": int(row["Volume"])})
        logger.info(f"Fetched {len(ohlcv)} days of data for {symbol}")
        return ohlcv
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        return None

def calculate_atr(ohlcv: List[Dict], period: int = 14) -> List[float]:
    atr = []
    prev_close = None
    for i, bar in enumerate(ohlcv):
        high = bar["high"]
        low = bar["low"]
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        if i < period - 1:
            atr.append(None)
        elif i == period - 1:
            atr.append(tr)
        else:
            atr.append((atr[-1] * (period - 1) + tr) / period)
        prev_close = bar["close"]
    return atr

def calculate_tsi(ohlcv: List[Dict], fast: int = 13, slow: int = 25, signal: int = 13) -> Tuple[List[float], List[float]]:
    closes = [bar["close"] for bar in ohlcv]
    momentum = []
    for i in range(1, len(closes)):
        momentum.append(closes[i] - closes[i-1])
    if len(momentum) < slow:
        return [50.0] * len(ohlcv), [50.0] * len(ohlcv)
    def calc_ema(data, period):
        if len(data) < period:
            return data
        ema = [data[0]]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
        return ema
    mom_ema1 = calc_ema(momentum, fast)
    mom_ema2 = calc_ema(mom_ema1, slow)
    abs_mom_ema1 = calc_ema([abs(m) for m in momentum], fast)
    abs_mom_ema2 = calc_ema(abs_mom_ema1, slow)
    tsi_values = []
    for i in range(len(momentum)):
        if abs_mom_ema2[i] != 0:
            tsi = 100 * (mom_ema2[i] / abs_mom_ema2[i])
        else:
            tsi = 50.0
        tsi_values.append(tsi)
    signal_values = calc_ema(tsi_values, signal)
    while len(tsi_values) < len(ohlcv):
        tsi_values.insert(0, 50.0)
        signal_values.insert(0, 50.0)
    return tsi_values, signal_values

def calculate_sma(ohlcv: List[Dict], period: int = 50) -> List[float]:
    """Simple Moving Average"""
    sma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            sma.append(None)
        else:
            avg = sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period
            sma.append(avg)
    return sma

def calculate_ema(ohlcv: List[Dict], period: int = 20) -> List[float]:
    """Exponential Moving Average - faster reaction than SMA"""
    ema = []
    multiplier = 2 / (period + 1)
    for i in range(len(ohlcv)):
        if i < period - 1:
            ema.append(None)
        elif i == period - 1:
            # Seed with SMA
            avg = sum(ohlcv[j]["close"] for j in range(i - period + 1, i + 1)) / period
            ema.append(avg)
        else:
            ema.append((ohlcv[i]["close"] - ema[-1]) * multiplier + ema[-1])
    return ema

def calculate_rsi(ohlcv: List[Dict], period: int = 14) -> List[float]:
    """RSI (Relative Strength Index)"""
    if len(ohlcv) < period + 1:
        return [50.0] * len(ohlcv)
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    rsi = [50.0] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - (100 / (1 + rs)))
    rsi = [50.0] * (period) + rsi[period:]
    return rsi

def calculate_volume_ma(ohlcv: List[Dict], period: int = 20) -> List[float]:
    """Volume Moving Average"""
    vol_ma = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vol_ma.append(None)
        else:
            avg = sum(ohlcv[j]["volume"] for j in range(i - period + 1, i + 1)) / period
            vol_ma.append(avg)
    return vol_ma

def calculate_adx(ohlcv: List[Dict], period: int = 14) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate ADX (Average Directional Index) and directional indicators.
    Returns (adx, plus_di, minus_di) tuples.
    ADX > 20 indicates strong trend - we'll require this for valid signals.
    """
    if len(ohlcv) < period * 2:
        return [20.0] * len(ohlcv), [0.0] * len(ohlcv), [0.0] * len(ohlcv)

    high = [bar["high"] for bar in ohlcv]
    low = [bar["low"] for bar in ohlcv]
    close = [bar["close"] for bar in ohlcv]

    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(1, len(ohlcv)):
        # True Range
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr = max(hl, hc, lc)
        tr_list.append(tr)

        # Directional Movement
        up_move = high[i] - high[i-1]
        down_move = low[i-1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)

        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)

    # Smooth with Wilder's smoothing
    def wilder_smooth(data, period):
        if len(data) < period:
            return [sum(data) / len(data)] * len(data)
        result = []
        result.append(sum(data[:period]) / period)
        for i in range(period, len(data)):
            result.append((result[-1] * (period - 1) + data[i]) / period)
        return result

    tr_smooth = wilder_smooth(tr_list, period)
    plus_smooth = wilder_smooth(plus_dm, period)
    minus_smooth = wilder_smooth(minus_dm, period)

    plus_di = []
    minus_di = []
    dx = []

    for i in range(len(tr_smooth)):
        if tr_smooth[i] == 0:
            plus_di.append(0)
            minus_di.append(0)
        else:
            plus_di.append(100 * plus_smooth[i] / tr_smooth[i])
            minus_di.append(100 * minus_smooth[i] / tr_smooth[i])

        di_sum = plus_di[-1] + minus_di[-1]
        if di_sum == 0:
            dx.append(0)
        else:
            dx.append(100 * abs(plus_di[-1] - minus_di[-1]) / di_sum)

    # ADX is the smoothed DX
    adx_smooth = wilder_smooth(dx, period)

    # Pad to match ohlcv length
    adx = [20.0]  # First value unknown
    adx.extend(adx_smooth)
    plus_di = [0.0] + plus_di
    minus_di = [0.0] + minus_di

    # Ensure same length
    while len(adx) < len(ohlcv):
        adx.append(adx[-1])
    while len(plus_di) < len(ohlcv):
        plus_di.append(plus_di[-1])
    while len(minus_di) < len(ohlcv):
        minus_di.append(minus_di[-1])

    return adx, plus_di, minus_di

def generate_signal(ohlcv: List[Dict], tsi: List[float], signal_line: List[float],
                    sma_vals: List[float], ema_vals: List[float], rsi_vals: List[float],
                    vol_ma: List[float], atr_vals: List[float],
                    adx_vals: List[float] = None) -> Tuple[str, str]:
    """
    Generate signal with multi-filter confirmation.
    Returns (signal, filter_reason) tuple.
    v3: Added ADX trend strength filter + TSI momentum slope for more selective entries.
    """
    if len(ohlcv) < 2 or len(tsi) < 2 or len(signal_line) < 2:
        return "HOLD", "insufficient_data"

    current_price = ohlcv[-1]["close"]
    prev_tsi = tsi[-2]
    current_tsi = tsi[-1]
    prev_signal = signal_line[-2]
    current_signal = signal_line[-1]

    # Check volatility filter
    current_atr = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0
    if current_atr > 0 and (current_atr / current_price) < MIN_ATR_PCT:
        return "HOLD", "low_volatility"

    # Check volume filter
    current_vol = ohlcv[-1]["volume"]
    avg_vol = vol_ma[-1] if vol_ma and vol_ma[-1] is not None else current_vol
    if avg_vol > 0 and (current_vol / avg_vol) < VOLUME_THRESHOLD:
        return "HOLD", "low_volume"

    # Check ADX trend strength filter (v3)
    if adx_vals and len(adx_vals) >= 2:
        current_adx = adx_vals[-1] if adx_vals[-1] is not None else 20.0
        if current_adx <= ADX_THRESHOLD:
            return "HOLD", f"adx_weak({current_adx:.1f})"

    # Check SMA(50) trend filter - primary trend
    current_sma = sma_vals[-1] if sma_vals and sma_vals[-1] is not None else current_price
    above_sma = current_price > current_sma

    # Check EMA(20) trend filter - faster confirmation
    current_ema = ema_vals[-1] if ema_vals and ema_vals[-1] is not None else current_price
    above_ema = current_price > current_ema

    # Check RSI filter
    current_rsi = rsi_vals[-1] if rsi_vals and len(rsi_vals) >= 1 else 50.0

    # Check TSI threshold (require meaningful crossover) - v3 tightened
    tsi_diff = abs(current_tsi - current_signal)
    strong_cross = tsi_diff >= TSI_THRESHOLD

    # v3: Check TSI distance from zero line for stronger momentum
    strong_momentum = abs(current_tsi) > 10.0

    # v3: Check TSI momentum slope (must be rising for BUY, falling for SELL)
    # Use 3-bar slope for smoother momentum direction
    tsi_slope_positive = len(tsi) >= 4 and tsi[-1] > tsi[-3]
    tsi_slope_negative = len(tsi) >= 4 and tsi[-1] < tsi[-3]

    # BUY signal: TSI crosses above signal + all filters
    if prev_tsi <= prev_signal and current_tsi > current_signal:
        if not strong_cross:
            return "HOLD", f"tsi_weak_crossing({tsi_diff:.2f})"
        if not strong_momentum:
            return "HOLD", f"tsi_weak_momentum({abs(current_tsi):.1f})"
        if not tsi_slope_positive:
            return "HOLD", "tsi_not_rising"
        if not above_sma:
            return "HOLD", "below_sma_trend"
        if not above_ema:
            return "HOLD", "below_ema_trend"
        if current_rsi < RSI_OVERSOLD:
            return "HOLD", f"rsi_oversold({current_rsi:.1f})"
        return "BUY", "all_filters_passed"

    # SELL signal: TSI crosses below signal + all filters
    elif prev_tsi >= prev_signal and current_tsi < current_signal:
        if not strong_cross:
            return "HOLD", f"tsi_weak_crossing({tsi_diff:.2f})"
        if not strong_momentum:
            return "HOLD", f"tsi_weak_momentum({abs(current_tsi):.1f})"
        if not tsi_slope_negative:
            return "HOLD", "tsi_not_falling"
        if above_sma:
            return "HOLD", "above_sma_trend"
        if above_ema:
            return "HOLD", "above_ema_trend"
        if current_rsi > RSI_OVERBOUGHT:
            return "HOLD", f"rsi_overbought({current_rsi:.1f})"
        return "SELL", "all_filters_passed"

    return "HOLD", "no_crossover"

def calculate_stop_loss(entry_price: float, atr: float) -> float:
    return entry_price - (atr * STOP_LOSS_ATR_MULT)

def calculate_target(entry_price: float, atr: float) -> float:
    return entry_price + (atr * TARGET_ATR_MULT)

def check_daily_loss_limit(state: Dict, capital: float) -> bool:
    daily_loss_cap_amount = capital * DAILY_LOSS_CAP
    if abs(state.get("daily_loss", 0)) >= daily_loss_cap_amount:
        logger.warning(f"Daily loss limit reached")
        return True
    return False

def groww_place_order(symbol: str, transaction_type: str, quantity: int, price: float) -> Optional[Dict]:
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        logger.info(f"📋 SIGNAL: {transaction_type} {quantity} shares of {symbol} at ₹{price:.2f}")
        logger.info("   (No API credentials - order not placed)")
        return None
    try:
        headers = {"Content-Type": "application/json", "X-Api-Key": GROWW_API_KEY, "X-Secret-Key": GROWW_API_SECRET}
        payload = {"symbol": symbol, "transaction_type": transaction_type, "quantity": quantity, "price": price, "order_type": "LIMIT"}
        response = requests.post(f"{GROWW_API_BASE}/v1/orders", headers=headers, json=payload, timeout=GROWW_API_TIMEOUT)
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Order placed successfully: {result}")
            return result
        else:
            logger.error(f"Order failed: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Groww API error: {e}")
        return None

def execute_trade(signal: str, current_price: float, atr: float, state: Dict, capital: float) -> Dict:
    result = {"action": "NONE", "signal": signal, "price": current_price}
    state = reset_daily_state(state)
    if signal == "HOLD":
        return result
    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        logger.info("Max trades reached for today")
        return result
    if check_daily_loss_limit(state, capital):
        return result
    quantity = int(POSITION_SIZE / current_price)
    if quantity < 1:
        return result
    if signal == "BUY":
        stop_loss = calculate_stop_loss(current_price, atr)
        target = calculate_target(current_price, atr)
        logger.info(f"🟢 BUY: ₹{current_price:.2f} | Qty:{quantity} | SL:₹{stop_loss:.2f} | TGT:₹{target:.2f}")
        order = groww_place_order(SYMBOL, "BUY", quantity, current_price)
        result = {"action": "BUY", "signal": signal, "price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "order": order}
        state["trades_today"] += 1
        state["position"] = {"entry_price": current_price, "quantity": quantity, "stop_loss": stop_loss, "target": target, "entry_time": datetime.now().isoformat()}
    elif signal == "SELL":
        if not state.get("position"):
            logger.info(f"🔴 SELL: ₹{current_price:.2f} (No position)")
            return result
        pos = state["position"]
        quantity = pos["quantity"]
        pnl = (current_price - pos["entry_price"]) * quantity
        logger.info(f"🔴 SELL: ₹{current_price:.2f} | P&L: ₹{pnl:.2f}")
        order = groww_place_order(SYMBOL, "SELL", quantity, current_price)
        result = {"action": "SELL", "signal": signal, "price": current_price, "quantity": quantity, "entry_price": pos["entry_price"], "pnl": pnl, "order": order}
        state["trades_today"] += 1
        state["daily_pnl"] += pnl
        if pnl < 0:
            state["daily_loss"] += pnl
        state["position"] = None
    save_state(state)
    return result

def main():
    logger.info("=" * 60)
    logger.info(f"LIVE TRADING - {SYMBOL} | {STRATEGY}")
    logger.info(f"Win Rate: {BENCHMARK_WIN_RATE * 100:.2f}% -> Target: {TARGET_WIN_RATE*100:.0f}% | Pos: ₹{POSITION_SIZE:,} | SL: {STOP_LOSS_ATR_MULT*100:.1f}% ATR | TGT: {TARGET_ATR_MULT}x ATR")
    logger.info(f"Filters: SMA({SMA_PERIOD})+EMA(20) | ADX>{ADX_THRESHOLD:.0f} | RSI ovr:{RSI_OVERBOUGHT}/os:{RSI_OVERSOLD} | Vol:{VOLUME_THRESHOLD}x | TSI_th:{TSI_THRESHOLD}")
    logger.info("=" * 60)
    state = load_state()
    state = reset_daily_state(state)
    CAPITAL = 100000
    if check_daily_loss_limit(state, CAPITAL):
        sys.exit(0)
    ohlcv = fetch_recent_data(SYMBOL, 90)
    if not ohlcv:
        sys.exit(1)
    atr = calculate_atr(ohlcv, ATR_PERIOD)
    tsi, signal_line = calculate_tsi(ohlcv, TSI_FAST, TSI_SLOW, TSI_SIGNAL)
    sma_vals = calculate_sma(ohlcv, SMA_PERIOD)
    ema_vals = calculate_ema(ohlcv, 20)
    rsi_vals = calculate_rsi(ohlcv, RSI_PERIOD)
    vol_ma = calculate_volume_ma(ohlcv, VOLUME_MA_PERIOD)
    adx_vals, plus_di, minus_di = calculate_adx(ohlcv, ADX_PERIOD)  # v3: trend strength filter
    current_price = ohlcv[-1]["close"]
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)
    signal, filter_reason = generate_signal(ohlcv, tsi, signal_line, sma_vals, ema_vals, rsi_vals, vol_ma, atr, adx_vals)
    current_sma = sma_vals[-1] if sma_vals and sma_vals[-1] else 0
    current_ema = ema_vals[-1] if ema_vals and ema_vals[-1] else 0
    current_rsi = rsi_vals[-1] if rsi_vals and rsi_vals[-1] else 50.0
    current_vol = ohlcv[-1]["volume"]
    avg_vol = vol_ma[-1] if vol_ma and vol_ma[-1] else current_vol
    logger.info(f"Price: ₹{current_price:.2f} | ATR: ₹{current_atr:.2f} | TSI: {tsi[-1]:.2f} | ADX: {adx_vals[-1]:.1f} | Signal: {signal} | Filter: {filter_reason}")
    logger.info(f"  SMA({SMA_PERIOD}): ₹{current_sma:.2f} | EMA(20): ₹{current_ema:.2f} | RSI({RSI_PERIOD}): {current_rsi:.1f} | Vol Ratio: {current_vol/avg_vol:.2f}x")
    if signal != "HOLD":
        result = execute_trade(signal, current_price, current_atr, state, CAPITAL)
        state["last_signal"] = signal
        if result["action"] != "NONE":
            logger.info(f"Trade executed: {result}")
    else:
        logger.info("HOLD signal - no trade")
    if state.get("position"):
        pos = state["position"]
        pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100
        logger.info(f"Position: Entry ₹{pos['entry_price']:.2f} | Curr ₹{current_price:.2f} | P&L: {pnl_pct:.2f}%")
    logger.info("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
