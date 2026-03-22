#!/usr/bin/env python3
"""
INTELLIGENT TRADING ORCHESTRATOR
================================
Meta-strategy that combines signals from 5 live stock scripts with advanced filtering:
- live_RELIANCE.py (TSI strategy, 63.64% win rate)
- live_TCS.py (VWAP strategy, 63.64% win rate)
- live_SBIN.py (VWAP strategy, 63.64% win rate)
- live_TITAN.py (VWAP strategy, 61.11% win rate)
- live_HDFCBANK.py (ADX_TREND strategy, 60.61% win rate)

Advanced Filters:
a) Market Regime Detection (NIFTY trend vs range)
b) Multi-Timeframe Confirmation (15min, 1hr, daily)
c) Volume Confirmation (1.5x 20-day avg)
d) Correlation Filter (cross-sector confirmation)
e) Confluence Scoring (0-100 based on multiple factors)

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
"""

import os
import sys
import logging
import json
import math
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from dataclasses import dataclass

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
STOCKS_CONFIG = {
    "RELIANCE.NS": {
        "strategy": "TSI",
        "win_rate": 0.6364,
        "script": "live_RELIANCE.py",
        "sector": "energy",
        "correlation_stocks": ["HDFCBANK.NS", "ICICIBANK.NS"],
    },
    "TCS.NS": {
        "strategy": "VWAP",
        "win_rate": 0.6364,
        "script": "live_TCS.py",
        "sector": "it",
        "correlation_stocks": ["HCLTECH.NS", "INFY.NS"],
    },
    "SBIN.NS": {
        "strategy": "VWAP",
        "win_rate": 0.6364,
        "script": "live_SBIN.py",
        "sector": "banking",
        "correlation_stocks": ["HDFCBANK.NS", "ICICIBANK.NS"],
    },
    "TITAN.NS": {
        "strategy": "VWAP",
        "win_rate": 0.6111,
        "script": "live_TITAN.py",
        "sector": "consumer",
        "correlation_stocks": ["RELIANCE.NS"],
    },
    "HDFCBANK.NS": {
        "strategy": "ADX_TREND",
        "win_rate": 0.6061,
        "script": "HDFCBANK_NS.py",
        "sector": "banking",
        "correlation_stocks": ["SBIN.NS", "ICICIBANK.NS"],
    },
}

NIFTY_SYMBOL = "^NSEI"
CAPITAL = 100000  # ₹1,00,000
VOLUME_MULTIPLIER = 1.5
VOLUME_PERIOD = 20
SCORE_THRESHOLD_EXECUTE = 65
SCORE_THRESHOLD_SKIP = 40

