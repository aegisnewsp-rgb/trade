#!/usr/bin/env python3
"""
MASTER SCANNER - Intelligent Multi-Strategy Stock Scanner
=========================================================
Scans ALL stocks in the manifest and uses multiple confirmation
filters before signaling BUY/SELL. Combines win_rate + volume +
trend strength into a confidence score.

BUY signal: confidence > 0.65
SELL signal: confidence < 0.40
HOLD: 0.40 <= confidence <= 0.65

Usage:
    python master_scanner.py [--top N] [--min-confidence 0.65]
"""

import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import math

# Configuration
MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'manifest.json')
BUY_THRESHOLD = 0.65
SELL_THRESHOLD = 0.40
TOP_N = 5

# Weights for confidence score
WIN_RATE_WEIGHT = 0.40
VOLUME_WEIGHT = 0.30
TREND_WEIGHT = 0.30


def load_manifest() -> dict:
    """Load the trading manifest."""
    with open(MANIFEST_PATH, 'r') as f:
        return json.load(f)


def calculate_volume_ratio(volumes: List[int], current_vol: int, period: int = 20) -> float:
    """Calculate volume ratio vs 20-day moving average."""
    if len(volumes) < period:
        return 1.0
    avg_vol = sum(volumes[-period:]) / period
    if avg_vol == 0:
        return 1.0
    return min(current_vol / avg_vol, 3.0)  # Cap at 3x


def calculate_trend_strength(closes: List[float], period: int = 50) -> float:
    """Calculate trend strength using linear regression slope normalized."""
    if len(closes) < period:
        return 0.5
    
    recent = closes[-period:]
    n = len(recent)
    
    # Linear regression
    x_mean = (n - 1) / 2
    y_mean = sum(recent) / n
    
    numerator = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return 0.5
    
    slope = numerator / denominator
    
    # Normalize slope to 0-1 range (assume max 5% per day is very strong)
    max_slope = y_mean * 0.05
    normalized = (slope / max_slope + 1) / 2
    
    return max(0.0, min(1.0, normalized))


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Calculate RSI indicator."""
    if len(closes) < period + 1:
        return 50.0
    
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_volatility(closes: List[float], period: int = 20) -> float:
    """Calculate normalized volatility (coefficient of variation)."""
    if len(closes) < period:
        return 0.5
    
    recent = closes[-period:]
    mean = sum(recent) / len(recent)
    if mean == 0:
        return 0.5
    
    variance = sum((x - mean) ** 2 for x in recent) / len(recent)
    std_dev = math.sqrt(variance)
    
    # Coefficient of variation - higher means more volatile
    cv = std_dev / mean
    
    # Normalize to 0-1 (typical range 0.01 to 0.1)
    normalized = (cv - 0.01) / 0.09
    return max(0.0, min(1.0, normalized))


def calculate_confidence_score(
    win_rate: Optional[float],
    volume_ratio: float,
    trend_strength: float,
    rsi: float,
    volatility: float,
    is_benchmark: bool
) -> float:
    """
    Calculate overall confidence score (0-1).
    
    Components:
    - win_rate (40%): Historical win rate from benchmark
    - volume_ratio (30%): Current volume vs 20-day MA
    - trend_strength (30%): 50-day trend strength
    
    Adjustments:
    - RSI > 70 or < 30 reduces confidence (momentum extremes)
    - Very low volatility reduces confidence (choppy market)
    - Non-benchmark stocks get 10% penalty
    """
    # Base score from components
    if win_rate is not None:
        base_score = (
            WIN_RATE_WEIGHT * win_rate +
            VOLUME_WEIGHT * min(volume_ratio / 2, 1.0) +  # Cap at 2x MA
            TREND_WEIGHT * trend_strength
        )
    else:
        # No benchmark data - rely on technicals only
        base_score = (
            0.5 * min(volume_ratio / 2, 1.0) +
            0.5 * trend_strength
        )
    
    # RSI adjustment (overbought/oversold reduces confidence)
    if rsi > 75 or rsi < 25:
        rsi_adj = 0.85
    elif rsi > 70 or rsi < 30:
        rsi_adj = 0.92
    else:
        rsi_adj = 1.0
    
    # Volatility adjustment (very low volatility = choppy = lower confidence)
    if volatility < 0.1:
        vol_adj = 0.85
    elif volatility < 0.2:
        vol_adj = 0.95
    else:
        vol_adj = 1.0
    
    # Benchmark verification adjustment
    benchmark_adj = 1.0 if is_benchmark else 0.90
    
    # Final confidence
    confidence = base_score * rsi_adj * vol_adj * benchmark_adj
    
    return round(min(max(confidence, 0.0), 1.0), 4)


def get_indicators_for_stock(symbol: str, script_path: str) -> Dict:
    """
    Fetch indicators for a stock using yfinance.
    Returns volume_ratio, trend_strength, rsi, volatility.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="3mo")
        
        if df.empty or len(df) < 30:
            return {
                "volume_ratio": 1.0,
                "trend_strength": 0.5,
                "rsi": 50.0,
                "volatility": 0.5,
                "data_quality": "insufficient"
            }
        
        closes = df["Close"].tolist()
        volumes = df["Volume"].tolist()
        current_vol = volumes[-1] if volumes else 0
        
        return {
            "volume_ratio": calculate_volume_ratio(volumes, current_vol),
            "trend_strength": calculate_trend_strength(closes),
            "rsi": calculate_rsi(closes),
            "volatility": calculate_volatility(closes),
            "data_quality": "good",
            "last_price": closes[-1] if closes else 0,
            "data_points": len(df)
        }
    except Exception as e:
        return {
            "volume_ratio": 1.0,
            "trend_strength": 0.5,
            "rsi": 50.0,
            "volatility": 0.5,
            "data_quality": f"error: {str(e)[:50]}"
        }


