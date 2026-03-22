#!/usr/bin/env python3
"""
SIGNAL VERIFICATION TOOL
========================
Back-tests the enhanced orchestrator strategy against last 30 days of data.
Compares enhanced signals (with filters) vs raw signals (without filters).
Reports improvement in win rate.

Usage:
    python verify_signals.py                    # Full 30-day backtest
    python verify_signals.py --days 60          # Custom day range
    python verify_signals.py --symbol TCS.NS    # Single stock analysis

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
"""

import os
import sys
import logging
import json
import argparse
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
    "RELIANCE.NS": {"strategy": "TSI", "win_rate": 0.6364},
    "TCS.NS": {"strategy": "VWAP", "win_rate": 0.6364},
    "SBIN.NS": {"strategy": "VWAP", "win_rate": 0.6364},
    "TITAN.NS": {"strategy": "VWAP", "win_rate": 0.6111},
    "HDFCBANK.NS": {"strategy": "ADX_TREND", "win_rate": 0.6061},
}

NIFTY_SYMBOL = "^NSEI"
BACKTEST_DAYS = 30
VOLUME_MULTIPLIER = 1.5

# Logging
LOG_DIR = Path("/home/node/workspace/trade-project/deploy/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    signal: str
    pnl_pct: float
    enhanced_filtered: bool

@dataclass
class BacktestResult:
    symbol: str
    total_days: int
    raw_signals: int
    enhanced_signals: int
    raw_wins: int
    raw_losses: int
    raw_win_rate: float
    enhanced_wins: int
    enhanced_losses: int
    enhanced_win_rate: float
    improvement: float
    trades: List[Trade]

def setup_logging():
    log_file = LOG_DIR / f"verify_signals_{date.today().isoformat()}.log"
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
def fetch_data(symbol: str, days: int) -> Optional[List[Dict]]:
    """Fetch OHLCV data using yfinance."""
    if not YFINANCE_AVAILABLE:
        logger.error("yfinance not available")
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days + 30}d")  # Extra days for indicator warmup
        
        if df.empty:
            logger.error(f"No data returned for {symbol}")
            return None
        
        ohlcv = []
        for idx, row in df.iterrows():
            ohlcv.append({
                "date": idx.isoformat(),
                "date_str": idx.strftime("%Y-%m-%d"),
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
    """Calculate True Strength Index."""
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
        
        plus_dm = max(0, ohlcv[i]["high"] - ohlcv[i-1]["high"])
        minus_dm = max(0, ohlcv[i-1]["low"] - ohlcv[i]["low"])
        
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

# ============== SIGNAL GENERATION ==============
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

# ============== MARKET REGIME ==============
def detect_market_regime(nifty_ohlcv: List[Dict], period: int = 20) -> str:
    """Detect NIFTY market regime using 20-day SMA slope."""
    if len(nifty_ohlcv) < period + 1:
        return "RANGE"
    
    closes = [bar["close"] for bar in nifty_ohlcv]
    sma = calculate_sma(closes, period)
    
    if sma[-1] is None or sma[-(period)] is None:
        return "RANGE"
    
    sma_slope = (sma[-1] - sma[-period]) / sma[-period]
    trend_threshold = 0.02
    
    if sma_slope > trend_threshold:
        return "UPTREND"
    elif sma_slope < -trend_threshold:
        return "DOWNTREND"
    else:
        return "RANGE"

# ============== FILTERS ==============
def check_volume_filter(ohlcv: List[Dict], period: int = 20, multiplier: float = 1.5) -> bool:
    """Check if volume is above threshold."""
    if len(ohlcv) < period + 1:
        return False
    
    volumes = [bar["volume"] for bar in ohlcv[-period:]]
    avg_volume = sum(volumes) / len(volumes)
    current_volume = ohlcv[-1]["volume"]
    
    return current_volume >= avg_volume * multiplier

def should_filter_enhanced(raw_signal: str, regime: str, ohlcv: List[Dict]) -> Tuple[bool, str]:
    """
    Determine if signal should be filtered by enhanced checks.
    Returns (should_filter, reason)
    """
    if raw_signal == "HOLD":
        return True, "HOLD signal"
    
    # Market regime check
    if raw_signal == "BUY" and regime != "UPTREND":
        return True, f"BUY blocked - market not in UPTREND (current: {regime})"
    elif raw_signal == "SELL" and regime != "DOWNTREND":
        return True, f"SELL blocked - market not in DOWNTREND (current: {regime})"
    
    # Volume check
    if not check_volume_filter(ohlcv):
        return True, "Signal filtered - volume below threshold"
    
    return False, "Signal passes enhanced filters"

# ============== BACKTESTING ==============
def run_backtest(symbol: str, config: Dict, nifty_ohlcv: List[Dict], 
                 start_idx: int, end_idx: int, ohlcv: List[Dict]) -> BacktestResult:
    """Run backtest for a single symbol over a date range."""
    
    strategy = config["strategy"]
    regime = detect_market_regime(nifty_ohlcv)
    
    raw_trades: List[Trade] = []
    enhanced_trades: List[Trade] = []
    
    # Track positions
    raw_position = None
    enhanced_position = None
    
    for i in range(start_idx, end_idx):
        # Get historical data up to this point
        hist_data = ohlcv[:i+1]
        
        if len(hist_data) < 30:
            continue
        
        # Generate signals
        raw_signal = generate_raw_signal(symbol, hist_data, strategy)
        
        # Check enhanced filter
        should_filter, filter_reason = should_filter_enhanced(raw_signal, regime, hist_data)
        enhanced_signal = "HOLD" if should_filter else raw_signal
        
        current_bar = hist_data[-1]
        current_date = current_bar["date_str"]
        current_price = current_bar["close"]
        
        # RAW SIGNAL TRADING
        if raw_signal == "BUY" and raw_position is None:
            raw_position = {"entry_date": current_date, "entry_price": current_price, "signal": "BUY"}
        elif raw_signal == "SELL" and raw_position is not None:
            pnl_pct = ((current_price - raw_position["entry_price"]) / raw_position["entry_price"]) * 100
            trade = Trade(
                entry_date=raw_position["entry_date"],
                entry_price=raw_position["entry_price"],
                exit_date=current_date,
                exit_price=current_price,
                signal=raw_position["signal"],
                pnl_pct=pnl_pct,
                enhanced_filtered=False
            )
            raw_trades.append(trade)
            raw_position = None
        
        # ENHANCED SIGNAL TRADING
        if enhanced_signal == "BUY" and enhanced_position is None:
            enhanced_position = {"entry_date": current_date, "entry_price": current_price, "signal": "BUY"}
        elif enhanced_signal == "SELL" and enhanced_position is not None:
            pnl_pct = ((current_price - enhanced_position["entry_price"]) / enhanced_position["entry_price"]) * 100
            trade = Trade(
                entry_date=enhanced_position["entry_date"],
                entry_price=enhanced_position["entry_price"],
                exit_date=current_date,
                exit_price=current_price,
                signal=enhanced_position["signal"],
                pnl_pct=pnl_pct,
                enhanced_filtered=True
            )
            enhanced_trades.append(trade)
            enhanced_position = None
    
    # Close any open positions at end
    if raw_position is not None and end_idx > 0:
        final_price = ohlcv[end_idx-1]["close"]
        pnl_pct = ((final_price - raw_position["entry_price"]) / raw_position["entry_price"]) * 100
        trade = Trade(
            entry_date=raw_position["entry_date"],
            entry_price=raw_position["entry_price"],
            exit_date=ohlcv[end_idx-1]["date_str"],
            exit_price=final_price,
            signal=raw_position["signal"],
            pnl_pct=pnl_pct,
            enhanced_filtered=False
        )
        raw_trades.append(trade)
    
    if enhanced_position is not None and end_idx > 0:
        final_price = ohlcv[end_idx-1]["close"]
        pnl_pct = ((final_price - enhanced_position["entry_price"]) / enhanced_position["entry_price"]) * 100
        trade = Trade(
            entry_date=enhanced_position["entry_date"],
            entry_price=enhanced_position["entry_price"],
            exit_date=ohlcv[end_idx-1]["date_str"],
            exit_price=final_price,
            signal=enhanced_position["signal"],
            pnl_pct=pnl_pct,
            enhanced_filtered=True
        )
        enhanced_trades.append(trade)
    
    # Calculate win rates
    raw_wins = sum(1 for t in raw_trades if t.pnl_pct > 0)
    raw_losses = len(raw_trades) - raw_wins
    raw_win_rate = raw_wins / len(raw_trades) if len(raw_trades) > 0 else 0
    
    enhanced_wins = sum(1 for t in enhanced_trades if t.pnl_pct > 0)
    enhanced_losses = len(enhanced_trades) - enhanced_wins
    enhanced_win_rate = enhanced_wins / len(enhanced_trades) if len(enhanced_trades) > 0 else 0
    
    improvement = ((enhanced_win_rate - raw_win_rate) * 100) if len(raw_trades) > 0 else 0
    
    return BacktestResult(
        symbol=symbol,
        total_days=end_idx - start_idx,
        raw_signals=len(raw_trades),
        enhanced_signals=len(enhanced_trades),
        raw_wins=raw_wins,
        raw_losses=raw_losses,
        raw_win_rate=raw_win_rate,
        enhanced_wins=enhanced_wins,
        enhanced_losses=enhanced_losses,
        enhanced_win_rate=enhanced_win_rate,
        improvement=improvement,
        trades=enhanced_trades
    )

def run_full_backtest(days: int = 30):
    """Run full backtest across all stocks."""
    logger.info("=" * 70)
    logger.info(f"SIGNAL VERIFICATION - {days} DAY BACKTEST")
    logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    # Fetch NIFTY data first
    logger.info("\n[FETCH] Fetching NIFTY data...")
    nifty_ohlcv = fetch_data(NIFTY_SYMBOL, days + 30)
    
    if not nifty_ohlcv:
        logger.error("Failed to fetch NIFTY data")
        return
    
    total_days = len(nifty_ohlcv)
    start_idx = max(30, total_days - days)  # Warmup period + backtest window
    end_idx = total_days
    
    logger.info(f"[DATA] NIFTY data: {total_days} days loaded")
    logger.info(f"[BACKTEST] Period: {nifty_ohlcv[start_idx]['date_str']} to {nifty_ohlcv[-1]['date_str']}")
    
    all_results = []
    total_improvement = 0
    count_with_trades = 0
    
    for symbol, config in STOCKS_CONFIG.items():
        logger.info(f"\n[BACKTEST] Testing {symbol}...")
        
        ohlcv = fetch_data(symbol, days + 30)
        if not ohlcv or len(ohlcv) < 60:
            logger.warning(f"Insufficient data for {symbol}, skipping")
            continue
        
        result = run_backtest(symbol, config, nifty_ohlcv, start_idx, end_idx, ohlcv)
        all_results.append(result)
        
        if result.raw_signals > 0:
            count_with_trades += 1
            total_improvement += result.improvement
        
        logger.info(f"  Raw signals: {result.raw_signals} (Win rate: {result.raw_win_rate:.1%})")
        logger.info(f"  Enhanced signals: {result.enhanced_signals} (Win rate: {result.enhanced_win_rate:.1%})")
        logger.info(f"  Improvement: {result.improvement:+.1f}%")
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("BACKTEST SUMMARY")
    logger.info("=" * 70)
    
    logger.info(f"\n{'Symbol':<15} {'Raw WR':<10} {'Enh WR':<10} {'Improvement':<12} {'Raw#':<8} {'Enh#':<8}")
    logger.info("-" * 70)
    
    for r in all_results:
        raw_wr_str = f"{r.raw_win_rate:.1%}" if r.raw_signals > 0 else "N/A"
        enh_wr_str = f"{r.enhanced_win_rate:.1%}" if r.enhanced_signals > 0 else "N/A"
        imp_str = f"{r.improvement:+.1f}%" if r.raw_signals > 0 else "N/A"
        
        logger.info(f"{r.symbol:<15} {raw_wr_str:<10} {enh_wr_str:<10} {imp_str:<12} {r.raw_signals:<8} {r.enhanced_signals:<8}")
    
    avg_improvement = total_improvement / count_with_trades if count_with_trades > 0 else 0
    
    logger.info("-" * 70)
    logger.info(f"\nAVERAGE IMPROVEMENT: {avg_improvement:+.2f}%")
    logger.info(f"STOCKS WITH TRADES: {count_with_trades}/{len(all_results)}")
    
    # Detailed trades for best performer
    if all_results:
        best = max(all_results, key=lambda x: x.improvement)
        logger.info(f"\nBEST PERFORMER: {best.symbol} ({best.improvement:+.1f}% improvement)")
        
        if best.trades:
            logger.info("\nSample trades:")
            for t in best.trades[:5]:
                logger.info(f"  {t.entry_date} -> {t.exit_date}: {t.signal} @ {t.entry_price:.2f} -> {t.exit_price:.2f} ({t.pnl_pct:+.2f}%)")
    
    # Save results
    output_file = LOG_DIR / f"backtest_results_{date.today().isoformat()}.json"
    output_data = {
        "date": date.today().isoformat(),
        "backtest_days": days,
        "period": f"{nifty_ohlcv[start_idx]['date_str']} to {nifty_ohlcv[-1]['date_str']}",
        "results": [
            {
                "symbol": r.symbol,
                "raw_signals": r.raw_signals,
                "enhanced_signals": r.enhanced_signals,
                "raw_win_rate": r.raw_win_rate,
                "enhanced_win_rate": r.enhanced_win_rate,
                "improvement": r.improvement,
                "trades": [
                    {
                        "entry": t.entry_date,
                        "exit": t.exit_date,
                        "signal": t.signal,
                        "pnl_pct": t.pnl_pct
                    }
                    for t in r.trades
                ]
            }
            for r in all_results
        ],
        "average_improvement": avg_improvement
    }
    
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    logger.info(f"\n[SAVE] Results saved to {output_file}")
    logger.info("=" * 70)
    
    return all_results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal Verification Tool")
    parser.add_argument("--days", type=int, default=BACKTEST_DAYS, help=f"Number of days to backtest (default: {BACKTEST_DAYS})")
    parser.add_argument("--symbol", type=str, help="Single symbol to analyze")
    args = parser.parse_args()
    
    if args.symbol:
        logger.info(f"Single symbol analysis: {args.symbol}")
        # For single symbol, just run the full backtest
        # (could add single-symbol mode but for now run full)
    
    run_full_backtest(days=args.days)
