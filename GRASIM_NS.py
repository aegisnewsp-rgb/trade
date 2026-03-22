#!/usr/bin/env python3
"""
⚠️ INTEGRATION WARNING - READ THIS FIRST ⚠️
=============================================
This script is a STANDALONE BACKTESTING TOOL only.
It is NOT integrated with autotrade-v2 live trading system.

To use with live trading:
1. This script generates signals from historical data
2. Integration with autotrade/main.py is required for live execution
3. The live trading system has bugs (see bugs.md) that prevent execution
4. Currently: Only 5 stocks in APPROVED_UNIVERSE (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK)

This script can be used for:
✓ Signal generation and backtesting
✓ Strategy validation
✓ Paper trading preparation

NOT for:
✗ Direct live trading (requires autotrade-v2 integration)
✗ Integration with Groww API for real-time trading

See: autotrade/main.py for live trading implementation.
=============================================

"""
GRASIM_NS.py - Production Trading Script

Stock: GRASIM.NS
Strategy: FIBONACCI_RETRACEMENT
Win Rate: 57.4% (from benchmark: benchmark)
Parameters: {'fib_levels': [0.236, 0.382, 0.5, 0.618, 0.786]}

COPY-PASTE READY FOR GROWW CLOUD DEPLOYMENT
Past 3 months data from Groww API
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import json

# Try to import groww_api - if not available, use yfinance as fallback
try:
    from groww_api import GrowwAPI
    GROWW_AVAILABLE = True
except ImportError:
    GROWW_AVAILABLE = False
    import yfinance as yf

# Configuration
SYMBOL = "GRASIM.NS"
STRATEGY = "FIBONACCI_RETRACEMENT"
BENCHMARK_WIN_RATE = 0.5736  # e.g., 0.9167 or None
CAPITAL = 100000  # ₹1,00,000 as per autotrade-v2 config
RISK_PER_TRADE = 0.02  # 2% risk per trade
MAX_POSITIONS = 1

# Strategy Parameters (optimized from benchmark)
PARAMS = {'fib_levels': [0.236, 0.382, 0.5, 0.618, 0.786]}

# Display helper - formats the benchmark win rate
if BENCHMARK_WIN_RATE:
    WIN_RATE_DISPLAY = str(BENCHMARK_WIN_RATE * 100) + "%"
else:
    WIN_RATE_DISPLAY = "N/A"

# Past 3 months date range
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=90)


def fetch_data(symbol: str, start_date: datetime, end_date: datetime) -> Optional[dict]:
    """Fetch OHLCV data using Groww API or yfinance fallback."""
    if GROWW_AVAILABLE:
        try:
            api = GrowwAPI()
            data = api.get_historical_data(
                symbol=symbol,
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                interval="1d"
            )
            return data
        except Exception as e:
            print(f"Groww API failed: {e}, falling back to yfinance")
    
    # Fallback to yfinance
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date.strftime("%Y-%m-%d"), 
                          end=end_date.strftime("%Y-%m-%d"))
        if df.empty:
            print(f"No data for {symbol}")
            return None
        
        # Convert to OHLCV dict format
        data = {
            "symbol": symbol,
            "ohlcv": [
                {
                    "date": str(idx.date()),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": int(row["Volume"])
                }
                for idx, row in df.iterrows()
            ]
        }
        return data
    except Exception as e:
        print(f"yfinance failed: {e}")
        return None


def calculate_vwap(ohlcv: List[dict], period: int = 14) -> List[float]:
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


def calculate_atr(ohlcv: List[dict], period: int = 14) -> List[float]:
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


