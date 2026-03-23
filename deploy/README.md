# Deploy - Live Trading Scripts

## Overview
This directory contains live trading scripts (`live_*.py`) for automated trade execution.

**⚠️ NOTE:** The `live_*.py` files are gitignored (too many for GitHub). They are local-only.

## Scripts
- **471 live trading scripts** covering various NSE/BSE stocks
- Each script implements a specific strategy (TSI, VWAP, ADX_TREND, etc.)
- Scripts run during market hours (9:30 AM - 3:30 PM IST)

## QA Status
- **Last checked: 2026-03-23 01:12 UTC
- **All 471 scripts:** ✅ PASS (syntax validation)
- **Iteration:** #21
- **New v8 LOWWR upgrades:** HDFCBANK (60.61%), IGL (60.2%), TATASTEEL (61.54%), KOTAKBANK (N/A), COALINDIA (Target 65%+)
- **Bug fix:** IGL - fixed YFINANCE_AVAILABLE chained assignment bug (was overwriting boolean with Path)
- **Loop status:** Running (qa_loop_forever.py, 7-min cycles; qa_loop.py, 30-min cycles)
- **Working tree:** Dirty (2 files modified: live_HDFCBANK.py, live_IGL.py)

## Regime-Filter Enhancements (Iteration #14)
Scripts with 0% WR in DOWNTREND/RANGE regime enhanced with NIFTY-based regime filtering:
- **live_ICICIBANK.py** (0% WR in DOWNTREND): Added NIFTY regime detection. BUY blocked in DOWNTREND, 50% size in RANGE
- **live_SBILIFE_NS.py** (0% WR in DOWNTREND): Complete rewrite with regime-filtered VWAP+RSI. BUY blocked in DOWNTREND
- **live_DRREDDY.py** (0% WR in RANGE): Added NIFTY regime detection. 50% size in RANGE, BUY blocked in DOWNTREND

**Regime filter mechanism:**
- Detects NIFTY SMA ratio (current vs 20-day SMA)
- UPTREND (ratio > 1.02): full position size
- RANGE (0.98-1.02): 50% position size
- DOWNTREND (ratio < 0.98): 0% position size (BUY signals blocked)

## 0% WR Enhancements (Iteration #16)
Scripts with 0% win rate (12+ trades) converted to MEAN_REVERSION mode:
- **live_CYIENT.BO.py** (0% WR, 12 trades): Changed from VWAP to MEAN_REVERSION. RSI oversold (<35) + lower BB + volume confirm = BUY

**MEAN_REVERSION approach:**
- BUY: RSI <= 35 AND price <= lower Bollinger Band AND volume > 1.2x 20-day MA
- SELL: RSI >= 65 AND price >= upper Bollinger Band AND volume > 1.2x 20-day MA
- Tighter stop loss (0.8%) and target (3.0x) for mean reversion style

## Low-WR Enhancements (Iteration #13)
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

## v8 LOWWR Enhancements (Iteration #19 - 2026-03-23)
Basic low win-rate scripts upgraded to v8 multi-filter standard:
- **live_MARUTI_NS.py** (low base) -> v8 multi-filter upgrade
- **live_HINDPETRO_NS.py** (low base) -> v8 multi-filter upgrade
- **live_NESTLEIND_NS.py** (low base) -> v8 multi-filter upgrade
- **live_POWERGRID_NS.py** (low base) -> v8 multi-filter upgrade

**v8 multi-filter strategy:**
- VWAP + RSI(14,32/68) + MACD(12,26,9) + Volume(2x MA) + Trend(50-MA) + Bollinger Band(20,2.0)
- 3-TIER EXIT SYSTEM: 1.5x/3.0x/5.0x risk targets
- STOP_LOSS_PCT: 0.6% | TARGET_MULT: 4.0x

## Enhancement Notes
Low win-rate scripts (benchmark, all below 70%):
• ADANIENT.NS: 57.69% → ✅ v8 LOWWR upgrade (2026-03-23)
• TECHM.NS: 58.00% → ✅ v8 LOWWR upgrade (2026-03-23)
• BPCL.NS: 57.50% → ✅ v8 LOWWR upgrade (2026-03-23)
• CHOLAFIN.NS: 57.49% → ✅ v8 LOWWR upgrade (2026-03-23)
• SHREECEM_NS.NS: 58.06% → ✅ v8 LOWWR (already upgraded)
• POWERGRID_NS.NS: 58.82% → ✅ v8 LOWWR (already upgraded)
• MARUTI_NS.NS: 59.26% → ✅ v8 LOWWR (already upgraded)
• HINDPETRO_NS.NS: 59.38% → ✅ v8 LOWWR (already upgraded)
• SBILIFE_NS.NS: 59.44% → ✅ v8 LOWWR (already upgraded)
• NESTLEIND_NS.NS: 59.93% → ✅ v8 LOWWR (already upgraded)
• HDFCBANK.NS: 60.61% → ✅ v8 LOWWR upgrade (2026-03-23)
• IGL.NS: 60.2% → ✅ v8 LOWWR upgrade (2026-03-23) + bug fix
• TATASTEEL.NS: 61.54% → ✅ v8 LOWWR upgrade (2026-03-23) [NEW]
• CIPLA.NS: 60.07%
• SRF_NS.NS: 60.13%

Target: 70%+ win rate for all scripts
Note: Low win-rate scripts already use multi-filter confirmation (RSI, volume, volatility, trend). Improvements require careful backtesting beyond syntax fixes.
