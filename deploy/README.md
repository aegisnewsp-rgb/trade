# Live Trading Scripts

Automated trading scripts for Indian stocks using Groww API.

## Scripts

- `live_*.py` - Individual stock trading scripts
- All scripts use yfinance for data and can connect to Groww API for live trading

## Strategy Types

- **VWAP_RSI_MACD_VOL** - VWAP + RSI + MACD + Volume + Trend filter
- **MA_ENVELOPE** - Moving Average envelope strategy
- **ADX_TREND** - ADX-based trend following
- **TSI** - True Strength Index
- **Bollinger** - Bollinger Bands
- **RSI** - RSI-based mean reversion

## Usage

```bash
cd deploy
python3 live_RELIANCE.py
```

## Requirements

- python3
- yfinance
- requests

## Notes

- Scripts include paper trading fallback when Groww API is not configured
- Win rates are based on historical backtesting
- Target win rates assume proper market conditions
