#!/usr/bin/env python3
"""
Portfolio Optimizer - Modern Portfolio Theory Implementation

Uses Mean-Variance Optimization to find the maximum Sharpe ratio portfolio
from a set of stock recommendations.

Usage:
    python portfolio_optimizer.py [--tickers TICKER1,TICKER2,...] [--top-n 5]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import yfinance as yf
from scipy.optimize import minimize


def get_stock_data(tickers: list, days: int = 90) -> dict:
    """
    Fetch historical stock data using yfinance.
    
    Args:
        tickers: List of stock ticker symbols
        days: Number of days of historical data to fetch
        
    Returns:
        Dictionary with ticker as key and DataFrame as value
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 30)  # Extra buffer for SMA calc
    
    stock_data = {}
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)
            
            if len(df) > 30:  # Ensure we have enough data
                stock_data[ticker] = df['Close']
            else:
                print(f"[WARN] Insufficient data for {ticker}, skipping")
                
        except Exception as e:
            print(f"[WARN] Failed to fetch {ticker}: {e}")
            
    return stock_data


def calculate_returns(prices_df: 'pd.DataFrame') -> np.ndarray:
    """
    Calculate daily returns from price data.
    
    Args:
        prices_df: DataFrame with closing prices
        
    Returns:
        NumPy array of daily returns
    """
    returns = prices_df.pct_change().dropna()
    return returns.values


def calculate_covariance_matrix(returns: np.ndarray) -> np.ndarray:
    """
    Calculate the covariance matrix of returns.
    
    Args:
        returns: Array of return values
        
    Returns:
        Covariance matrix
    """
    return np.cov(returns.T)


def portfolio_performance(weights: np.ndarray, mean_returns: np.ndarray, 
                         cov_matrix: np.ndarray, risk_free_rate: float = 0.06) -> tuple:
    """
    Calculate portfolio return, volatility, and Sharpe ratio.
    
    Args:
        weights: Array of portfolio weights
        mean_returns: Array of mean returns for each asset
        cov_matrix: Covariance matrix of returns
        risk_free_rate: Annual risk-free rate (default 6%)
        
    Returns:
        Tuple of (annual_return, volatility, sharpe_ratio)
    """
    # Annualized return
    portfolio_return = np.sum(mean_returns * weights) * 252
    
    # Annualized volatility
    portfolio_std = np.sqrt(np.dot(weights.T, np.dot(cov_matrix * 252, weights)))
    
    # Sharpe ratio
    sharpe_ratio = (portfolio_return - risk_free_rate) / portfolio_std if portfolio_std > 0 else 0
    
    return portfolio_return, portfolio_std, sharpe_ratio


def negative_sharpe(weights: np.ndarray, mean_returns: np.ndarray, 
                   cov_matrix: np.ndarray, risk_free_rate: float = 0.06) -> float:
    """Negative Sharpe ratio for minimization."""
    return -portfolio_performance(weights, mean_returns, cov_matrix, risk_free_rate)[2]


def max_drawdown(prices: np.ndarray) -> float:
    """
    Calculate maximum drawdown from a price series.
    
    Args:
        prices: Array of portfolio values
        
    Returns:
        Maximum drawdown as a positive percentage
    """
    cummax = np.maximum.accumulate(prices)
    drawdown = (cummax - prices) / cummax
    return np.max(drawdown) * 100