def scan_all_stocks(manifest: dict, top_n: int = 5, min_confidence: float = 0.0) -> List[Dict]:
    """
    Scan all stocks in the manifest and return ranked recommendations.
    """
    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    for stock in manifest.get("scripts", []):
        symbol = stock["symbol"]
        strategy = stock["strategy"]
        win_rate = stock.get("win_rate")
        is_benchmark = stock.get("source") == "benchmark"
        script = stock.get("script", "unknown")
        
        # Get technical indicators
        indicators = get_indicators_for_stock(symbol, script)
        
        # Calculate confidence score
        confidence = calculate_confidence_score(
            win_rate=win_rate,
            volume_ratio=indicators["volume_ratio"],
            trend_strength=indicators["trend_strength"],
            rsi=indicators["rsi"],
            volatility=indicators["volatility"],
            is_benchmark=is_benchmark
        )
        
        # Determine signal
        if confidence > BUY_THRESHOLD:
            signal = "BUY"
        elif confidence < SELL_THRESHOLD:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        result = {
            "timestamp": timestamp,
            "symbol": symbol,
            "strategy": strategy,
            "win_rate": win_rate,
            "benchmark_verified": is_benchmark,
            "confidence_score": confidence,
            "signal": signal,
            "indicators": {
                "volume_ratio": round(indicators["volume_ratio"], 2),
                "trend_strength": round(indicators["trend_strength"], 2),
                "rsi": round(indicators["rsi"], 1),
                "volatility": round(indicators["volatility"], 2)
            },
            "last_price": indicators.get("last_price", 0),
            "data_quality": indicators.get("data_quality", "unknown")
        }
        
        results.append(result)
        
        # Log the scan
        log_entry = (
            f"[{timestamp}] SCAN: {symbol} | Strategy: {strategy} | "
            f"Win Rate: {win_rate or 'N/A'} | Conf: {confidence:.4f} | "
            f"Signal: {signal} | Vol Ratio: {indicators['volume_ratio']:.2f} | "
            f"Trend: {indicators['trend_strength']:.2f} | RSI: {indicators['rsi']:.1f}"
        )
        print(log_entry)
    
    # Sort by confidence score (descending)
    results.sort(key=lambda x: x["confidence_score"], reverse=True)
    
    return results


