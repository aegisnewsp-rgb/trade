#!/usr/bin/env python3
"""
RISK CALCULATOR
===============
Dynamic position sizing based on:
- ATR (volatility) for stop loss calculation
- Kelly Criterion for optimal position sizing
- Portfolio-level risk management
- Correlation-based position reduction

⚠️ FOR EDUCATIONAL/PAPER TRADING USE ⚠️
"""

import os
import sys
import logging
import json
import math
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple
from pathlib import Path
from dataclasses import dataclass

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ============== CONFIGURATION ==============
CAPITAL = 100000  # ₹1,00,000 default capital
MAX_POSITIONS = 3  # Maximum concurrent positions
MAX_PORTFOLIO_RISK = 0.05  # Max 5% of portfolio at risk
DEFAULT_WIN_RATE = 0.60  # Default win rate if unknown
DEFAULT_REWARD_RISK = 2.0  # Default reward:risk ratio

# ATR Settings
ATR_PERIOD = 14
STOP_LOSS_ATR = 1.5  # Stop loss at 1.5x ATR
TARGET_ATR = 3.0  # Target at 3x ATR

# Kelly Criterion
KELLY_FRACTION = 0.25  # Use 25% of Kelly (conservative)

# Correlation threshold for position reduction
CORRELATION_THRESHOLD = 0.7

# Logging
LOG_DIR = Path("/home/node/workspace/trade-project/deploy/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class PositionSize:
    symbol: str
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    position_value: float
    risk_amount: float
    risk_pct: float
    kelly_pct: float
    final_size_multiplier: float
    reasoning: List[str]

@dataclass
class PortfolioRisk:
    total_capital: float
    available_capital: float
    positions: List[PositionSize]
    total_risk: float
    total_risk_pct: float
    correlated_positions: List[str]
    warnings: List[str]

def setup_logging():
    log_file = LOG_DIR / f"risk_calc_{date.today().isoformat()}.log"
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
def fetch_data(symbol: str, days: int = 90) -> Optional[List[Dict]]:
    """Fetch OHLCV data using yfinance."""
    if not YFINANCE_AVAILABLE:
        logger.error("yfinance not available")
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{days}d")
        
        if df.empty:
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

def fetch_returns(symbol: str, days: int = 252) -> List[float]:
    """Fetch daily returns for correlation calculation."""
    ohlcv = fetch_data(symbol, days)
    if not ohlcv or len(ohlcv) < 2:
        return []
    
    returns = []
    for i in range(1, len(ohlcv)):
        ret = (ohlcv[i]["close"] - ohlcv[i-1]["close"]) / ohlcv[i-1]["close"]
        returns.append(ret)
    
    return returns

# ============== TECHNICAL INDICATORS ==============
def calculate_atr(ohlcv: List[Dict], period: int = 14) -> float:
    """Calculate current ATR value."""
    if len(ohlcv) < period + 1:
        return ohlcv[-1]["close"] * 0.02  # Default 2% if insufficient data
    
    prev_close = None
    tr_list = []
    
    for i, bar in enumerate(ohlcv[-period-1:]):
        high = bar["high"]
        low = bar["low"]
        
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        
        tr_list.append(tr)
        prev_close = bar["close"]
    
    # Calculate ATR
    atr = sum(tr_list) / period
    return atr

def calculate_volatility(returns: List[float]) -> float:
    """Calculate volatility (standard deviation of returns)."""
    if len(returns) < 2:
        return 0.02  # Default 2% if insufficient data
    
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    volatility = math.sqrt(variance)
    
    return volatility

# ============== KELLY CRITERION ==============
def kelly_criterion(win_rate: float, reward_risk_ratio: float) -> float:
    """
    Calculate Kelly Criterion percentage for position sizing.
    
    Kelly % = W - (1-W)/R
    Where:
        W = Win rate (probability of winning)
        R = Reward/Risk ratio (average win / average loss)
    
    Returns Kelly percentage (0 to 1).
    """
    if reward_risk_ratio <= 0:
        return 0.0
    
    kelly = win_rate - ((1 - win_rate) / reward_risk_ratio)
    
    # Bound Kelly between 0 and 1
    kelly = max(0.0, min(1.0, kelly))
    
    return kelly

def kelly_adjusted_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    atr: float,
    win_rate: float,
    kelly_fraction: float = KELLY_FRACTION
) -> Tuple[int, float, List[str]]:
    """
    Calculate position size using Kelly Criterion.
    
    Returns: (quantity, kelly_pct, reasoning)
    """
    reasoning = []
    
    # Calculate risk per share
    risk_per_share = abs(entry_price - stop_loss)
    
    if risk_per_share == 0:
        reasoning.append("Risk per share is 0, cannot calculate Kelly size")
        return 1, 0.0, reasoning
    
    # Calculate reward/risk ratio based on ATR-based target
    target = entry_price + (atr * TARGET_ATR)
    reward_per_share = target - entry_price
    reward_risk_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 1.0
    
    reasoning.append(f"Reward/Risk ratio: {reward_risk_ratio:.2f}")
    
    # Calculate Kelly percentage
    kelly = kelly_criterion(win_rate, reward_risk_ratio)
    kelly_pct = kelly * kelly_fraction  # Apply fraction for conservatism
    
    reasoning.append(f"Kelly criterion: {kelly:.2%} (raw), {kelly_pct:.2%} (with {kelly_fraction:.0%} fraction)")
    
    # Calculate position size based on Kelly
    risk_amount = capital * kelly_pct
    quantity = int(risk_amount / risk_per_share)
    
    if quantity < 1:
        reasoning.append(f"Position size < 1 share, using minimum of 1")
        quantity = 1
    
    return quantity, kelly_pct, reasoning

