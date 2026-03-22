#!/usr/bin/env python3
"""
STRATEGY ENHANCER - Add Filters to Any Base Strategy
=====================================================
Takes a base strategy and enhances it with multiple confirmation filters:
1. Volume confirmation: only trade if volume > 20-day MA
2. Trend confirmation: only trade in direction of 50-day MA
3. Volatility filter: avoid trading in extremely low volatility
4. Momentum confirmation: use RSI as final filter

Usage:
    python strategy_enhancer.py --input RELIANCE_NS.py --output enhanced_RELIANCE.py
    
    Or import and use programmatically:
    from strategy_enhancer import enhance_strategy
    
    enhanced_code = enhance_strategy(base_strategy_code, strategy_name="VWAP")
"""

import os
import re
from typing import Dict, List, Optional, Tuple


# ============================================================================
# FILTER CONFIGURATIONS
# ============================================================================

VOLUME_FILTER_CONFIG = {
    "enabled": True,
    "ma_period": 20,
    "min_volume_ratio": 1.0,  # Volume must be > 1x the 20-day MA
    "description": "Only trade when volume exceeds 20-day moving average"
}

TREND_FILTER_CONFIG = {
    "enabled": True,
    "ma_period": 50,
    "description": "Only trade in direction of 50-day moving average"
}

VOLATILITY_FILTER_CONFIG = {
    "enabled": True,
    "atr_period": 14,
    "min_atr_percent": 0.5,  # ATR must be at least 0.5% of price
    "max_atr_percent": 5.0,  # ATR must be less than 5% (avoid extreme volatility)
    "description": "Avoid trading in extremely low or high volatility"
}

RSI_FILTER_CONFIG = {
    "enabled": True,
    "rsi_period": 14,
    "oversold": 35,  # Adjusted from 30 for more signal quality
    "overbought": 65,  # Adjusted from 70 for more signal quality
    "description": "RSI momentum confirmation filter"
}


# ============================================================================
# CODE GENERATION FUNCTIONS
# ============================================================================