def generate_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Generate trading signals based on strategy."""
    strategy = params.get("strategy", "VWAP")
    
    if strategy == "VWAP":
        return vwap_signals(ohlcv, params)
    elif strategy == "ADX_TREND":
        return adx_signals(ohlcv, params)
    elif strategy == "FIBONACCI_RETRACEMENT":
        return fibonacci_signals(ohlcv, params)
    elif strategy == "MOMENTUM_DIVERGENCE":
        return momentum_signals(ohlcv, params)
    elif strategy == "MA_ENVELOPE":
        return ma_envelope_signals(ohlcv, params)
    elif strategy == "TSI":
        return tsi_signals(ohlcv, params)
    elif strategy == "MACD_MOMENTUM":
        return macd_signals(ohlcv, params)
    elif strategy == "PARABOLIC_SAR":
        return parabolic_sar_signals(ohlcv, params)
    elif strategy == "VOLUME_DIVERGENCE":
        return volume_divergence_signals(ohlcv, params)
    else:
        return ["HOLD"] * len(ohlcv)


def vwap_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """VWAP Momentum Strategy - Trade when price crosses VWAP."""
    period = params.get("vwap_period", 14)
    atr_multiplier = params.get("atr_multiplier", 1.5)
    
    vwap = calculate_vwap(ohlcv, period)
    atr = calculate_atr(ohlcv, period)
    
    signals = ["HOLD"] * len(ohlcv)
    
    for i in range(period, len(ohlcv)):
        if vwap[i] is None or atr[i] is None:
            continue
        
        current_price = ohlcv[i]["close"]
        vwap_value = vwap[i]
        atr_value = atr[i]
        
        # Entry: Price crosses above VWAP with momentum
        if current_price > vwap_value + atr_value * atr_multiplier:
            signals[i] = "BUY"
        # Exit: Price crosses below VWAP
        elif current_price < vwap_value - atr_value * atr_multiplier:
            signals[i] = "SELL"
    
    return signals


def adx_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """ADX Trend Strategy - Trade with strong trends."""
    period = params.get("adx_period", 14)
    threshold = params.get("adx_threshold", 25)
    
    # Simplified ADX calculation
    signals = ["HOLD"] * len(ohlcv)
    
    for i in range(period * 2, len(ohlcv)):
        # Calculate directional movement
        plus_dm = max(0, ohlcv[i]["high"] - ohlcv[i-1]["high"])
        minus_dm = max(0, ohlcv[i-1]["low"] - ohlcv[i]["low"])
        
        # Simplified trend detection using price momentum
        price_change = ohlcv[i]["close"] - ohlcv[i-period]["close"]
        volatility = sum(abs(ohlcv[j]["close"] - ohlcv[j-1]["close"]) for j in range(i-period+1, i+1))
        
        if volatility > 0 and abs(price_change) / volatility > 0.5:
            if price_change > 0:
                signals[i] = "BUY"
            else:
                signals[i] = "SELL"
    
    return signals


def fibonacci_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Fibonacci Retracement Strategy."""
    signals = ["HOLD"] * len(ohlcv)
    fib_levels = params.get("fib_levels", [0.236, 0.382, 0.5, 0.618, 0.786])
    
    for i in range(50, len(ohlcv)):
        # Find recent swing high/low
        window = ohlcv[i-50:i+1]
        swing_high = max(bar["high"] for bar in window)
        swing_low = min(bar["low"] for bar in window)
        range_size = swing_high - swing_low
        
        if range_size == 0:
            continue
        
        current_price = ohlcv[i]["close"]
        
        # Check Fibonacci levels
        for fib in fib_levels:
            level = swing_high - (range_size * fib)
            if abs(current_price - level) / range_size < 0.02:  # Within 2% of level
                if current_price > level:  # Bounce from level
                    signals[i] = "BUY"
                    break
                elif current_price < level:  # Break through level
                    signals[i] = "SELL"
                    break
    
    return signals


def momentum_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Momentum Divergence Strategy."""
    rsi_period = params.get("rsi_period", 14)
    lookback = params.get("lookback", 20)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Calculate RSI
    rsi_values = []
    for i in range(len(ohlcv)):
        if i < rsi_period:
            rsi_values.append(50)
            continue
        
        gains = []
        losses = []
        for j in range(i - rsi_period, i):
            change = ohlcv[j+1]["close"] - ohlcv[j]["close"]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / rsi_period
        avg_loss = sum(losses) / rsi_period
        
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_values.append(rsi)
    
    # Generate signals based on RSI divergence
    for i in range(lookback, len(ohlcv)):
        current_rsi = rsi_values[i]
        prev_rsi = rsi_values[i-lookback]
        price_now = ohlcv[i]["close"]
        price_then = ohlcv[i-lookback]["close"]
        
        # Bullish divergence: price lower, RSI higher
        if price_now < price_then and current_rsi > prev_rsi:
            signals[i] = "BUY"
        # Bearish divergence: price higher, RSI lower
        elif price_now > price_then and current_rsi < prev_rsi:
            signals[i] = "SELL"
        # Overbought/Oversold
        elif current_rsi < 30:
            signals[i] = "BUY"  # Oversold - potential bounce
        elif current_rsi > 70:
            signals[i] = "SELL"  # Overbought - potential pullback
    
    return signals


def ma_envelope_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Moving Average Envelope Strategy."""
    ma_period = params.get("ma_period", 20)
    envelope_pct = params.get("envelope_pct", 3.0)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Calculate moving average
    for i in range(ma_period - 1, len(ohlcv)):
        ma = sum(ohlcv[j]["close"] for j in range(i - ma_period + 1, i + 1)) / ma_period
        upper = ma * (1 + envelope_pct / 100)
        lower = ma * (1 - envelope_pct / 100)
        
        current_price = ohlcv[i]["close"]
        
        if current_price < lower:
            signals[i] = "BUY"  # Price below lower band - oversold
        elif current_price > upper:
            signals[i] = "SELL"  # Price above upper band - overbought
    
    return signals