# ============== ATR-BASED STOP/TARGET ==============
def calculate_stop_loss(entry_price: float, atr: float, atr_mult: float = STOP_LOSS_ATR) -> float:
    """Calculate ATR-based stop loss."""
    return entry_price - (atr * atr_mult)

def calculate_target(entry_price: float, atr: float, atr_mult: float = TARGET_ATR) -> float:
    """Calculate ATR-based target."""
    return entry_price + (atr * atr_mult)

# ============== CORRELATION ANALYSIS ==============
def calculate_correlation(returns1: List[float], returns2: List[float]) -> float:
    """Calculate Pearson correlation between two return series."""
    if len(returns1) < 10 or len(returns2) < 10:
        return 0.0
    
    # Trim to same length
    min_len = min(len(returns1), len(returns2))
    r1 = returns1[-min_len:]
    r2 = returns2[-min_len:]
    
    # Calculate means
    mean1 = sum(r1) / len(r1)
    mean2 = sum(r2) / len(r2)
    
    # Calculate correlation
    numerator = sum((a - mean1) * (b - mean2) for a, b in zip(r1, r2))
    denom1 = math.sqrt(sum((a - mean1) ** 2 for a in r1))
    denom2 = math.sqrt(sum((b - mean2) ** 2 for b in r2))
    
    if denom1 == 0 or denom2 == 0:
        return 0.0
    
    correlation = numerator / (denom1 * denom2)
    
    return max(-1.0, min(1.0, correlation))

def find_correlated_positions(
    new_symbol: str,
    existing_positions: List[Dict],
    threshold: float = CORRELATION_THRESHOLD
) -> List[str]:
    """Find existing positions that are highly correlated with new signal."""
    correlated = []
    
    new_returns = fetch_returns(new_symbol, 60)
    
    for pos in existing_positions:
        pos_symbol = pos["symbol"]
        pos_returns = fetch_returns(pos_symbol, 60)
        
        if not new_returns or not pos_returns:
            continue
        
        corr = calculate_correlation(new_returns, pos_returns)
        
        if abs(corr) >= threshold:
            correlated.append(pos_symbol)
            logger.info(f"[CORRELATION] {new_symbol} vs {pos_symbol}: {corr:.2%}")
    
    return correlated

