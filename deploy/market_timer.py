#!/usr/bin/env python3
"""
Market Timer - Market Timing and Exposure Level Module

Determines market exposure level (EXPOUT/NEUTRAL/DEFENSIVE) based on:
- NIFTY 50 trend (20-day SMA)
- VIX-like volatility measure
- Market strength (% of top stocks above their MA)

Usage:
    python market_timer.py [--output JSON_FILE]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import yfinance as yf


# Top 10 NIFTY stocks for market strength calculation
NIFTY_TOP_10 = [
    'RELIANCE_NS', 'HDFCBANK_NS', 'ICICIBANK_NS', 'INFY_NS', 'HDFC_NS',
    'ITC_NS', 'KOTAKBANK_NS', 'LT_NS', 'SBIN_NS', 'BHARTIARTL_NS'
]


def get_market_data(ticker: str, days: int = 60) -> 'pd.Series':
    """
    Fetch historical data for a market index.
    
    Args:
        ticker: Index ticker symbol (e.g., '^NSEI' for NIFTY 50)
        days: Number of days of historical data
        
    Returns:
        Series of closing prices
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 30)
    
    try:
        index = yf.Ticker(ticker)
        df = index.history(start=start_date, end=end_date)
        return df['Close']
    except Exception as e:
        print(f"[ERROR] Failed to fetch {ticker}: {e}")
        return None


def calculate_sma(prices: np.ndarray, period: int = 20) -> np.ndarray:
    """
    Calculate Simple Moving Average.
    
    Args:
        prices: Array of prices
        period: SMA period (default 20 days)
        
    Returns:
        Array of SMA values
    """
    sma = np.convolve(prices, np.ones(period)/period, mode='valid')
    return sma


def calculate_volatility(returns: np.ndarray, period: int = 20) -> float:
    """
    Calculate VIX-like volatility measure using 20-day std dev of returns.
    
    Args:
        returns: Array of daily returns
        period: Lookback period (default 20 days)
        
    Returns:
        Annualized volatility percentage
    """
    if len(returns) < period:
        return 0.0
    
    # Use last 'period' returns for rolling volatility
    recent_returns = returns[-period:]
    daily_std = np.std(recent_returns)
    
    # Annualize (252 trading days)
    annualized_vol = daily_std * np.sqrt(252) * 100
    
    return annualized_vol


