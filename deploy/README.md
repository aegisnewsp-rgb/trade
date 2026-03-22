# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (`live_*.py`) for automated trade execution.

**⚠️ NOTE:** The `live_*.py` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **371 live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked:** 2026-03-22 20:28 UTC
- **All 371 scripts:** ✅ Compiled successfully (py_compile)
- **Syntax:** All clean, no errors

## Script Structure
Each `live_*.py` script includes:
- Strategy name and parameters
- Position sizing (₹7000 default)
- Daily loss cap (0.3%)
- Smart entry filters (RSI, volume, VWAP)
- Dynamic ATR stop losses
- 3-tier target management
- Market regime detection (NIFTY correlation)

## Enhancement Notes
Low win-rate scripts (benchmark data from manifest):
- ICICIBANK.NS: 57.30% (ADX_TREND)
- DABUR.NS: 57.32% (ADX_TREND)
- GRASIM.NS: 57.36% (FIBONACCI_RETRACEMENT)
- CHOLAFIN.NS: 57.49% (FIBONACCI_RETRACEMENT)
- BPCL.NS: 57.50% (VWAP)

Target: 70%+ win rate for all scripts

## Logs
Trading logs stored in `logs/` directory (gitignored).

## Running
```bash
cd deploy
python3 live_<SYMBOL>.py
```