def optimize_portfolio(mean_returns: np.ndarray, cov_matrix: np.ndarray,
                     n_assets: int, max_positions: int = 3,
                     max_weight: float = 0.40, min_weight: float = 0.10) -> dict:
    """
    Find the optimal portfolio weights using scipy optimization.
    
    Args:
        mean_returns: Mean returns for each asset
        cov_matrix: Covariance matrix
        n_assets: Number of assets to include
        max_positions: Maximum number of positions (default 3)
        max_weight: Maximum weight per position (default 40%)
        min_weight: Minimum weight per position (default 10%)
        
    Returns:
        Dictionary with optimal weights and portfolio metrics
    """
    # Constraints
    constraints = [
        {'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0}  # Weights sum to 1
    ]
    
    # Bounds: min_weight <= weight <= max_weight for each asset
    # For assets we're not using, set bounds to (0, 0)
    bounds = tuple((min_weight, max_weight) for _ in range(n_assets))
    
    # Initial guess: equal distribution
    initial_weights = np.array([1.0 / n_assets] * n_assets)
    
    # Optimize for negative Sharpe (minimize)
    result = minimize(
        negative_sharpe,
        initial_weights,
        args=(mean_returns, cov_matrix,),
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={'maxiter': 1000, 'ftol': 1e-9}
    )
    
    if not result.success:
        print(f"[WARN] Optimization did not converge: {result.message}")
    
    optimal_weights = result.x
    
    # Calculate portfolio metrics
    annual_return, volatility, sharpe = portfolio_performance(
        optimal_weights, mean_returns, cov_matrix
    )
    
    return {
        'weights': optimal_weights,
        'annual_return': annual_return,
        'volatility': volatility,
        'sharpe_ratio': sharpe
    }


def load_recommendations(scanner_output_path: str = None) -> list:
    """
    Load stock recommendations from master_scanner.py output.
    
    Args:
        scanner_output_path: Path to scanner output JSON file
        
    Returns:
        List of recommended tickers
    """
    if scanner_output_path and Path(scanner_output_path).exists():
        with open(scanner_output_path, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'recommendations' in data:
                return data['recommendations']
            elif isinstance(data, list):
                return data
    
    # Return sample recommendations if no file exists
    # In production, this would come from master_scanner.py output
    return ['RELIANCE_NS', 'HDFCBANK_NS', 'INFY_NS', 'TCS_NS', 'ICICIBANK_NS']


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Portfolio Optimizer - Modern Portfolio Theory'
    )
    parser.add_argument(
        '--tickers',
        type=str,
        help='Comma-separated list of tickers (overrides scanner output)'
    )
    parser.add_argument(
        '--top-n',
        type=int,
        default=5,
        help='Number of top stocks to include (default: 5)'
    )
    parser.add_argument(
        '--scanner-output',
        type=str,
        help='Path to master_scanner.py output JSON'
    )
    parser.add_argument(
        '--max-positions',
        type=int,
        default=3,
        help='Maximum number of positions (default: 3)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output JSON file path'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Portfolio Optimizer - Modern Portfolio Theory")
    print("=" * 60)
    
    # Get tickers
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',')]
    else:
        recommendations = load_recommendations(args.scanner_output)
        tickers = recommendations[:args.top_n]
    
    print(f"\n[*] Processing {len(tickers)} stocks: {tickers}")
    
    # Fetch data
    print("\n[*] Fetching 90 days of historical data...")
    stock_data = get_stock_data(tickers, days=90)
    
    if len(stock_data) < 2:
        print("[ERROR] Insufficient stock data for optimization")
        sys.exit(1)
    
    # Align data - use common dates
    import pandas as pd
    prices_df = pd.DataFrame(stock_data)
    prices_df = prices_df.dropna()
    
    if len(prices_df) < 60:
        print("[ERROR] Insufficient aligned data points")
        sys.exit(1)
    
    print(f"[*] Using {len(prices_df)} aligned data points")
    
    # Calculate returns
    returns = calculate_returns(prices_df)
    mean_returns = returns.mean(axis=0)
    cov_matrix = calculate_covariance_matrix(returns)
    
    print("\n[*] Running Mean-Variance Optimization...")
    
    # Optimize
    n_assets = len(tickers)
    result = optimize_portfolio(
        mean_returns,
        cov_matrix,
        n_assets,
        max_positions=args.max_positions
    )
    
    # Calculate max drawdown for the optimal portfolio
    portfolio_values = np.dot(returns, result['weights'])
    cumulative = np.cumprod(1 + portfolio_values)
    max_dd = max_drawdown(cumulative)
    
    # Prepare output
    output = {
        'timestamp': datetime.now().isoformat(),
        'tickers': tickers,
        'optimal_weights': {
            ticker: round(weight, 4) 
            for ticker, weight in zip(tickers, result['weights'])
        },
        'metrics': {
            'annual_return': round(result['annual_return'] * 100, 2),
            'volatility': round(result['volatility'] * 100, 2),
            'sharpe_ratio': round(result['sharpe_ratio'], 4),
            'max_drawdown': round(max_dd, 2)
        },
        'constraints': {
            'max_positions': args.max_positions,
            'max_weight_per_position': 0.40,
            'min_weight_per_position': 0.10
        }
    }
    
    # Display results
    print("\n" + "=" * 60)
    print("OPTIMAL PORTFOLIO ALLOCATION")
    print("=" * 60)
    
    for ticker, weight in output['optimal_weights'].items():
        if weight > 0.01:  # Only show meaningful positions
            print(f"  {ticker:20s}: {weight * 100:6.2f}%")
    
    print("\n" + "-" * 60)
    print("PORTFOLIO METRICS")
    print("-" * 60)
    print(f"  Expected Annual Return : {output['metrics']['annual_return']:7.2f}%")
    print(f"  Annual Volatility      : {output['metrics']['volatility']:7.2f}%")
    print(f"  Sharpe Ratio           : {output['metrics']['sharpe_ratio']:7.4f}")
    print(f"  Maximum Drawdown       : {output['metrics']['max_drawdown']:7.2f}%")
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
        default_path = Path('/home/node/workspace/trade-project/deploy/portfolio_weights.json')
        with open(default_path, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\n[*] Results saved to: {default_path}")
    
    return output


if __name__ == '__main__':
    main()
