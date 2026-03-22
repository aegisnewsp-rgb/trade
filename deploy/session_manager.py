#!/usr/bin/env python3
"""
Session Manager - Trading Session Orchestrator

Manages daily trading session:
- Pre-market (8:30 AM IST): Creates trading plan
- Post-market (3:30 PM IST): Closes positions, records P&L, generates report

Usage:
    python session_manager.py [--mode pre-market|post-market|simulate]
"""

import argparse
import json
import os
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Optional


# IST timezone handling
IST_OFFSET = 5.5  # UTC+5:30


def get_ist_time() -> datetime:
    """Get current time in IST."""
    utc_now = datetime.utcnow()
    return utc_now + timedelta(hours=IST_OFFSET)


def is_market_day(ist_time: datetime = None) -> bool:
    """
    Check if today is a trading day (Monday-Friday).
    
    Args:
        ist_time: Current IST time (optional, uses current time if None)
        
    Returns:
        True if market is open, False if weekend
    """
    if ist_time is None:
        ist_time = get_ist_time()
    
    # 0 = Monday, 6 = Sunday
    return ist_time.weekday() < 5


def load_json_file(filepath: str) -> Optional[dict]:
    """
    Safely load a JSON file.
    
    Args:
        filepath: Path to JSON file
        
    Returns:
        Parsed JSON dict or None if file doesn't exist
    """
    path = Path(filepath)
    if not path.exists():
        return None
    
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[WARN] Could not load {filepath}: {e}")
        return None


