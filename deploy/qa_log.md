# QA Log

## 2026-03-22

### 23:12 UTC - Cycle Start
- **Syntax check:** 391 live_*.py scripts checked
- **Result:** ✅ ALL PASS
- **Win rate analysis:**
  - Bottom performers: CYIENT.BO (0%), DSM (0%), GAL (0%), PRAKASHSTL.BO (0%), RUPA.BO (0%), SHYAM.BO (0%)
  - These are already flagged in README and subject to ongoing enhancement iterations
- **Git status:** Clean (no changes)
- **Next cycle:** 60 seconds


### 23:13 UTC - Cycle 2
- **Syntax check:** 391 live_*.py scripts ✅ ALL PASS
- **Git:** Clean
23:14 UTC - All 471 scripts pass

## 2026-03-23 - Cycle #21 (01:12 UTC)
### Syntax check: 471 live_*.py scripts ✅ ALL PASS
### Enhancements:
- **live_HDFCBANK.py**: 60.61% WR → v8 LOWWR (VWAP+RSI+MACD+BB+Trend multi-filter, 3-TIER EXIT, NIFTY BANK sector)
  - Note: Already upgraded in iter=210, re-confirmed
- **live_IGL.py**: 60.2% WR → v8 LOWWR (VWAP+RSI+MACD+BB+Trend, gas price correlation)
  - Bug fix: YFINANCE_AVAILABLE chained assignment bug (was `True_DIR = Path(...)`)
  - Gas price correlation: rising gas = favorable for IGL BUY signals
### Git: auto-commit iter=212 (IGL + README)
### README: Iteration #21 updated

### TATASTEEL Enhancement (01:19 UTC):
- **live_TATASTEEL.py**: 61.54% WR → v8 LOWWR (added Bollinger Band + 50-MA Trend filter to existing v7 steel logic)
  - Added calculate_ma() and calculate_bollinger_bands() functions
  - Updated vwap_enhanced_signal() to include BB and Trend MA filters
  - Updated PARAMS with trend_ma_period=50, bb_period=20, bb_std=2.0
  - Updated STRATEGY name to VWAP_RSI_MACD_VOL_BB_v8_LOWWR
  - v8: STOP_LOSS_PCT=0.006, TARGET_MULT=4.0 (steel keeps 0.8% ATR stop via STOP_LOSS_ATR_MULT)

### KOTAKBANK Enhancement (01:20 UTC):
- **live_KOTAKBANK.py**: N/A WR → v8 LOWWR (upgraded from basic VWAP_RSI_FILTER to full multi-filter)
  - Basic VWAP_RSI strategy (RSI 35/65, ATR-based stops) → v8 multi-filter (RSI 32/68 + MACD + BB + Trend MA)
  - Added STOP_LOSS_PCT=0.006, TARGET_MULT=4.0, 3-TIER EXIT
  - Added calculate_macd(), calculate_ma(), calculate_avg_volume(), calculate_bollinger_bands()
  - Rewrote vwap_signal() with full v8 multi-filter