# Logging
LOG_DIR = Path("/home/node/workspace/trade-project/deploy/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class StockSignal:
    symbol: str
    raw_signal: str
    strategy: str
    win_rate: float
    price: float
    atr: float
    volume_ratio: float
    market_regime_ok: bool
    timeframe_confirmed: bool
    sector_confirmed: bool
    distance_to_support: float
    distance_to_resistance: float
    confluence_score: float
    recommendation: str
    reasoning: List[str]

def setup_logging():
    log_file = LOG_DIR / f"orchestrator_{date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============== DATA FETCHING ==============
def fetch_data(symbol: str, period: str = "3mo", interval: str = "1d") -> Optional[List[Dict]]:
    """Fetch OHLCV data using yfinance."""
    if not YFINANCE_AVAILABLE:
        logger.error("yfinance not available")
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            logger.error(f"No data returned for {symbol}")
            return None
        
        ohlcv = []
        for idx, row in df.iterrows():
            ohlcv.append({
                "date": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"])
            })
        
        return ohlcv
    except Exception as e:
        logger.error(f"Failed to fetch data for {symbol}: {e}")
        return None

def fetch_intraday_data(symbol: str, interval: str = "15m") -> Optional[List[Dict]]:
    """Fetch intraday OHLCV data."""
    return fetch_data(symbol, period="5d", interval=interval)

# ============== TECHNICAL INDICATORS ==============
def calculate_atr(ohlcv: List[Dict], period: int = 14) -> List[float]:
    """Calculate Average True Range."""
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

def calculate_sma(prices: List[float], period: int) -> List[float]:
    """Calculate Simple Moving Average."""
    sma = []
    for i in range(len(prices)):
        if i < period - 1:
            sma.append(None)
        else:
            sma.append(sum(prices[i-period+1:i+1]) / period)
    return sma

def calculate_vwap(ohlcv: List[Dict], period: int = 14) -> List[float]:
    """Calculate VWAP (Volume Weighted Average Price)."""
    vwap = []
    for i in range(len(ohlcv)):
        if i < period - 1:
            vwap.append(None)
        else:
            typical_prices = []
            volumes = []
            for j in range(i - period + 1, i + 1):
                tp = (ohlcv[j]["high"] + ohlcv[j]["low"] + ohlcv[j]["close"]) / 3
                typical_prices.append(tp)
                volumes.append(ohlcv[j]["volume"])
            
            tp_sum = sum(typical_prices)
            vol_sum = sum(volumes)
            vwap.append(tp_sum / vol_sum if vol_sum > 0 else 0)
    return vwap

def calculate_tsi(ohlcv: List[Dict], fast: int = 13, slow: int = 25, signal: int = 13) -> Tuple[List[float], List[float]]:
    """Calculate True Strength Index. Returns (tsi_values, signal_values)."""
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
    
    tsi_values = []
    abs_mom_ema1 = calc_ema([abs(m) for m in momentum], fast)
    abs_mom_ema2 = calc_ema(abs_mom_ema1, slow)
    
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

def calculate_adx(ohlcv: List[Dict], period: int = 14) -> Tuple[List[float], List[float], List[float]]:
    """Calculate ADX, +DI, -DI. Simplified version."""
    adx_values = []
    plus_di = []
    minus_di = []
    
    for i in range(len(ohlcv)):
        if i < period:
            adx_values.append(25.0)
            plus_di.append(25.0)
            minus_di.append(25.0)
            continue
        
        # Calculate directional movement
        plus_dm = max(0, ohlcv[i]["high"] - ohlcv[i-1]["high"])
        minus_dm = max(0, ohlcv[i-1]["low"] - ohlcv[i]["low"])
        
        # Simplified ADX calculation
        price_change = ohlcv[i]["close"] - ohlcv[i-period]["close"]
        volatility = sum(abs(ohlcv[j]["close"] - ohlcv[j-1]["close"]) for j in range(i-period+1, i+1))
        
        if volatility > 0:
            strength = abs(price_change) / volatility
            adx = min(100, strength * 50)
        else:
            adx = 25.0
        
        adx_values.append(adx)
        
        if price_change > 0:
            plus_di.append(min(100, adx))
            minus_di.append(max(0, 100 - adx))
        else:
            plus_di.append(max(0, 100 - adx))
            minus_di.append(min(100, adx))
    
    return adx_values, plus_di, minus_di

# ============== RAW SIGNAL GENERATION ==============
def generate_tsi_signal(ohlcv: List[Dict]) -> str:
    """Generate TSI-based signal."""
    if len(ohlcv) < 26:
        return "HOLD"
    
    tsi, signal_line = calculate_tsi(ohlcv)
    
    current_tsi = tsi[-1]
    prev_tsi = tsi[-2]
    current_signal = signal_line[-1]
    prev_signal = signal_line[-2]
    
    if prev_tsi <= prev_signal and current_tsi > current_signal:
        return "BUY"
    elif prev_tsi >= prev_signal and current_tsi < current_signal:
        return "SELL"
    
    return "HOLD"

def generate_vwap_signal(ohlcv: List[Dict], atr_mult: float = 1.5) -> str:
    """Generate VWAP-based signal."""
    if len(ohlcv) < 15:
        return "HOLD"
    
    vwap = calculate_vwap(ohlcv, 14)
    atr = calculate_atr(ohlcv, 14)
    
    current_price = ohlcv[-1]["close"]
    vwap_value = vwap[-1]
    atr_value = atr[-1]
    
    if vwap_value is None or atr_value is None or atr_value == 0:
        return "HOLD"
    
    if current_price > vwap_value + atr_value * atr_mult:
        return "BUY"
    elif current_price < vwap_value - atr_value * atr_mult:
        return "SELL"
    
    return "HOLD"

def generate_adx_signal(ohlcv: List[Dict], threshold: float = 25) -> str:
    """Generate ADX-based signal."""
    if len(ohlcv) < 30:
        return "HOLD"
    
    adx, plus_di, minus_di = calculate_adx(ohlcv, 14)
    
    current_adx = adx[-1]
    current_plus = plus_di[-1]
    current_minus = minus_di[-1]
    current_price = ohlcv[-1]["close"]
    prev_price = ohlcv[-2]["close"]
    
    if current_adx > threshold:
        if current_plus > current_minus and current_price > prev_price:
            return "BUY"
        elif current_minus > current_plus and current_price < prev_price:
            return "SELL"
    
    return "HOLD"

def generate_raw_signal(symbol: str, ohlcv: List[Dict], strategy: str) -> str:
    """Generate raw signal based on strategy."""
    if strategy == "TSI":
        return generate_tsi_signal(ohlcv)
    elif strategy == "VWAP":
        return generate_vwap_signal(ohlcv)
    elif strategy == "ADX_TREND":
        return generate_adx_signal(ohlcv)
    else:
        return "HOLD"

# ============== ADVANCED FILTERS ==============
def detect_market_regime(nifty_ohlcv: List[Dict], period: int = 20) -> str:
    """
    Detect NIFTY market regime using 20-day SMA slope.
    Returns: 'UPTREND', 'DOWNTREND', or 'RANGE'
    """
    if len(nifty_ohlcv) < period + 1:
        return "RANGE"
    
    closes = [bar["close"] for bar in nifty_ohlcv]
    sma = calculate_sma(closes, period)
    
    if sma[-1] is None or sma[-(period)] is None:
        return "RANGE"
    
    # Calculate SMA slope
    sma_slope = (sma[-1] - sma[-period]) / sma[-period]
    
    # Threshold for trend detection (2% slope per day scaled to period)
    trend_threshold = 0.02
    
    if sma_slope > trend_threshold:
        return "UPTREND"
    elif sma_slope < -trend_threshold:
        return "DOWNTREND"
    else:
        return "RANGE"

def check_market_regime_filter(regime: str, signal: str) -> Tuple[bool, str]:
    """Check if signal is allowed based on market regime."""
    if signal == "BUY":
        if regime == "UPTREND":
            return True, "Market in UPTREND - BUY allowed"
        else:
            return False, f"Market not in UPTREND (current: {regime}) - BUY blocked"
    
    elif signal == "SELL":
        if regime == "DOWNTREND":
            return True, "Market in DOWNTREND - SELL allowed"
        else:
            return False, f"Market not in DOWNTREND (current: {regime}) - SELL blocked"
    
    return True, "HOLD signal - no regime check needed"

def check_multi_timeframe_confirmation(symbol: str, daily_ohlcv: List[Dict]) -> Tuple[bool, List[str]]:
    """
    Check 15min, 1hr, and daily timeframes for direction confirmation.
    Returns (confirmed, reasoning_list)
    """
    reasoning = []
    confirmations = 0
    
    # Daily timeframe
    if len(daily_ohlcv) >= 26:
        daily_signal = generate_raw_signal(symbol, daily_ohlcv, "TSI")
        reasoning.append(f"Daily: {daily_signal}")
        if daily_signal != "HOLD":
            confirmations += 1
    
    # 1hr timeframe
    intraday_1h = fetch_intraday_data(symbol, "1h")
    if intraday_1h and len(intraday_1h) >= 26:
        hourly_signal = generate_raw_signal(symbol, intraday_1h[-50:], "TSI")
        reasoning.append(f"1HR: {hourly_signal}")
        if hourly_signal != "HOLD":
            confirmations += 1
    
    # 15min timeframe
    intraday_15m = fetch_intraday_data(symbol, "15m")
    if intraday_15m and len(intraday_15m) >= 26:
        fifteen_signal = generate_raw_signal(symbol, intraday_15m[-50:], "TSI")
        reasoning.append(f"15MIN: {fifteen_signal}")
        if fifteen_signal != "HOLD":
            confirmations += 1
    
    # All 3 timeframes = full confirmation, 2 = partial
    confirmed = confirmations >= 2
    reasoning.append(f"Timeframe confirmations: {confirmations}/3")
    
    return confirmed, reasoning

def check_volume_confirmation(ohlcv: List[Dict], period: int = 20, multiplier: float = 1.5) -> Tuple[bool, float, str]:
    """
    Check if volume is > 1.5x 20-day average.
    Returns (confirmed, volume_ratio, reasoning)
    """
    if len(ohlcv) < period + 1:
        return False, 0.0, "Insufficient volume data"
    
    volumes = [bar["volume"] for bar in ohlcv[-period:]]
    avg_volume = sum(volumes) / len(volumes)
    current_volume = ohlcv[-1]["volume"]
    
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
    
    confirmed = volume_ratio >= multiplier
    reasoning = f"Volume ratio: {volume_ratio:.2f}x avg (need {multiplier}x)"
    
    return confirmed, volume_ratio, reasoning

def check_sector_correlation(symbol: str, raw_signal: str, correlation_stocks: List[str]) -> Tuple[bool, str]:
    """
    Check if correlated stocks in the same sector show the same signal.
    Returns (confirmed, reasoning)
    """
    if raw_signal == "HOLD" or not correlation_stocks:
        return True, "No correlation check needed"
    
    confirmations = 0
    total = 0
    
    for corr_symbol in correlation_stocks:
        corr_data = fetch_data(corr_symbol, period="5d")
        if corr_data and len(corr_data) >= 15:
            # Use simple VWAP for correlation check
            corr_signal = generate_vwap_signal(corr_data)
            if corr_signal == raw_signal:
                confirmations += 1
            total += 1
    
    if total == 0:
        return True, "No correlation data available"
    
    confirmed = confirmations >= 1  # At least 1 correlated stock agrees
    reasoning = f"Sector correlation: {confirmations}/{total} correlated stocks agree"
    
    return confirmed, reasoning

def calculate_support_resistance(ohlcv: List[Dict], lookback: int = 20) -> Tuple[float, float]:
    """Calculate nearest support and resistance levels."""
    if len(ohlcv) < lookback:
        return 0.0, 0.0
    
    recent = ohlcv[-lookback:]
    lows = [bar["low"] for bar in recent]
    highs = [bar["high"] for bar in recent]
    
    # Simple support/resistance: recent low/high
    support = min(lows)
    resistance = max(highs)
    
    return support, resistance

def calculate_distance_to_levels(ohlcv: List[Dict]) -> Tuple[float, float]:
    """
    Calculate distance to support and resistance as percentage.
    Returns (distance_to_support_pct, distance_to_resistance_pct)
    """
    if len(ohlcv) < 2:
        return 0.0, 0.0
    
    current_price = ohlcv[-1]["close"]
    support, resistance = calculate_support_resistance(ohlcv)
    
    if support > 0:
        dist_support = ((current_price - support) / current_price) * 100
    else:
        dist_support = 0.0
    
    if resistance > 0:
        dist_resistance = ((resistance - current_price) / current_price) * 100
    else:
        dist_resistance = 0.0
    
    return dist_support, dist_resistance

# ============== CONFLUENCE SCORING ==============
def calculate_confluence_score(
    stock_config: Dict,
    raw_signal: str,
    market_regime_ok: bool,
    timeframe_confirmed: bool,
    volume_confirmed: bool,
    volume_ratio: float,
    sector_confirmed: bool,
    dist_support: float,
    dist_resistance: float
) -> Tuple[float, List[str]]:
    """
    Calculate confluence score (0-100) for a signal.
    
    Scoring breakdown:
    - Win rate: up to 30 points
    - Confirmations (volume, timeframe, regime): up to 40 points
    - Sector correlation: up to 20 points
    - Distance to support/resistance: up to 10 points
    """
    if raw_signal == "HOLD":
        return 0.0, ["HOLD signal - no score calculated"]
    
    score = 0.0
    reasoning = []
    
    # 1. Win rate contribution (up to 30 points)
    win_rate = stock_config.get("win_rate", 0.5)
    win_rate_score = win_rate * 30
    score += win_rate_score
    reasoning.append(f"Win rate: {win_rate:.2%} x 30 = {win_rate_score:.1f} pts")
    
    # 2. Confirmations (up to 40 points)
    confirmation_score = 0
    
    # Market regime (15 points)
    if market_regime_ok:
        confirmation_score += 15
        reasoning.append("Market regime: +15 pts")
    else:
        reasoning.append("Market regime: BLOCKED")
    
    # Timeframe confirmation (15 points)
    if timeframe_confirmed:
        confirmation_score += 15
        reasoning.append("Multi-timeframe: +15 pts")
    else:
        reasoning.append("Multi-timeframe: weak confirmation")
    
    # Volume confirmation (10 points)
    if volume_confirmed:
        confirmation_score += 10
        reasoning.append(f"Volume confirmed ({volume_ratio:.2f}x): +10 pts")
    else:
        reasoning.append(f"Volume weak ({volume_ratio:.2f}x): +0 pts")
    
    score += confirmation_score
    
    # 3. Sector correlation (up to 20 points)
    if sector_confirmed:
        sector_score = 20
        score += sector_score
        reasoning.append("Sector correlation confirmed: +20 pts")
    else:
        reasoning.append("Sector correlation: weak, +5 pts")
        score += 5
    
    # 4. Support/Resistance distance (up to 10 points)
    if raw_signal == "BUY":
        # For BUY: closer to support is better
        if dist_support < 2.0:
            sr_score = 10
        elif dist_support < 4.0:
            sr_score = 7
        elif dist_support < 6.0:
            sr_score = 4
        else:
            sr_score = 2
        reasoning.append(f"BUY near support ({dist_support:.1f}%): +{sr_score} pts")
    else:  # SELL
        # For SELL: closer to resistance is better
        if dist_resistance < 2.0:
            sr_score = 10
        elif dist_resistance < 4.0:
            sr_score = 7
        elif dist_resistance < 6.0:
            sr_score = 4
        else:
            sr_score = 2
        reasoning.append(f"SELL near resistance ({dist_resistance:.1f}%): +{sr_score} pts")
    
    score += sr_score
    
    return score, reasoning

# ============== MAIN ORCHESTRATOR ==============
def analyze_stock(symbol: str, config: Dict, nifty_ohlcv: List[Dict], market_regime: str) -> Optional[StockSignal]:
    """Analyze a single stock and return enhanced signal."""
    reasoning = []
    
    # Fetch data
    ohlcv = fetch_data(symbol, period="3mo")
    if not ohlcv:
        logger.warning(f"No data for {symbol}")
        return None
    
    current_price = ohlcv[-1]["close"]
    atr = calculate_atr(ohlcv, 14)
    current_atr = atr[-1] if atr[-1] else (current_price * 0.02)
    
    # 1. Generate raw signal
    strategy = config["strategy"]
    raw_signal = generate_raw_signal(symbol, ohlcv, strategy)
    reasoning.append(f"Raw {strategy} signal: {raw_signal}")
    
    if raw_signal == "HOLD":
        return StockSignal(
            symbol=symbol,
            raw_signal=raw_signal,
            strategy=strategy,
            win_rate=config["win_rate"],
            price=current_price,
            atr=current_atr,
            volume_ratio=0.0,
            market_regime_ok=True,
            timeframe_confirmed=False,
            sector_confirmed=True,
            distance_to_support=0.0,
            distance_to_resistance=0.0,
            confluence_score=0.0,
            recommendation="SKIP",
            reasoning=["HOLD signal - no action"]
        )
    
    # 2. Market regime filter
    regime_ok, regime_reason = check_market_regime_filter(market_regime, raw_signal)
    reasoning.append(regime_reason)
    
    # 3. Multi-timeframe confirmation
    tf_confirmed, tf_reasoning = check_multi_timeframe_confirmation(symbol, ohlcv)
    reasoning.extend(tf_reasoning)
    
    # 4. Volume confirmation
    vol_confirmed, vol_ratio, vol_reason = check_volume_confirmation(ohlcv)
    reasoning.append(vol_reason)
    
    # 5. Sector correlation
    sector_confirmed, sector_reason = check_sector_correlation(
        symbol, raw_signal, config.get("correlation_stocks", [])
    )
    reasoning.append(sector_reason)
    
    # 6. Support/Resistance distance
    dist_support, dist_resistance = calculate_distance_to_levels(ohlcv)
    reasoning.append(f"Dist to support: {dist_support:.1f}%, Dist to resistance: {dist_resistance:.1f}%")
    
    # 7. Calculate confluence score
    score, score_reasoning = calculate_confluence_score(
        config, raw_signal, regime_ok, tf_confirmed, vol_confirmed,
        vol_ratio, sector_confirmed, dist_support, dist_resistance
    )
    reasoning.extend(score_reasoning)
    
    # 8. Determine recommendation
    if not regime_ok:
        recommendation = "SKIP"
    elif score >= SCORE_THRESHOLD_EXECUTE:
        recommendation = "EXECUTE"
    elif score < SCORE_THRESHOLD_SKIP:
        recommendation = "SKIP"
    else:
        recommendation = "WATCH"
    
    return StockSignal(
        symbol=symbol,
        raw_signal=raw_signal,
        strategy=strategy,
        win_rate=config["win_rate"],
        price=current_price,
        atr=current_atr,
        volume_ratio=vol_ratio,
        market_regime_ok=regime_ok,
        timeframe_confirmed=tf_confirmed,
        sector_confirmed=sector_confirmed,
        distance_to_support=dist_support,
        distance_to_resistance=dist_resistance,
        confluence_score=score,
        recommendation=recommendation,
        reasoning=reasoning
    )

def run_orchestrator():
    """Main orchestrator execution."""
    logger.info("=" * 70)
    logger.info("INTELLIGENT TRADING ORCHESTRATOR")
    logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    # 1. Fetch NIFTY data for market regime
    logger.info("\n[FETCH] NIFTY data for market regime detection...")
    nifty_ohlcv = fetch_data(NIFTY_SYMBOL, period="2mo")
    
    if not nifty_ohlcv:
        logger.error("Failed to fetch NIFTY data")
        return
    
    market_regime = detect_market_regime(nifty_ohlcv)
    logger.info(f"[REGIME] Current NIFTY regime: {market_regime}")
    
    # 2. Analyze each stock
    logger.info("\n[ANALYZE] Analyzing all stocks...")
    signals: List[StockSignal] = []
    
    for symbol, config in STOCKS_CONFIG.items():
        logger.info(f"\n--- Analyzing {symbol} ---")
        signal = analyze_stock(symbol, config, nifty_ohlcv, market_regime)
        if signal:
            signals.append(signal)
            logger.info(f"[{symbol}] Raw: {signal.raw_signal} | Score: {signal.confluence_score:.1f} | Rec: {signal.recommendation}")
    
    # 3. Sort by confluence score
    signals.sort(key=lambda x: x.confluence_score, reverse=True)
    
    # 4. Generate daily trading plan
    logger.info("\n" + "=" * 70)
    logger.info("DAILY TRADING PLAN")
    logger.info("=" * 70)
    
    logger.info(f"\nMarket Regime: {market_regime}")
    logger.info(f"Total Stocks Analyzed: {len(signals)}")
    
    execute_signals = [s for s in signals if s.recommendation == "EXECUTE"]
    watch_signals = [s for s in signals if s.recommendation == "WATCH"]
    
    logger.info(f"\nEXECUTE ({len(execute_signals)}):")
    for s in execute_signals:
        logger.info(f"  {s.symbol}: {s.raw_signal} @ ₹{s.price:.2f} (Score: {s.confluence_score:.0f})")
        logger.info(f"    ATR: ₹{s.atr:.2f} | Vol Ratio: {s.volume_ratio:.2f}x")
    
    logger.info(f"\nWATCH ({len(watch_signals)}):")
    for s in watch_signals:
        logger.info(f"  {s.symbol}: {s.raw_signal} @ ₹{s.price:.2f} (Score: {s.confluence_score:.0f})")
    
    # 5. Detailed signal report
    logger.info("\n" + "=" * 70)
    logger.info("RANKED SIGNAL RECOMMENDATIONS")
    logger.info("=" * 70)
    
    for rank, s in enumerate(signals, 1):
        logger.info(f"\n#{rank} {s.symbol}")
        logger.info(f"    Strategy: {s.strategy} | Raw Signal: {s.raw_signal}")
        logger.info(f"    Price: ₹{s.price:.2f} | ATR: ₹{s.atr:.2f}")
        logger.info(f"    Confluence Score: {s.confluence_score:.0f}/100")
        logger.info(f"    Recommendation: {s.recommendation}")
        logger.info(f"    Reasoning:")
        for r in s.reasoning:
            logger.info(f"      - {r}")
    
    # 6. Save daily plan to file
    daily_plan = {
        "date": date.today().isoformat(),
        "market_regime": market_regime,
        "nifty_price": nifty_ohlcv[-1]["close"] if nifty_ohlcv else None,
        "signals": [
            {
                "symbol": s.symbol,
                "raw_signal": s.raw_signal,
                "strategy": s.strategy,
                "price": s.price,
                "atr": s.atr,
                "volume_ratio": s.volume_ratio,
                "confluence_score": s.confluence_score,
                "recommendation": s.recommendation,
                "reasoning": s.reasoning
            }
            for s in signals
        ],
        "execute_count": len(execute_signals),
        "watch_count": len(watch_signals)
    }
    
    plan_file = LOG_DIR / f"daily_plan_{date.today().isoformat()}.json"
    with open(plan_file, 'w') as f:
        json.dump(daily_plan, f, indent=2)
    
    logger.info(f"\n[SAVE] Daily plan saved to {plan_file}")
    logger.info("=" * 70)
    
    return daily_plan

# ============== STANDALONE SIGNAL CHECK ==============
def check_signals():
    """Quick signal check without full analysis (for real-time use)."""
    logger.info("\n[QUICK CHECK] Fetching NIFTY regime...")
    nifty_ohlcv = fetch_data(NIFTY_SYMBOL, period="2mo")
    
    if not nifty_ohlcv:
        logger.error("Failed to fetch NIFTY data")
        return []
    
    market_regime = detect_market_regime(nifty_ohlcv)
    
    results = []
    for symbol, config in STOCKS_CONFIG.items():
        ohlcv = fetch_data(symbol, period="3mo")
        if not ohlcv:
            continue
        
        raw_signal = generate_raw_signal(symbol, ohlcv, config["strategy"])
        regime_ok, _ = check_market_regime_filter(market_regime, raw_signal)
        
        results.append({
            "symbol": symbol,
            "raw_signal": raw_signal,
            "regime_ok": regime_ok,
            "price": ohlcv[-1]["close"]
        })
    
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Intelligent Trading Orchestrator")
    parser.add_argument("--quick", action="store_true", help="Quick signal check only")
    args = parser.parse_args()
    
    if args.quick:
        results = check_signals()
        print("\nQuick Signal Check:")
        for r in results:
            print(f"  {r['symbol']}: {r['raw_signal']} (Regime OK: {r['regime_ok']}) @ ₹{r['price']:.2f}")
    else:
        run_orchestrator()
