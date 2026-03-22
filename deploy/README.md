# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (`live_*.py`) for automated trade execution.

**⚠️ NOTE:** The `live_*.py` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **471 live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked:** 2026-03-22 22:09 UTC
- **All 471 scripts:** ✅ PASS (syntax validation)
- **Iteration:** #13

## Low-WR Enhancements (Iteration #13)
Scripts with <30% backtest WR enhanced with RSI + Volume filtering:
- live_NMDC.py: 12.5% WR → MEAN_REVERSION mode (SIGNAL_MODE=MEAN_REVERSION, SL=0.6%, TGT=2.5x, ATR=1.0)
- live_SAIL.py: 25% WR → added RSI filter (RSI>50 BUY, RSI<45 SELL) + volume confirmation (1.2x avg)

## MEAN_REVERSION Enhancements (Iteration #9)
Bottom 10 scripts with < 15% historical win rate enhanced with **MEAN_REVERSION** signal mode:
- live_COMPINFO.BO.py: 4.76% win rate → MEAN_REVERSION mode (was BREAKOUT)
- live_SHIVALIK.BO.py: 5.00% win rate → MEAN_REVERSION mode
- live_AMTL.BO.py: 5.56% win rate → MEAN_REVERSION mode
- live_ALANKIT.BO.py: 5.88% win rate → MEAN_REVERSION mode
- live_COROMANDEL.BO.py: 6.25% win rate → MEAN_REVERSION mode
- live_PATANJALI.py: 7.69% win rate → MEAN_REVERSION mode
- live_ATGL.NS.py: 9.09% win rate → MEAN_REVERSION mode
- live_INFY.py: 9.52% win rate → MEAN_REVERSION mode
- live_SEL.BO.py: 9.52% win rate → MEAN_REVERSION mode
- live_SPAL.BO.py: 10.53% win rate → MEAN_REVERSION mode

**Parameter changes:**
- SIGNAL_MODE: BREAKOUT → MEAN_REVERSION (inverted signals: BUY when oversold, SELL when overbought)
- STOP_LOSS_PCT: 0.008 → 0.006 (tighter stop loss)
- TARGET_MULT: 4.0 → 2.5 (lower target, more achievable)
- atr_multiplier: 1.5 → 1.0 (tighter VWAP bands)

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