def tsi_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """True Strength Index Strategy."""
    fast = params.get("fast_period", 13)
    slow = params.get("slow_period", 25)
    signal = params.get("signal_period", 13)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Calculate momentum
    momentum = []
    for i in range(1, len(ohlcv)):
        mom = ohlcv[i]["close"] - ohlcv[i-1]["close"]
        momentum.append(mom)
    
    if len(momentum) < slow:
        return signals
    
    # Double smoothing (simplified TSI)
    fast_ema = momentum  # Simplified
    slow_ema = momentum  # Simplified
    
    for i in range(slow, len(ohlcv)):
        if i >= len(fast_ema) or i >= len(slow_ema):
            continue
        
        # Simplified signal
        if fast_ema[i] > slow_ema[i]:
            signals[i] = "BUY"
        elif fast_ema[i] < slow_ema[i]:
            signals[i] = "SELL"
    
    return signals


def macd_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """MACD Momentum Strategy."""
    fast = params.get("fast", 12)
    slow = params.get("slow", 26)
    signal_period = params.get("signal", 9)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Calculate EMAs
    closes = [bar["close"] for bar in ohlcv]
    
    def calc_ema(data, period):
        ema = [data[0]]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
        return ema
    
    fast_ema = calc_ema(closes, fast)
    slow_ema = calc_ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = calc_ema(macd_line, signal_period)
    
    for i in range(max(fast, slow, signal_period), len(ohlcv)):
        if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
            signals[i] = "BUY"
        elif macd_line[i] < signal_line[i] and macd_line[i-1] >= signal_line[i-1]:
            signals[i] = "SELL"
    
    return signals