def calculate_market_strength(tickers: list, period: int = 20) -> float:
    """
    Calculate market strength: % of top 10 NIFTY stocks above their 20-day MA.
    
    Args:
        tickers: List of ticker symbols
        period: MA period (default 20 days)
        
    Returns:
        Percentage of stocks currently above their SMA
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=60)
    
    stocks_above_ma = 0
    total_stocks = 0
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)
            
            if len(df) < period + 5:
                continue
                
            prices = df['Close'].values
            sma = np.mean(prices[-period:])
            current_price = prices[-1]
            
            if current_price > sma:
                stocks_above_ma += 1
                
            total_stocks += 1
            
        except Exception as e:
            print(f"[WARN] Could not process {ticker}: {e}")
            continue
    
    if total_stocks == 0:
        return 0.0
    
    return (stocks_above_ma / total_stocks) * 100


def determine_exposure(nifty_above_sma: bool, market_strength: float) -> tuple:
    """
    Determine market exposure level based on rules.
    
    Rules:
    - If NIFTY > 20-day SMA AND market_strength > 60% → EXPOUT (100%)
    - If NIFTY < 20-day SMA OR market_strength < 40% → DEFENSIVE (20%)
    - Otherwise → NEUTRAL (50%)
    
    Args:
        nifty_above_sma: Boolean indicating if NIFTY is above its SMA
        market_strength: Percentage of stocks above their MA
        
    Returns:
        Tuple of (exposure_level, allocation_percentage, signal_reason)
    """
    if nifty_above_sma and market_strength > 60:
        return 'EXPOUT', 100, 'NIFTY bullish + strong market breadth'
    elif not nifty_above_sma or market_strength < 40:
        return 'DEFENSIVE', 20, 'NIFTY bearish OR weak market breadth'
    else:
        return 'NEUTRAL', 50, 'Mixed signals, balanced approach'


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Market Timer - Determine Market Exposure Level'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--nifty',
        type=str,
        default='^NSEI',
        help='NIFTY 50 ticker (default: ^NSEI)'
    )
    parser.add_argument(
        '--nifty-bank',
        type=str,
        default='^NSEBANK',
        help='NIFTY Bank ticker (default: ^NSEBANK)'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Market Timer - NIFTY Market Analysis")
    print("=" * 60)
    
    # Fetch NIFTY 50 data
    print(f"\n[*] Fetching NIFTY 50 data ({args.nifty})...")
    nifty_data = get_market_data(args.nifty, days=60)
    
    if nifty_data is None or len(nifty_data) < 25:
        print("[ERROR] Could not fetch NIFTY 50 data")
        sys.exit(1)
    
    # Fetch NIFTY Bank data
    print(f"[*] Fetching NIFTY Bank data ({args.nifty_bank})...")
    bank_data = get_market_data(args.nifty_bank, days=60)
    
    # Calculate NIFTY 50 indicators
    nifty_prices = nifty_data.values
    nifty_sma_20 = calculate_sma(nifty_prices, period=20)
    
    if len(nifty_sma_20) == 0:
        print("[ERROR] Insufficient data for SMA calculation")
        sys.exit(1)
    
    current_nifty = nifty_prices[-1]
    current_sma = nifty_sma_20[-1]
    nifty_above_sma = current_nifty > current_sma
    
    # Calculate returns for volatility
    nifty_returns = np.diff(np.log(nifty_prices))
    nifty_volatility = calculate_volatility(nifty_returns)
    
    # Calculate market strength
    print(f"\n[*] Calculating market strength ({len(NIFTY_TOP_10)} stocks)...")
    market_strength = calculate_market_strength(NIFTY_TOP_10)
    
    # Determine exposure
    exposure_level, allocation, signal_reason = determine_exposure(
        nifty_above_sma, market_strength
    )
    
    # Calculate NIFTY Bank trend
    bank_trend = "BULLISH"
    if bank_data is not None and len(bank_data) >= 25:
        bank_prices = bank_data.values
        bank_sma = calculate_sma(bank_prices, period=20)
        if len(bank_sma) > 0 and bank_prices[-1] > bank_sma[-1]:
            bank_trend = "BULLISH"
        else:
            bank_trend = "BEARISH"
    
    # Prepare output
    output = {
        'timestamp': datetime.now().isoformat(),
        'nifty': {
            'current_price': round(current_nifty, 2),
            'sma_20': round(current_sma, 2),
            'above_sma': nifty_above_sma,
            'trend': 'BULLISH' if nifty_above_sma else 'BEARISH'
        },
        'nifty_bank': {
            'trend': bank_trend
        },
        'volatility': {
            'vix_like': round(nifty_volatility, 2),
            'level': 'HIGH' if nifty_volatility > 25 else ('LOW' if nifty_volatility < 15 else 'MODERATE')
        },
        'market_strength': {
            'percent_above_ma': round(market_strength, 1),
            'stocks_analyzed': len(NIFTY_TOP_10)
        },
        'exposure': {
            'level': exposure_level,
            'allocation_percent': allocation,
            'signal_reason': signal_reason
        }
    }
    
    # Display results
    print("\n" + "=" * 60)
    print("MARKET ANALYSIS RESULTS")
    print("=" * 60)
    
    print(f"\n  NIFTY 50:")
    print(f"    Current Price : {current_nifty:,.2f}")
    print(f"    20-Day SMA    : {current_sma:,.2f}")
    print(f"    Trend         : {'🟢 BULLISH' if nifty_above_sma else '🔴 BEARISH'}")
    
    print(f"\n  NIFTY Bank:")
    print(f"    Trend         : {'🟢 BULLISH' if bank_trend == 'BULLISH' else '🔴 BEARISH'}")
    
    print(f"\n  Volatility (VIX-like):")
    print(f"    Annualized    : {nifty_volatility:.2f}%")
    print(f"    Level         : {output['volatility']['level']}")
    
    print(f"\n  Market Strength:")
    print(f"    Stocks above 20-MA : {market_strength:.1f}%")
    print(f"    Stocks analyzed    : {len(NIFTY_TOP_10)}")
    
    print("\n" + "-" * 60)
    print("EXPOSURE RECOMMENDATION")
    print("-" * 60)
    print(f"  Level       : {exposure_level}")
    print(f"  Allocation  : {allocation}%")
    print(f"  Signal      : {signal_reason}")
    print("=" * 60)
    
    # Save output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\n[*] Results saved to: {output_path}")
    else:
        # Default output path
        default_path = Path('/home/node/workspace/trade-project/deploy/market_timer_output.json')
        with open(default_path, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\n[*] Results saved to: {default_path}")
    
    return output


if __name__ == '__main__':
    main()