# ============== POSITION SIZE CALCULATION ==============
def calculate_position_size(
    symbol: str,
    entry_price: float,
    atr: float,
    capital: float,
    win_rate: float,
    existing_positions: List[Dict],
    max_positions: int = MAX_POSITIONS,
    max_portfolio_risk: float = MAX_PORTFOLIO_RISK
) -> PositionSize:
    """
    Calculate optimal position size with all risk management rules.
    
    Rules:
    1. Max 3 positions at a time
    2. Max 5% portfolio at risk at any time
    3. Reduce size if correlated positions exist
    4. Apply Kelly Criterion for sizing
    """
    reasoning = []
    reasoning.append(f"Entry: ₹{entry_price:.2f} | ATR: ₹{atr:.2f} | Capital: ₹{capital:,.0f}")
    
    # Calculate stop loss and target
    stop_loss = calculate_stop_loss(entry_price, atr)
    target = calculate_target(entry_price, atr)
    risk_per_share = entry_price - stop_loss
    
    reasoning.append(f"Stop Loss: ₹{stop_loss:.2f} | Target: ₹{target:.2f}")
    reasoning.append(f"Risk per share: ₹{risk_per_share:.2f}")
    
    # Calculate Kelly-based quantity
    kelly_qty, kelly_pct, kelly_reasoning = kelly_adjusted_size(
        capital, entry_price, stop_loss, atr, win_rate
    )
    reasoning.extend(kelly_reasoning)
    
    # Check position count limit
    if len(existing_positions) >= max_positions:
        reasoning.append(f"⚠️ MAX POSITIONS ({max_positions}) REACHED - SKIP")
        return PositionSize(
            symbol=symbol,
            quantity=0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            position_value=0,
            risk_amount=0,
            risk_pct=0,
            kelly_pct=kelly_pct,
            final_size_multiplier=0,
            reasoning=reasoning
        )
    
    # Calculate correlation with existing positions
    correlated = find_correlated_positions(symbol, existing_positions)
    correlation_reduction = 1.0
    
    if correlated:
        correlation_reduction = 0.5  # Reduce by 50% for correlated positions
        reasoning.append(f"⚠️ CORRELATED with {correlated} - reducing size by 50%")
    
    # Calculate position value and risk
    raw_quantity = kelly_qty * correlation_reduction
    quantity = max(1, int(raw_quantity))  # At least 1 share
    
    position_value = quantity * entry_price
    risk_amount = quantity * risk_per_share
    risk_pct = risk_amount / capital
    
    # Check max portfolio risk
    current_risk = sum(p.get("risk_amount", 0) for p in existing_positions)
    total_potential_risk = current_risk + risk_amount
    max_allowed_risk = capital * max_portfolio_risk
    
    if total_potential_risk > max_allowed_risk:
        # Scale down to fit within risk limit
        available_risk = max(0, max_allowed_risk - current_risk)
        if available_risk > 0:
            quantity = max(1, int(available_risk / risk_per_share))
            position_value = quantity * entry_price
            risk_amount = quantity * risk_per_share
            risk_pct = risk_amount / capital
            reasoning.append(f"⚠️ Scaled to fit portfolio risk limit ({max_portfolio_risk:.0%})")
        else:
            reasoning.append(f"⚠️ NO RISK BUDGET AVAILABLE - SKIP")
            quantity = 0
    
    final_multiplier = quantity / kelly_qty if kelly_qty > 0 else 0
    
    reasoning.append(f"Final quantity: {quantity} shares (multiplier: {final_multiplier:.2f})")
    reasoning.append(f"Position value: ₹{position_value:,.2f}")
    reasoning.append(f"Risk: ₹{risk_amount:,.2f} ({risk_pct:.2%} of capital)")
    
    return PositionSize(
        symbol=symbol,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        position_value=position_value,
        risk_amount=risk_amount,
        risk_pct=risk_pct,
        kelly_pct=kelly_pct,
        final_size_multiplier=final_multiplier,
        reasoning=reasoning
    )

# ============== PORTFOLIO RISK MANAGEMENT ==============
def analyze_portfolio_risk(
    capital: float,
    positions: List[Dict],
    max_positions: int = MAX_POSITIONS,
    max_portfolio_risk: float = MAX_PORTFOLIO_RISK
) -> PortfolioRisk:
    """Analyze overall portfolio risk."""
    warnings = []
    
    # Calculate current risk
    total_risk = sum(p.get("risk_amount", 0) for p in positions)
    total_risk_pct = total_risk / capital if capital > 0 else 0
    available_capital = capital - sum(p.get("position_value", 0) for p in positions)
    
    # Check position count
    if len(positions) >= max_positions:
        warnings.append(f"⚠️ At max positions ({max_positions}/{max_positions})")
    
    # Check risk limit
    if total_risk_pct > max_portfolio_risk:
        warnings.append(f"⚠️ Portfolio risk exceeds limit ({total_risk_pct:.2%} > {max_portfolio_risk:.0%})")
    
    # Find correlated positions
    correlated_pairs = []
    for i, pos1 in enumerate(positions):
        for pos2 in positions[i+1:]:
            r1 = fetch_returns(pos1["symbol"], 60)
            r2 = fetch_returns(pos2["symbol"], 60)
            if r1 and r2:
                corr = calculate_correlation(r1, r2)
                if abs(corr) >= CORRELATION_THRESHOLD:
                    correlated_pairs.append(f"{pos1['symbol']}-{pos2['symbol']}")
    
    if correlated_pairs:
        warnings.append(f"⚠️ Correlated position pairs: {', '.join(correlated_pairs)}")
    
    return PortfolioRisk(
        total_capital=capital,
        available_capital=available_capital,
        positions=positions,
        total_risk=total_risk,
        total_risk_pct=total_risk_pct,
        correlated_positions=correlated_pairs,
        warnings=warnings
    )