def parabolic_sar_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Parabolic SAR Strategy."""
    af = params.get("af", 0.02)
    af_max = params.get("af_max", 0.2)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Simplified Parabolic SAR
    sar = ohlcv[0]["low"]
    trend = 1  # 1 for up, -1 for down
    ep = ohlcv[0]["high"]  # Extreme point
    acceleration = af
    
    for i in range(1, len(ohlcv)):
        sar_prev = sar
        ep_prev = ep
        
        # Update SAR
        sar = sar_prev + acceleration * (ep_prev - sar_prev)
        
        # Check for reversal
        if trend == 1:
            if ohlcv[i]["low"] < sar:
                trend = -1
                sar = ep
                ep = ohlcv[i]["low"]
                acceleration = af
            else:
                if ohlcv[i]["high"] > ep:
                    ep = ohlcv[i]["high"]
                    acceleration = min(acceleration + af, af_max)
        else:
            if ohlcv[i]["high"] > sar:
                trend = 1
                sar = ep
                ep = ohlcv[i]["high"]
                acceleration = af
            else:
                if ohlcv[i]["low"] < ep:
                    ep = ohlcv[i]["low"]
                    acceleration = min(acceleration + af, af_max)
        
        # Generate signal
        if trend == 1 and ohlcv[i]["close"] > sar:
            signals[i] = "BUY"
        elif trend == -1 and ohlcv[i]["close"] < sar:
            signals[i] = "SELL"
    
    return signals


def volume_divergence_signals(ohlcv: List[dict], params: dict) -> List[str]:
    """Volume Divergence Strategy."""
    obv_lookback = params.get("obv_lookback", 20)
    price_lookback = params.get("price_lookback", 14)
    
    signals = ["HOLD"] * len(ohlcv)
    
    # Calculate OBV
    obv = [0]
    for i in range(1, len(ohlcv)):
        if ohlcv[i]["close"] > ohlcv[i-1]["close"]:
            obv.append(obv[-1] + ohlcv[i]["volume"])
        elif ohlcv[i]["close"] < ohlcv[i-1]["close"]:
            obv.append(obv[-1] - ohlcv[i]["volume"])
        else:
            obv.append(obv[-1])
    
    # Generate signals
    for i in range(obv_lookback, len(ohlcv)):
        price_change = ohlcv[i]["close"] - ohlcv[i-price_lookback]["close"]
        obv_change = obv[i] - obv[i-obv_lookback]
        
        # Bullish divergence
        if price_change < 0 and obv_change > 0:
            signals[i] = "BUY"
        # Bearish divergence
        elif price_change > 0 and obv_change < 0:
            signals[i] = "SELL"
    
    return signals


def calculate_position_size(entry_price: float, stop_loss: float, capital: float) -> int:
    """Calculate position size based on risk management."""
    risk_amount = capital * RISK_PER_TRADE
    risk_per_share = abs(entry_price - stop_loss)
    
    if risk_per_share > 0:
        position_size = int(risk_amount / risk_per_share)
    else:
        position_size = 0
    
    # Maximum position size
    max_position = int(capital * 0.1 / entry_price)  # Max 10% of capital
    
    return min(position_size, max_position)


def run_backtest(ohlcv: List[dict], signals: List[str]) -> dict:
    """Run backtest on the strategy."""
    capital = CAPITAL
    position = 0
    entry_price = 0
    trades = []
    wins = 0
    losses = 0
    
    for i in range(len(ohlcv)):
        signal = signals[i]
        current_price = ohlcv[i]["close"]
        
        if signal == "BUY" and position == 0:
            # Enter position
            position = calculate_position_size(current_price, current_price * 0.98, capital)
            if position > 0:
                entry_price = current_price
                capital -= position * entry_price
        
        elif signal == "SELL" and position > 0:
            # Exit position
            pnl = (current_price - entry_price) * position
            capital += position * current_price
            
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            
            trades.append({"entry": entry_price, "exit": current_price, "pnl": pnl})
            position = 0
            entry_price = 0
    
    # Close any open position at the end
    if position > 0:
        final_price = ohlcv[-1]["close"]
        pnl = (final_price - entry_price) * position
        capital += position * final_price
        if pnl > 0:
            wins += 1
        else:
            losses += 1
        trades.append({"entry": entry_price, "exit": final_price, "pnl": pnl})
    
    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0
    
    return {
        "initial_capital": CAPITAL,
        "final_capital": capital,
        "total_return": (capital - CAPITAL) / CAPITAL * 100,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate * 100,
        "trades": trades
    }


def main():
    """Main execution function."""
    print("=" * 60)
    print(f"{STRATEGY} Strategy - {SYMBOL}")
    print(f"Win Rate from Benchmark: {WIN_RATE_DISPLAY}")
    print("=" * 60)
    
    # Fetch data
    print(f"\nFetching past 3 months data for {SYMBOL}...")
    data = fetch_data(SYMBOL, START_DATE, END_DATE)
    
    if not data or not data.get("ohlcv"):
        print("Failed to fetch data. Exiting.")
        return
    
    ohlcv = data["ohlcv"]
    print(f"Retrieved {len(ohlcv)} days of data")
    
    # Generate signals
    print(f"Generating {STRATEGY} signals...")
    params = dict(PARAMS)
    params["strategy"] = STRATEGY
    signals = generate_signals(ohlcv, params)
    
    # Run backtest
    print("Running backtest...")
    results = run_backtest(ohlcv, signals)
    
    # Print results
    print(f"\n============================================================")
    print("BACKTEST RESULTS")
    print(f"============================================================")
    print(f"Initial Capital: ₹{results['initial_capital']:,.0f}")
    print(f"Final Capital: ₹{results['final_capital']:,.0f}")
    print(f"Total Return: {results['total_return']:.2f}%")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Wins: {results['wins']} | Losses: {results['losses']}")
    print(f"Win Rate: {results['win_rate']:.2f}%")
    print(f"============================================================")
    
    # Save results
    output_file = f"{SYMBOL.replace('.', '_')}_results.json"
    with open(output_file, 'w') as f:
        json.dump({
            "symbol": SYMBOL,
            "strategy": STRATEGY,
            "benchmark_win_rate": 0.5736,
            "backtest_results": results
        }, f, indent=2)
    
    print(f"\nResults saved to {output_file}")
    
    # Print recent signals for live trading
    print(f"\nRECENT SIGNALS (last 5 days):")
    for i in range(max(0, len(ohlcv) - 5), len(ohlcv)):
        date = ohlcv[i]["date"]
        close = ohlcv[i]["close"]
        signal = signals[i]
        print(f"  {date}: ₹{close:.2f} - {signal}")


if __name__ == "__main__":
    main()