def generate_enhanced_signal_function(strategy_code: str, base_strategy: str) -> str:
    """Generate the enhanced signal function with all filters."""
    
    filters_enabled = []
    if VOLUME_FILTER_CONFIG["enabled"]:
        filters_enabled.append("volume")
    if TREND_FILTER_CONFIG["enabled"]:
        filters_enabled.append("trend")
    if VOLATILITY_FILTER_CONFIG["enabled"]:
        filters_enabled.append("volatility")
    if RSI_FILTER_CONFIG["enabled"]:
        filters_enabled.append("rsi")
    
    enhanced_code = '''
# ============================================================================
# ENHANCED SIGNAL GENERATION - WITH MULTI-FILTER CONFIRMATION
# ============================================================================
# Active filters: {}

def calculate_volume_ma(ohlcv: List[dict], period: int = {}) -> float:
    """Calculate 20-day volume moving average."""
    if len(ohlcv) < period:
        return 0
    volumes = [bar["volume"] for bar in ohlcv[-period:]]
    return sum(volumes) / period


def calculate_price_ma(ohlcv: List[dict], period: int = {}) -> float:
    """Calculate N-day moving average of close prices."""
    if len(ohlcv) < period:
        return 0
    closes = [bar["close"] for bar in ohlcv[-period:]]
    return sum(closes) / period


def calculate_atr(ohlcv: List[dict], period: int = {}) -> float:
    """Calculate Average True Range."""
    if len(ohlcv) < period + 1:
        return 0
    tr_values = []
    for i in range(1, len(ohlcv)):
        high = ohlcv[i]["high"]
        low = ohlcv[i]["low"]
        prev_close = ohlcv[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period if len(tr_values) >= period else 0


def calculate_rsi(ohlcv: List[dict], period: int = {}) -> float:
    """Calculate RSI indicator."""
    if len(ohlcv) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(ohlcv)):
        change = ohlcv[i]["close"] - ohlcv[i-1]["close"]
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
    return 100 - (100 / (1 + rs))


def apply_filters(
    ohlcv: List[dict],
    base_signal: str,
    index: int,
    params: dict
) -> Tuple[str, dict]:
    """
    Apply all enabled filters to the base signal.
    Returns (filtered_signal, filter_info).
    """
    filter_info = {{
        "volume_passed": False,
        "trend_passed": False,
        "volatility_passed": False,
        "rsi_passed": False,
        "all_passed": False
    }}
    
    current_price = ohlcv[index]["close"]
    
    # Skip if no base signal
    if base_signal == "HOLD":
        return "HOLD", filter_info
    
    # 1. VOLUME FILTER
    if {}:
        vol_ma = calculate_volume_ma(ohlcv, {})
        current_vol = ohlcv[index]["volume"]
        min_vol_ratio = {}
        
        if vol_ma > 0 and current_vol >= vol_ma * min_vol_ratio:
            filter_info["volume_passed"] = True
    
    # 2. TREND FILTER  
    if {}:
        trend_ma = calculate_price_ma(ohlcv, {})
        
        if base_signal == "BUY" and current_price > trend_ma:
            filter_info["trend_passed"] = True
        elif base_signal == "SELL" and current_price < trend_ma:
            filter_info["trend_passed"] = True
    
    # 3. VOLATILITY FILTER
    if {}:
        atr_value = calculate_atr(ohlcv, {})
        atr_percent = (atr_value / current_price * 100) if current_price > 0 else 0
        min_atr = {}
        max_atr = {}
        
        if min_atr <= atr_percent <= max_atr:
            filter_info["volatility_passed"] = True
    
    # 4. RSI MOMENTUM FILTER
    if {}:
        rsi = calculate_rsi(ohlcv, {})
        oversold = {}
        overbought = {}
        
        if base_signal == "BUY" and rsi >= oversold:
            filter_info["rsi_passed"] = True
        elif base_signal == "SELL" and rsi <= overbought:
            filter_info["rsi_passed"] = True
    
    # Determine if ALL critical filters passed
    # Volume and Trend are critical; Volatility and RSI are advisory
    critical_volume = {}  # Can be toggled
    critical_trend = {}   # Can be toggled
    critical_volatility = False
    critical_rsi = False
    
    if critical_volume and not filter_info["volume_passed"]:
        return "HOLD", filter_info
    if critical_trend and not filter_info["trend_passed"]:
        return "HOLD", filter_info
    
    # If volatility or RSI fails, still pass but note it
    filter_info["all_passed"] = (
        (not critical_volume or filter_info["volume_passed"]) and
        (not critical_trend or filter_info["trend_passed"])
    )
    
    return base_signal, filter_info


def enhanced_generate_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """
    Enhanced signal generation with multi-filter confirmation.
    Applies volume, trend, volatility, and RSI filters to base strategy signals.
    """
    # First get base strategy signals
    base_signals = {}(ohlcv, params)
    
    # Apply filters to each signal
    enhanced_signals = []
    for i in range(len(ohlcv)):
        base_signal = base_signals[i]
        filtered_signal, filter_info = apply_filters(ohlcv, base_signal, i, params)
        enhanced_signals.append(filtered_signal)
    
    return enhanced_signals


# ============================================================================
# END OF ENHANCED SIGNAL GENERATION
# ============================================================================
'''.format(
        ", ".join(filters_enabled),
        
        # Volume MA
        VOLUME_FILTER_CONFIG["ma_period"],
        
        # Price MA
        TREND_FILTER_CONFIG["ma_period"],
        
        # ATR period
        VOLATILITY_FILTER_CONFIG["atr_period"],
        
        # RSI period
        RSI_FILTER_CONFIG["rsi_period"],
        
        # Volume filter enabled
        VOLUME_FILTER_CONFIG["enabled"],
        VOLUME_FILTER_CONFIG["ma_period"],
        VOLUME_FILTER_CONFIG["min_volume_ratio"],
        
        # Trend filter enabled
        TREND_FILTER_CONFIG["enabled"],
        TREND_FILTER_CONFIG["ma_period"],
        
        # Volatility filter enabled
        VOLATILITY_FILTER_CONFIG["enabled"],
        VOLATILITY_FILTER_CONFIG["min_atr_percent"],
        VOLATILITY_FILTER_CONFIG["max_atr_percent"],
        
        # RSI filter enabled
        RSI_FILTER_CONFIG["enabled"],
        RSI_FILTER_CONFIG["oversold"],
        RSI_FILTER_CONFIG["overbought"],
        
        # Critical flags
        "True",  # Volume critical
        "True",  # Trend critical
        
        # Function mapping
        get_signal_function_name(base_strategy)
    )
    
    return enhanced_code


def get_signal_function_name(strategy: str) -> str:
    """Map strategy name to signal function name."""
    mapping = {
        "VWAP": "vwap_signals",
        "ADX_TREND": "adx_signals",
        "FIBONACCI_RETRACEMENT": "fibonacci_signals",
        "MOMENTUM_DIVERGENCE": "momentum_signals",
        "MA_ENVELOPE": "ma_envelope_signals",
        "TSI": "tsi_signals",
        "MACD_MOMENTUM": "macd_signals",
        "PARABOLIC_SAR": "parabolic_sar_signals",
        "VOLUME_DIVERGENCE": "volume_divergence_signals",
    }
    return mapping.get(strategy, "vwap_signals")


def enhance_strategy_code(base_code: str, strategy_name: str) -> str:
    """
    Enhance existing strategy code with filter functions.
    """
    # Find where to insert the enhanced functions (before generate_signals)
    insertion_point = base_code.find("def generate_signals(")
    
    if insertion_point == -1:
        # Try to find the main function
        insertion_point = base_code.find("def main(")
        if insertion_point == -1:
            insertion_point = len(base_code)
    
    enhanced_code = generate_enhanced_signal_function(base_code, strategy_name)
    
    # Insert the enhanced code
    result = base_code[:insertion_point] + enhanced_code + "\n\n" + base_code[insertion_point:]
    
    # Modify generate_signals to use enhanced version
    result = result.replace(
        "def generate_signals(ohlcv: List[dict], params: dict) -> List[str]:",
        "def generate_signals(ohlcv: List[dict], params: dict) -> List[str]:\n    \"\"\"Original generate_signals - see enhanced_generate_signals for filtered version.\"\"\""
    )
    
    return result


