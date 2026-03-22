# Live Trading Scripts - Groww Platform

Production-ready deployable trading scripts for the Groww platform.

## Overview

This directory contains 5 standalone Python scripts for live trading on Groww. Each script implements a specific strategy derived from backtesting analysis of 65 stock trading scripts.

## Scripts

| Script | Stock | Strategy | Win Rate | 
|--------|-------|----------|----------|
| `live_RELIANCE.py` | RELIANCE.NS | TSI (True Strength Index) | 63.64% |
| `live_TCS.py` | TCS.NS | VWAP | 63.64% |
| `live_SBIN.py` | SBIN.NS | VWAP | 63.64% |
| `live_TITAN.py` | TITAN.NS | VWAP | 61.11% |
| `live_HDFCBANK.py` | HDFCBANK.NS | ADX_TREND | 60.61% |

## Risk Management

All scripts implement the following risk management rules:

- **Daily Loss Cap**: 0.3% of capital (₹300 on ₹100,000 capital)
- **Max Trades Per Day**: 1 trade per script
- **Position Size**: ₹7,000 per trade
- **Stop Loss**: 0.8% ATR-based
- **Target**: 4.0x ATR-based

## Requirements

```
pip install yfinance requests
```

## Environment Variables

For live order execution, set these environment variables:

```bash
export GROWW_API_KEY="your_api_key"
export GROWW_API_SECRET="your_api_secret"
```

**Note**: If API credentials are not set, the script will generate signals and log them but will NOT place real orders.

## Running the Scripts

### Basic Usage

```bash
python3 live_RELIANCE.py
python3 live_TCS.py
python3 live_SBIN.py
python3 live_TITAN.py
python3 live_HDFCBANK.py
```

### Schedule for 9 AM Execution

Using cron (add to crontab):

```bash
# Market open check happens automatically
# Run at 9:00 AM every trading day
0 9 * * 1-5 cd /home/node/workspace/trade-project/deploy && python3 live_RELIANCE.py >> /var/log/trading_RELIANCE.log 2>&1
0 9 * * 1-5 cd /home/node/workspace/trade-project/deploy && python3 live_TCS.py >> /var/log/trading_TCS.log 2>&1
0 9 * * 1-5 cd /home/node/workspace/trade-project/deploy && python3 live_SBIN.py >> /var/log/trading_SBIN.log 2>&1
0 9 * * 1-5 cd /home/node/workspace/trade-project/deploy && python3 live_TITAN.py >> /var/log/trading_TITAN.log 2>&1
0 9 * * 1-5 cd /home/node/workspace/trade-project/deploy && python3 live_HDFCBANK.py >> /var/log/trading_HDFCBANK.log 2>&1
```

## Output

Each script generates:

1. **Console Output**: Real-time logging of signal generation and trade execution
2. **Log File**: `logs/live_<STOCK>_<DATE>.log` - Daily log file
3. **State File**: `state_<STOCK>.json` - Persists trading state between runs

## Sample Output

```
============================================================
LIVE TRADING - RELIANCE.NS | TSI
Win Rate: 63.64%
Position Size: ₹7,000
Stop Loss: 0.8% ATR
Target: 4.0x ATR
============================================================
State loaded: 0 trades today
Pre-market warmup: Fetching data...
Fetched 90 days of data for RELIANCE.NS
Current Price: ₹2,850.00
Current ATR: ₹25.50
Current TSI: 45.23
Signal Line: 42.15
GENERATED SIGNAL: BUY
🟢 BUY SIGNAL: ₹2,850.00
   Quantity: 2 | Position: ₹5,700.00
   Stop Loss: ₹2,829.60 | Target: ₹2,952.00
   (No API credentials - order not placed)
============================================================
Script completed successfully
```

## Strategy Details

### TSI (True Strength Index) - RELIANCE
- Fast Period: 13
- Slow Period: 25
- Signal Period: 13
- BUY when TSI crosses above signal line
- SELL when TSI crosses below signal line

### VWAP (Volume Weighted Average Price) - TCS, SBIN, TITAN
- VWAP Period: 14
- ATR Period: 14
- ATR Multiplier: 1.5
- BUY when price > VWAP + (ATR × 1.5)
- SELL when price < VWAP - (ATR × 1.5)

### ADX_TREND (Average Directional Index) - HDFCBANK
- ADX Period: 14
- ADX Threshold: 25
- ATR Period: 14
- BUY when ADX > 25 and +DI > -DI
- SELL when ADX > 25 and -DI > +DI
- HOLD when ADX < 25 (no clear trend)

## State Management

Each script maintains state in `state_<STOCK>.json`:

```json
{
  "trades_today": 0,
  "last_trade_date": "2026-03-22",
  "daily_pnl": 0,
  "daily_loss": 0,
  "position": null,
  "last_signal": "BUY"
}
```

State is reset automatically at midnight for new trading days.

## Important Notes

1. **⚠️ Paper Trading First**: Always test with paper trading before live execution
2. **Market Hours**: Scripts check for NSE market open (9:15 AM - 3:30 PM IST)
3. **Graceful Degradation**: Scripts work without API credentials (signal logging only)
4. **Retry Logic**: Built-in error handling with retry capability
5. **Logging**: All actions are logged to both file and console

## Disclaimer

These scripts are for educational and paper trading purposes. Trading stocks involves risk. Past performance does not guarantee future results. Use at your own risk.
