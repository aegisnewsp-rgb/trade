# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (`live_*.py`) for automated trade execution.

**⚠️ NOTE:** The `live_*.py` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **471 live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked:** 2026-03-22 20:40:00 UTC
- **All 471 scripts:** ✅ All compiled successfully
- **Iteration:** #3

## Enhancement Notes
Low win-rate scripts (benchmark data from manifest):
• ICICIBANK.NS: 57.30% (ADX_TREND) - Already enhanced with 3-TIER EXIT
• DABUR.NS: 57.32% (ADX_TREND) - Already enhanced with volume + trend filter
• GRASIM.NS: 57.36% (FIBONACCI_RETRACEMENT)
• CHOLAFIN.NS: 57.49% (FIBONACCI_RETRACEMENT)
• BPCL.NS: 57.50% (VWAP)

Target: 70%+ win rate for all scripts