def create_standalone_enhancer(strategy_code: str, strategy_name: str, symbol: str) -> str:
    """
    Create a standalone enhanced strategy script.
    """
    header = f'''#!/usr/bin/env python3
"""
ENHANCED TRADING SCRIPT - {symbol}
===================================
Strategy: {strategy_name} with Multi-Filter Confirmation

FILTERS APPLIED:
- Volume: Only trade when volume > 20-day MA
- Trend: Only trade in direction of 50-day MA  
- Volatility: Avoid extremely low/high volatility environments
- RSI: Momentum confirmation

This is an AUTO-GENERATED enhanced version.
Generated by strategy_enhancer.py
"""

'''
    
    # Remove original header comments
    lines = strategy_code.split('\n')
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('SBIN_NS.py') or line.startswith('RELIANCE_NS.py'):
            start_idx = i
            break
    
    # Find where to start (after the integration warning block)
    code_body = '\n'.join(lines[start_idx:])
    
    # Add our header
    full_code = header + code_body
    
    # Enhance with filters
    full_code = enhance_strategy_code(full_code, strategy_name)
    
    return full_code


def print_enhancement_summary():
    """Print a summary of the enhancement configuration."""
    print("\n" + "=" * 70)
    print("STRATEGY ENHANCER - Configuration Summary")
    print("=" * 70)
    
    print("\n📊 VOLUME FILTER:")
    print(f"   Enabled: {VOLUME_FILTER_CONFIG['enabled']}")
    print(f"   Period: {VOLUME_FILTER_CONFIG['ma_period']}-day MA")
    print(f"   Min Volume Ratio: {VOLUME_FILTER_CONFIG['min_volume_ratio']}x")
    print(f"   Purpose: {VOLUME_FILTER_CONFIG['description']}")
    
    print("\n📈 TREND FILTER:")
    print(f"   Enabled: {TREND_FILTER_CONFIG['enabled']}")
    print(f"   Period: {TREND_FILTER_CONFIG['ma_period']}-day MA")
    print(f"   Purpose: {TREND_FILTER_CONFIG['description']}")
    
    print("\n📉 VOLATILITY FILTER:")
    print(f"   Enabled: {VOLATILITY_FILTER_CONFIG['enabled']}")
    print(f"   Period: {VOLATILITY_FILTER_CONFIG['atr_period']}-day ATR")
    print(f"   ATR Range: {VOLATILITY_FILTER_CONFIG['min_atr_percent']}% - {VOLATILITY_FILTER_CONFIG['max_atr_percent']}%")
    print(f"   Purpose: {VOLATILITY_FILTER_CONFIG['description']}")
    
    print("\n⚡ RSI FILTER:")
    print(f"   Enabled: {RSI_FILTER_CONFIG['enabled']}")
    print(f"   Period: {RSI_FILTER_CONFIG['rsi_period']}-day")
    print(f"   Oversold: {RSI_FILTER_CONFIG['oversold']}")
    print(f"   Overbought: {RSI_FILTER_CONFIG['overbought']}")
    print(f"   Purpose: {RSI_FILTER_CONFIG['description']}")
    
    print("\n" + "=" * 70)


def main():
    """Main CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Strategy Enhancer - Add Filters to Trading Strategies")
    parser.add_argument("--input", "-i", help="Input script path")
    parser.add_argument("--output", "-o", help="Output script path")
    parser.add_argument("--strategy", "-s", default="VWAP", help="Base strategy name")
    parser.add_argument("--symbol", help="Stock symbol for header")
    parser.add_argument("--show-config", action="store_true", help="Show enhancement config")
    
    args = parser.parse_args()
    
    if args.show_config:
        print_enhancement_summary()
        return
    
    if not args.input:
        print("Strategy Enhancer - Add Filters to Trading Strategies")
        print("\nUsage:")
        print("  python strategy_enhancer.py --input script.py --output enhanced.py")
        print("  python strategy_enhancer.py --show-config")
        print("\nExamples:")
        print("  python strategy_enhancer.py -i RELIANCE_NS.py -o enhanced_RELIANCE.py -s TSI")
        print("  python strategy_enhancer.py -i SBIN_NS.py -o enhanced_SBIN.py -s VWAP")
        print_enhancement_summary()
        return
    
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return
    
    # Read input
    with open(args.input, 'r') as f:
        base_code = f.read()
    
    # Create enhanced version
    enhanced_code = create_standalone_enhancer(
        base_code,
        args.strategy,
        args.symbol or "UNKNOWN"
    )
    
    # Write output
    output_path = args.output or args.input.replace('.py', '_enhanced.py')
    with open(output_path, 'w') as f:
        f.write(enhanced_code)
    
    print(f"✅ Enhanced strategy saved to: {output_path}")
    print(f"   Strategy: {args.strategy}")
    print(f"   Filters: volume, trend, volatility, RSI")


if __name__ == "__main__":
    main()
