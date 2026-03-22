# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (`live_*.py`) for automated trade execution.

**⚠️ NOTE:** The `live_*.py` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **471 live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked:** 2026-03-22 21:23 UTC
- **All 471 scripts:** ✅ PASS
- **Iteration:** #8
- **Fixes applied:** 19 scripts with indentation/try-except syntax errors
  - 10 "unexpected indent" (CIPLA, EICHERMOT, GODREJPROP_NS, HINDPETRO_NS, MARUTI_NS, NESTLEIND_NS, POWERGRID_NS, SBILIFE_NS, SHREECEM_NS, SRF_NS)
  - 8 "unindent does not match" (ADANIENT, ALANKIT.BO, ALKEM, CENTRALBK, CHOLAFIN, DABUR, IDEA, SAGILITY, UCOBANK)
  - 1 "expected 'except' or 'finally'" (ALANKIT.BO)

## Enhancement Notes
Low win-rate scripts (benchmark, all below 70%):
• ADANIENT.NS: 57.69% (TSI + multi-filter)
• TECHM.NS: 58.00% (generic IT benchmark)
• SHREECEM_NS.NS: 58.06% (generic benchmark)
• POWERGRID_NS.NS: 58.82%
• MARUTI_NS.NS: 59.26%
• HINDPETRO_NS.NS: 59.38%
• SBILIFE_NS.NS: 59.44%
• NESTLEIND_NS.NS: 59.93%
• CIPLA.NS: 60.07%
• SRF_NS.NS: 60.13%

Target: 70%+ win rate for all scripts
Note: Low win-rate scripts already use multi-filter confirmation (RSI, volume, volatility, trend). Improvements require careful backtesting beyond syntax fixes.