def print_top_recommendations(results: List[Dict], top_n: int = 5):
    """Print top N recommendations."""
    print("\n" + "=" * 80)
    print(f"TOP {top_n} STOCK RECOMMENDATIONS")
    print("=" * 80)
    print(f"{'Rank':<5} {'Symbol':<18} {'Strategy':<20} {'Win Rate':<10} {'Confidence':<12} {'Signal':<6} {'RSI':<6}")
    print("-" * 80)
    
    for i, r in enumerate(results[:top_n], 1):
        win_display = f"{r['win_rate']*100:.1f}%" if r['win_rate'] else "N/A"
        rsi = r['indicators']['rsi']
        print(f"{i:<5} {r['symbol']:<18} {r['strategy']:<20} {win_display:<10} {r['confidence_score']:<12.4f} {r['signal']:<6} {rsi:<6.1f}")
    
    print("-" * 80)
    print(f"\nSIGNAL THRESHOLDS: BUY > {BUY_THRESHOLD} | SELL < {SELL_THRESHOLD}")
    print("=" * 80)


def print_summary(results: List[Dict]):
    """Print scan summary."""
    total = len(results)
    buy_signals = sum(1 for r in results if r['signal'] == 'BUY')
    sell_signals = sum(1 for r in results if r['signal'] == 'SELL')
    hold_signals = sum(1 for r in results if r['signal'] == 'HOLD')
    benchmark_count = sum(1 for r in results if r['benchmark_verified'])
    
    print("\n" + "=" * 80)
    print("SCAN SUMMARY")
    print("=" * 80)
    print(f"Total stocks scanned: {total}")
    print(f"Benchmark verified: {benchmark_count}")
    print(f"BUY signals (> {BUY_THRESHOLD}): {buy_signals}")
    print(f"SELL signals (< {SELL_THRESHOLD}): {sell_signals}")
    print(f"HOLD signals: {hold_signals}")
    print("=" * 80)


def save_results(results: List[Dict], output_path: str = None):
    """Save scan results to JSON file."""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(os.path.dirname(__file__), f"scan_results_{timestamp}.json")
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")


def main():
    """Main execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Master Scanner - Intelligent Stock Scanner")
    parser.add_argument("--top", type=int, default=TOP_N, help=f"Number of top recommendations (default: {TOP_N})")
    parser.add_argument("--min-confidence", type=float, default=BUY_THRESHOLD, help=f"Minimum confidence for BUY (default: {BUY_THRESHOLD})")
    parser.add_argument("--save", action="store_true", help="Save results to JSON")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("MASTER SCANNER - Intelligent Multi-Strategy Scanner")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    
    # Load manifest
    print(f"\nLoading manifest from: {MANIFEST_PATH}")
    manifest = load_manifest()
    print(f"Total stocks in manifest: {manifest.get('total_stocks', 0)}")
    print(f"Benchmark verified: {manifest.get('stocks_with_benchmark_data', 0)}")
    print(f"Using default params: {manifest.get('stocks_using_default', 0)}")
    
    # Global threshold adjustment
    global BUY_THRESHOLD
    BUY_THRESHOLD = args.min_confidence
    
    # Scan all stocks
    print("\nScanning all stocks...")
    results = scan_all_stocks(manifest, top_n=args.top, min_confidence=args.min_confidence)
    
    # Print summary
    print_summary(results)
    
    # Print top recommendations
    print_top_recommendations(results, top_n=args.top)
    
    # Save if requested
    if args.save:
        save_results(results)
    
    return results


if __name__ == "__main__":
    main()