def get_latest_file(directory: str, pattern: str) -> Optional[str]:
    """
    Get the most recent file matching a pattern in a directory.
    
    Args:
        directory: Directory to search
        pattern: Filename pattern (e.g., 'portfolio_weights*.json')
        
    Returns:
        Path to most recent file or None
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return None
    
    files = list(dir_path.glob(pattern))
    if not files:
        return None
    
    # Sort by modification time, newest first
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return str(files[0])


def load_portfolio_weights(deploy_dir: str = '/home/node/workspace/trade-project/deploy') -> dict:
    """
    Load the latest portfolio weights from optimizer output.
    
    Args:
        deploy_dir: Path to deploy directory
        
    Returns:
        Dictionary with portfolio weights or empty dict
    """
    weights_file = get_latest_file(deploy_dir, 'portfolio_weights*.json')
    
    if weights_file:
        data = load_json_file(weights_file)
        if data and 'optimal_weights' in data:
            print(f"[*] Loaded portfolio weights from: {weights_file}")
            return data['optimal_weights']
    
    print("[WARN] No portfolio weights found, using default allocation")
    return {}


def load_market_timer_output(deploy_dir: str = '/home/node/workspace/trade-project/deploy') -> dict:
    """
    Load the latest market timer output.
    
    Args:
        deploy_dir: Path to deploy directory
        
    Returns:
        Dictionary with market timer data or default
    """
    timer_file = get_latest_file(deploy_dir, 'market_timer_output*.json')
    
    if timer_file:
        data = load_json_file(timer_file)
        if data and 'exposure' in data:
            print(f"[*] Loaded market timer data from: {timer_file}")
            return data
    
    print("[WARN] No market timer data found, defaulting to NEUTRAL")
    return {
        'exposure': {
            'level': 'NEUTRAL',
            'allocation_percent': 50
        }
    }


def calculate_position_sizes(portfolio_weights: dict, 
                            exposure_allocation: int,
                            total_capital: float = 100000) -> dict:
    """
    Calculate adjusted position sizes based on market exposure.
    
    Args:
        portfolio_weights: Dictionary of ticker -> weight
        exposure_allocation: Base allocation percentage (from market timer)
        total_capital: Total trading capital (default 100000)
        
    Returns:
        Dictionary with final position sizes
    """
    base_allocation = exposure_allocation / 100.0
    
    positions = {}
    for ticker, weight in portfolio_weights.items():
        if weight > 0.01:  # Only include meaningful positions
            # Adjust weight by exposure level
            adjusted_weight = weight * base_allocation
            position_value = total_capital * adjusted_weight
            
            positions[ticker] = {
                'weight': round(weight, 4),
                'adjusted_weight': round(adjusted_weight, 4),
                'allocation_percent': round(adjusted_weight * 100, 2),
                'value': round(position_value, 2)
            }
    
    return positions


def create_trading_plan(positions: dict, 
                       market_data: dict,
                       session_date: str) -> dict:
    """
    Create a complete trading plan for the session.
    
    Args:
        positions: Calculated position sizes
        market_data: Market timer data
        session_date: Date string (YYYY-MM-DD)
        
    Returns:
        Complete trading plan dictionary
    """
    scripts_to_run = []
    
    for ticker, position in positions.items():
        # Map ticker to script name
        script_name = f"{ticker}.py"
        
        scripts_to_run.append({
            'ticker': ticker,
            'script': script_name,
            'action': 'BUY' if position['adjusted_weight'] > 0 else 'HOLD',
            'weight': position['weight'],
            'adjusted_weight': position['adjusted_weight'],
            'allocation_percent': position['allocation_percent'],
            'estimated_value': position['value']
        })
    
    plan = {
        'session_date': session_date,
        'created_at': datetime.now().isoformat(),
        'market_exposure': market_data.get('exposure', {}),
        'total_positions': len(scripts_to_run),
        'scripts': scripts_to_run,
        'summary': {
            'total_allocation': sum(s['allocation_percent'] for s in scripts_to_run),
            'cash_requirement': sum(s['estimated_value'] for s in scripts_to_run)
        }
    }
    
    return plan


def save_trading_plan(plan: dict, output_dir: str = '/home/node/workspace/trade-project/deploy') -> str:
    """
    Save trading plan to JSON file.
    
    Args:
        plan: Trading plan dictionary
        output_dir: Output directory
        
    Returns:
        Path to saved file
    """
    session_date = plan['session_date']
    filename = f"session_plan_{session_date}.json"
    output_path = Path(output_dir) / filename
    
    with open(output_path, 'w') as f:
        json.dump(plan, f, indent=2)
    
    print(f"[*] Trading plan saved to: {output_path}")
    return str(output_path)


def display_trading_plan(plan: dict):
    """
    Display the trading plan in a formatted manner.
    
    Args:
        plan: Trading plan dictionary
    """
    print("\n" + "=" * 60)
    print(f"TRADING PLAN - {plan['session_date']}")
    print("=" * 60)
    
    exposure = plan['market_exposure']
    print(f"\n  Market Exposure: {exposure.get('level', 'UNKNOWN')} ({exposure.get('allocation_percent', 0)}%)")
    print(f"  Signal: {exposure.get('signal_reason', 'N/A')}")
    
    print(f"\n  Total Positions: {plan['total_positions']}")
    print(f"  Total Allocation: {plan['summary']['total_allocation']:.1f}%")
    
    print("\n" + "-" * 60)
    print("SCRIPTS TO EXECUTE")
    print("-" * 60)
    
    for script in plan['scripts']:
        action_icon = "🟢" if script['action'] == 'BUY' else "⚪"
        print(f"\n  {action_icon} {script['script']}")
        print(f"     Ticker    : {script['ticker']}")
        print(f"     Action    : {script['action']}")
        print(f"     Weight    : {script['weight']*100:.1f}%")
        print(f"     Adjusted  : {script['adjusted_weight']*100:.1f}%")
        print(f"     Value     : ₹{script['estimated_value']:,.2f}")
    
    print("\n" + "=" * 60)


def run_premarket_session(ist_time: datetime = None) -> dict:
    """
    Execute pre-market session tasks.
    
    Args:
        ist_time: Current IST time
        
    Returns:
        Trading plan dictionary
    """
    if ist_time is None:
        ist_time = get_ist_time()
    
    session_date = ist_time.strftime('%Y-%m-%d')
    
    print("=" * 60)
    print("PRE-MARKET SESSION")
    print(f"Session Date: {session_date}")
    print(f"Local Time: {ist_time.strftime('%Y-%m-%d %H:%M:%S')} IST")
    print("=" * 60)
    
    # Check if market is open today
    if not is_market_day(ist_time):
        print("\n⚠️  WARNING: Today is a weekend/holiday. No trading session.")
        plan = {
            'session_date': session_date,
            'market_closed': True,
            'reason': 'Weekend or market holiday'
        }
        return plan
    
    # Load portfolio weights
    print("\n[*] Loading portfolio weights...")
    portfolio_weights = load_portfolio_weights()
    
    # Load market timer output
    print("[*] Loading market timer data...")
    market_data = load_market_timer_output()
    
    # Calculate position sizes
    exposure_level = market_data.get('exposure', {}).get('level', 'NEUTRAL')
    exposure_allocation = market_data.get('exposure', {}).get('allocation_percent', 50)
    
    print(f"[*] Market exposure: {exposure_level} ({exposure_allocation}%)")
    
    positions = calculate_position_sizes(
        portfolio_weights,
        exposure_allocation
    )
    
    # Create trading plan
    plan = create_trading_plan(positions, market_data, session_date)
    
    # Display and save
    display_trading_plan(plan)
    save_trading_plan(plan)
    
    return plan


def calculate_pnl(opened_positions: list, current_prices: dict) -> dict:
    """
    Calculate profit/loss for closed positions.
    
    Args:
        opened_positions: List of position dicts with entry prices
        current_prices: Dict of ticker -> current price
        
    Returns:
        P&L summary dictionary
    """
    total_pnl = 0
    total_invested = 0
    positions_pnl = []
    
    for pos in opened_positions:
        ticker = pos['ticker']
        entry_price = pos.get('entry_price', 0)
        quantity = pos.get('quantity', 0)
        current_price = current_prices.get(ticker, entry_price)
        
        invested = entry_price * quantity
        current_value = current_price * quantity
        pnl = current_value - invested
        pnl_percent = (pnl / invested * 100) if invested > 0 else 0
        
        total_pnl += pnl
        total_invested += invested
        
        positions_pnl.append({
            'ticker': ticker,
            'entry_price': entry_price,
            'current_price': current_price,
            'quantity': quantity,
            'invested': invested,
            'current_value': current_value,
            'pnl': pnl,
            'pnl_percent': pnl_percent
        })
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_invested': round(total_invested, 2),
        'total_return_percent': round((total_pnl / total_invested * 100) if total_invested > 0 else 0, 2),
        'positions': positions_pnl
    }


def load_opened_positions(session_date: str, deploy_dir: str = '/home/node/workspace/trade-project/deploy') -> list:
    """
    Load positions that were opened during this session.
    
    Args:
        session_date: Date string (YYYY-MM-DD)
        deploy_dir: Deploy directory path
        
    Returns:
        List of opened positions
    """
    plan_file = Path(deploy_dir) / f"session_plan_{session_date}.json"
    
    if not plan_file.exists():
        print("[WARN] No session plan found for today")
        return []
    
    plan = load_json_file(str(plan_file))
    
    if not plan or 'scripts' not in plan:
        return []
    
    # Extract BUY positions as "opened"
    return [
        {'ticker': s['ticker'], 'quantity': 0, 'entry_price': 0}
        for s in plan['scripts'] 
        if s.get('action') == 'BUY'
    ]


def generate_daily_report(session_date: str, 
                         pnl_data: dict,
                         market_data: dict,
                         deploy_dir: str = '/home/node/workspace/trade-project/deploy') -> dict:
    """
    Generate end-of-day summary report.
    
    Args:
        session_date: Date string
        pnl_data: P&L calculation data
        market_data: Market timer data
        deploy_dir: Output directory
        
    Returns:
        Report dictionary
    """
    report = {
        'report_date': session_date,
        'generated_at': datetime.now().isoformat(),
        'market_exposure': market_data.get('exposure', {}),
        'trading_summary': {
            'total_pnl': pnl_data.get('total_pnl', 0),
            'total_invested': pnl_data.get('total_invested', 0),
            'total_return_percent': pnl_data.get('total_return_percent', 0),
            'positions_closed': len(pnl_data.get('positions', []))
        },
        'positions': pnl_data.get('positions', [])
    }
    
    # Save report
    report_file = Path(deploy_dir) / f"daily_report_{session_date}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"[*] Daily report saved to: {report_file}")
    
    return report


def display_pnl_report(pnl_data: dict, session_date: str):
    """
    Display P&L report.
    
    Args:
        pnl_data: P&L data dictionary
        session_date: Session date string
    """
    print("\n" + "=" * 60)
    print(f"POST-MARKET REPORT - {session_date}")
    print("=" * 60)
    
    print("\n  CLOSING ALL POSITIONS...")
    print(f"  Total Invested : ₹{pnl_data.get('total_invested', 0):,.2f}")
    print(f"  Total P&L       : ₹{pnl_data.get('total_pnl', 0):,.2f}")
    print(f"  Return %        : {pnl_data.get('total_return_percent', 0):.2f}%")
    
    if pnl_data.get('positions'):
        print("\n" + "-" * 60)
        print("POSITION BREAKDOWN")
        print("-" * 60)
        
        for pos in pnl_data['positions']:
            pnl_sign = "+" if pos['pnl'] >= 0 else ""
            print(f"\n  {pos['ticker']}:")
            print(f"    Entry   : ₹{pos['entry_price']:,.2f}")
            print(f"    Exit    : ₹{pos['current_price']:,.2f}")
            print(f"    P&L     : {pnl_sign}₹{pos['pnl']:,.2f} ({pnl_sign}{pos['pnl_percent']:.2f}%)")
    
    print("\n" + "=" * 60)


def run_postmarket_session(ist_time: datetime = None, simulate: bool = False) -> dict:
    """
    Execute post-market session tasks.
    
    Args:
        ist_time: Current IST time
        simulate: If True, don't actually close positions
        
    Returns:
        Session results dictionary
    """
    if ist_time is None:
        ist_time = get_ist_time()
    
    session_date = ist_time.strftime('%Y-%m-%d')
    
    print("=" * 60)
    print("POST-MARKET SESSION")
    print(f"Session Date: {session_date}")
    print(f"Local Time: {ist_time.strftime('%Y-%m-%d %H:%M:%S')} IST")
    print("=" * 60)
    
    # Check if market is open today
    if not is_market_day(ist_time):
        print("\n⚠️  No trading session today (weekend/holiday)")
        return {'session_date': session_date, 'no_session': True}
    
    # Load today's trading plan
    plan_file = Path('/home/node/workspace/trade-project/deploy') / f"session_plan_{session_date}.json"
    
    if not plan_file.exists():
        print("[WARN] No trading plan found for today")
        return {'session_date': session_date, 'no_plan': True}
    
    plan = load_json_file(str(plan_file))
    
    # Load market data
    market_data = load_market_timer_output()
    
    # Get current prices (or simulate)
    current_prices = {}
    
    if simulate:
        # In simulation mode, use entry prices
        for script in plan.get('scripts', []):
            current_prices[script['ticker']] = script.get('estimated_value', 100)
    else:
        # Fetch actual current prices
        print("\n[*] Fetching current market prices...")
        import yfinance as yf
        
        for script in plan.get('scripts', []):
            ticker = script['ticker']
            try:
                stock = yf.Ticker(ticker)
                current_price = stock.history(period='1d')['Close'][-1]
                current_prices[ticker] = current_price
            except Exception as e:
                print(f"[WARN] Could not fetch {ticker}: {e}")
                current_prices[ticker] = script.get('estimated_value', 100)
    
    # Load opened positions
    opened_positions = load_opened_positions(session_date)
    
    # Calculate P&L
    pnl_data = calculate_pnl(opened_positions, current_prices)
    
    # Display report
    display_pnl_report(pnl_data, session_date)
    
    # Generate and save daily report
    report = generate_daily_report(session_date, pnl_data, market_data)
    
    print("\n[*] Post-market session completed")
    
    return report


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Session Manager - Trading Session Orchestrator'
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['pre-market', 'post-market', 'simulate'],
        default='pre-market',
        help='Session mode to run (default: pre-market)'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Session date (YYYY-MM-DD), defaults to today'
    )
    parser.add_argument(
        '--deploy-dir',
        type=str,
        default='/home/node/workspace/trade-project/deploy',
        help='Deploy directory path'
    )
    
    args = parser.parse_args()
    
    # Determine session date
    if args.date:
        session_date = args.date
        from datetime import timedelta
        ist_time = get_ist_time().replace(hour=9, minute=0, second=0)
    else:
        ist_time = get_ist_time()
        session_date = ist_time.strftime('%Y-%m-%d')
    
    # Run appropriate session
    if args.mode == 'pre-market':
        run_premarket_session(ist_time)
    elif args.mode == 'post-market':
        run_postmarket_session(ist_time)
    elif args.mode == 'simulate':
        # Simulate a full trading day
        print("\n" + "=" * 60)
        print("SIMULATION MODE")
        print("=" * 60)
        
        print("\n--- PRE-MARKET ---")
        run_premarket_session(ist_time)
        
        print("\n--- POST-MARKET (Simulated) ---")
        run_postmarket_session(ist_time, simulate=True)


if __name__ == '__main__':
    main()
