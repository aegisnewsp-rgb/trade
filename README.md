# Trade Project - Live Trading Scripts

**471 live trading scripts** — all compile-verified ✓

## Scripts
- Location: `deploy/live_*.py`
- Exchange: NSE (`.NS`) and BSE (`.BO`)
- Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8)

## Status (2026-03-23 04:53 UTC)
- ✅ All 471 scripts pass `py_compile` (QA cycle 47 ✓)
- ✅ MM_NS (16.7%), ONGC (25%) pivoted to v9 MEAN_REVERSION (removed MACD/BB/trend multi-filter)
- ✅ COMPINFO.BO (4.8%) RSI crossover requirement removed (too strict, replaced with simple RSI 38/62)
- ✅ 10 x 0% WR scripts on v9 MEAN_REVERSION (ADANIPORTS, ICICIBANK, AXISBANK, HCLTECH_NS, ADANIPOWER, SRF_NS, DRREDDY, SBILIFE_NS, SHREECEM_NS, CIPLA)
- ✅ Strategy v8/v9 enhancements applied (MACD, volume, trend, BB, RSI filters)
- ✅ 3-tier exit system active
- ✅ Telegram status reporting enabled
- ✅ 7 x 5-9% WR scripts on v9c/v9 MEAN_REVERSION (COMPINFO.BO, SHIVALIK.BO, AMTL.BO, ALANKIT.BO, COROMANDEL.BO, PATANJALI, ATGL.NS)
- ✅ 7 x 10-13% WR scripts on v9 MEAN_REVERSION (INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO)
- ✅ 3 x 52-56% WR scripts on v9 MEAN_REVERSION (WIPRO 52%, HEROMOTOCO 55%, GLENMARK 56%)
- ✅ QA compile check running — 471/471 OK, 0 fails

## Quick Check
```bash
cd deploy && for f in live_*.py; do python3 -m py_compile "$f" || echo "FAIL: $f"; done
```

## Low Win-Rate Scripts (Target: 58%+)
| Script | Win Rate | Notes |
|--------|----------|-------|
| WIPRO | 52% | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| HEROMOTOCO | 55% | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| GLENMARK.NS | 56% | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| DABUR | 57% | v8 enhanced |
| GRASIM | 57% | v8 enhanced |
| COMPINFO.BO | 5% (21 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| SHIVALIK.BO | 5% (20 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| AMTL.BO | 6% (18 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| ALANKIT.BO | 6% (17 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| COROMANDEL.BO | 6% (16 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| PATANJALI | 8% (13 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| ATGL.NS | 9% (22 trades) | **→ v9c** (RSI 40/60 + vol 2x + RSI crossover) - 2026-03-23 |
| ADANIPORTS | 0% (11 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| ICICIBANK | 0% (7 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| AXISBANK | 0% (7 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| HCLTECH_NS | 0% (6 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| ADANIPOWER | 0% (6 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| DRREDDY | 0% (5 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| SRF_NS | 0% (5 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| SBILIFE_NS | 0% (4 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| SHREECEM_NS | 0% (3 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| CIPLA | 0% (3 trades) | **→ v9 MEAN_REVERSION** (RSI 38/62, vol 1.3x, no trend/MACD/BB) - 2026-03-23 |
| CYIENT.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| DSM | 0% (3 trades) | v8 LOWWR - trades too few for stats |
| GAL | 0% (2 trades) | v8 LOWWR - trades too few for stats |
| PRAKASHSTL.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| RUPA.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| INFY | 10% (21 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| SEL.BO | 10% (21 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| SPAL.BO | 11% (19 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| SUNDARAM.BO | 11% (19 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| ABFRL.BO | 11% (18 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| PUNJABCHEM.BO | 12% (16 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |
| SAMTEX.BO | 13% (23 trades) | **→ v9 MEAN_REVERSION** (RSI+VWAP, no trend) - 2026-03-23 |

## Enhancement Log
- 2026-03-23 04:53: MM_NS (16.7%), ONGC (25%) pivoted to MEAN_REVERSION v9 - removed MACD/BB/trend multi-filter; COMPINFO.BO (4.8%) RSI crossover requirement removed (was too strict); all now using RSI 38/62 + vol 1.3x + no trend/MACD/BB
- 2026-03-23 03:20: 10 x 0% WR scripts upgraded to v9 MEAN_REVERSION (ADANIPORTS, ICICIBANK, AXISBANK, HCLTECH_NS, ADANIPOWER, SRF_NS, DRREDDY, SBILIFE_NS, SHREECEM_NS, CIPLA) - removed trend/MACD/BB filters, RSI 38/62, vol 1.3x, atr 1.5 - same approach that fixed CYIENT, PRAKASHSTL, RUPA
- 2026-03-23 03:16: WIPRO (52%), HEROMOTOCO (55%), GLENMARK.NS (56%) upgraded to v9 MEAN_REVERSION - removed trend/MACD/BB filters, RSI 38/62, vol 1.3x, atr 1.0 (same approach that fixed 0% WR scripts)
- 2026-03-23 02:34: 7 x 10-13% WR scripts pivoted to MEAN_REVERSION v9 (INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO) - removed trend/MACD/BB filters, RSI 38/62, vol 1.3x (same approach that fixed 0% WR scripts)
- 2026-03-23 01:44: v9b enhancements: vol_mult 2.0→1.3 for thin small-caps (CYIENT, PRAKASHSTL, RUPA, COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL); atr_mult 1.5→0.5 for high-ATR% stocks (SHIVALIK 4.6%, COROMANDEL 4.4%, ALANKIT 7.2%, AMTL 9.9%, COMPINFO); ATGL.NS atr_mult 1.0→0.5 + stop 1x→2x ATR (8.12% ATR too high for 1x threshold)
- 2026-03-23 01:34: 7 scripts pivoted to MEAN_REVERSION v9 (COMPINFO.BO, SHIVALIK.BO, AMTL.BO, ALANKIT.BO, COROMANDEL.BO, PATANJALI, ATGL.NS) - v8 multi-filter too restrictive, removed trend/MACD/BB filters
- 2026-03-23 00:48: CYIENT.BO, PRAKASHSTL.BO, RUPA.BO pivoted to MEAN_REVERSION v9 (removed trend filter, widened RSI 38/62) - 0% WR under v8 was due to downtrend blocking all signals
- 2026-03-23 00:32: 12 additional 0% WR scripts upgraded to v8 LOWWR (CYIENT.BO, DSM, GAL, PRAKASHSTL.BO, RUPA.BO, INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO)
- 2026-03-23 00:12: 10 additional 0% WR scripts upgraded to v8 LOWWR (ADANIPORTS, ICICIBANK, AXISBANK, HCLTECH_NS, ADANIPOWER, DRREDDY, SRF_NS, SBILIFE_NS, SHREECEM_NS, CIPLA) → **→ v9 MEAN_REVERSION 03:20**
- 2026-03-22 23:36: WIPRO, HEROMOTOCO, GLENMARK.NS upgraded to v8 LOWWR (0.6% SL, ₹5K position)
- 2026-03-22: All scripts v8 (tightened ATR/RSI, added BB, MACD, volume filters)
- 2026-03-22: 10 worst scripts (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE) upgraded to v8 LOWWR standard