def get_position_recommendations(
    signals: List[Dict],
    capital: float,
    existing_positions: List[Dict]
) -> List[Dict]:
    """
    Get position size recommendations for multiple signals.
    Handles ranking and allocation based on score/confidence.
    """
    logger.info("\n" + "=" * 70)
    logger.info("POSITION SIZE CALCULATIONS")
    logger.info("=" * 70)
    
    # Sort by confidence/score
    sorted_signals = sorted(signals, key=lambda x: x.get("confluence_score", 0), reverse=True)
    
    # Calculate ATR for each signal
    for sig in sorted_signals:
        ohlcv = fetch_data(sig["symbol"], 30)
        if ohlcv:
            sig["atr"] = calculate_atr(ohlcv)
            sig["entry_price"] = ohlcv[-1]["close"]
        else:
            sig["atr"] = 0
            sig["entry_price"] = 0
    
    recommendations = []
    remaining_capital = capital - sum(p.get("position_value", 0) for p in existing_positions)
    
    for sig in sorted_signals:
        if remaining_capital <= 0:
            break
        
        symbol = sig["symbol"]
        entry_price = sig["entry_price"]
        atr = sig["atr"]
        win_rate = sig.get("win_rate", DEFAULT_WIN_RATE)
        
        logger.info(f"\n[CALCULATING] {symbol}")
        
        pos_size = calculate_position_size(
            symbol=symbol,
            entry_price=entry_price,
            atr=atr,
            capital=remaining_capital,
            win_rate=win_rate,
            existing_positions=existing_positions + recommendations
        )
        
        recommendation = {
            "symbol": symbol,
            "signal": sig.get("raw_signal", "BUY"),
            "confluence_score": sig.get("confluence_score", 0),
            **vars(pos_size)
        }
        
        recommendations.append(recommendation)
        
        for r in pos_size.reasoning:
            logger.info(f"  {r}")
        
        remaining_capital -= pos_size.position_value
    
    return recommendations

# ============== MAIN EXECUTION ==============
def run_risk_analysis(signals: List[Dict]):
    """Run full risk analysis on provided signals."""
    logger.info("=" * 70)
    logger.info("RISK CALCULATOR")
    logger.info(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Capital: ₹{CAPITAL:,.0f}")
    logger.info("=" * 70)
    
    # Assume no existing positions for standalone run
    existing_positions = []
    
    recommendations = get_position_recommendations(signals, CAPITAL, existing_positions)
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("POSITION SIZE SUMMARY")
    logger.info("=" * 70)
    
    logger.info(f"\n{'Symbol':<15} {'Signal':<8} {'Qty':<6} {'Value':<12} {'Risk':<10} {'Score':<8}")
    logger.info("-" * 70)
    
    total_value = 0
    total_risk = 0
    
    for rec in recommendations:
        if rec["quantity"] > 0:
            logger.info(
                f"{rec['symbol']:<15} {rec['signal']:<8} {rec['quantity']:<6} "
                f"₹{rec['position_value']:>10,.0f} ₹{rec['risk_amount']:>8,.0f} {rec['confluence_score']:.0f}"
            )
            total_value += rec["position_value"]
            total_risk += rec["risk_amount"]
    
    logger.info("-" * 70)
    logger.info(f"TOTAL: {len([r for r in recommendations if r['quantity'] > 0])} positions")
    logger.info(f"Total Position Value: ₹{total_value:,.0f}")
    logger.info(f"Total Risk: ₹{total_risk:,.0f} ({total_risk/CAPITAL:.2%})")
    
    # Portfolio risk analysis
    portfolio = analyze_portfolio_risk(CAPITAL, recommendations)
    
    if portfolio.warnings:
        logger.info("\n⚠️ WARNINGS:")
        for w in portfolio.warnings:
            logger.info(f"  {w}")
    
    # Save to file
    output = {
        "date": date.today().isoformat(),
        "capital": CAPITAL,
        "recommendations": recommendations,
        "total_position_value": total_value,
        "total_risk": total_risk,
        "total_risk_pct": total_risk / CAPITAL if CAPITAL > 0 else 0,
        "warnings": portfolio.warnings
    }
    
    output_file = LOG_DIR / f"risk_analysis_{date.today().isoformat()}.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"\n[SAVE] Analysis saved to {output_file}")
    logger.info("=" * 70)
    
    return recommendations

# Example usage
def demo():
    """Demo with sample signals."""
    sample_signals = [
        {"symbol": "RELIANCE.NS", "raw_signal": "BUY", "win_rate": 0.6364, "confluence_score": 75},
        {"symbol": "TCS.NS", "raw_signal": "BUY", "win_rate": 0.6364, "confluence_score": 68},
        {"symbol": "HDFCBANK.NS", "raw_signal": "BUY", "win_rate": 0.6061, "confluence_score": 62},
        {"symbol": "SBIN.NS", "raw_signal": "SELL", "win_rate": 0.6364, "confluence_score": 55},
    ]
    
    run_risk_analysis(sample_signals)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Risk Calculator")
    parser.add_argument("--demo", action="store_true", help="Run demo with sample signals")
    args = parser.parse_args()
    
    if args.demo:
        demo()
    else:
        # Run with empty signals (for testing data fetching)
        logger.info("Risk Calculator initialized. Use with orchestrator output.")
        logger.info("Run with --demo to see sample calculations.")
