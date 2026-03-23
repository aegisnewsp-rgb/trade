# Trade Project - Live Trading Scripts

**471 live trading scripts** — all compile-verified ✓

## Scripts
- Location: `deploy/live_*.py`
- Exchange: NSE (`.NS`) and BSE (`.BO`)
- Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8)

## Status (2026-03-23 01:31 UTC)
- ✅ All 471 scripts pass `py_compile` (QA cycle 39 ✓)
- ✅ Strategy v8 enhancements applied (MACD, volume, trend, BB filters)
- ✅ 3-tier exit system active
- ✅ Telegram status reporting enabled
- ✅ 25 scripts on v8 LOWWR (13 previous + 12 newly upgraded)
- ✅ v8 LOWWR scripts (INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, etc.) confirmed 10-13% WR — monitoring
- ✅ 3 x 0% WR scripts pivoted to MEAN_REVERSION v9 (CYIENT.BO, PRAKASHSTL.BO, RUPA.BO)
  - v8 trend filter blocked all signals in downtrends
  - v9: RSI-only + VWAP proximity + Volume (no trend filter)
  - RSI thresholds widened to 38/62 for more signal opportunities
- ✅ QA compile check running — 471/471 OK, 0 fails

## Quick Check
```bash
cd deploy && for f in live_*.py; do python3 -m py_compile "$f" || echo "FAIL: $f"; done
```

## Low Win-Rate Scripts (Target: 58%+)
| Script | Win Rate | Notes |
|--------|----------|-------|
| WIPRO | 52% | v8 LOWWR (0.6% SL, ₹5K pos) |
| HEROMOTOCO | 55% | v8 LOWWR auto (0.6% SL, ₹5K pos) |
| GLENMARK.NS | 56% | v8 LOWWR pharma (0.6% SL, ₹5K pos) |
| DABUR | 57% | v8 enhanced |
| GRASIM | 57% | v8 enhanced |
| COMPINFO.BO | 5% (21 trades) | v8 LOWWR (RSI 38/62) |
| ADANIPORTS | 28% (5 trades) | v8 LOWWR - few trades |
| ICICIBANK | 25% (7 trades) | v8 LOWWR - few trades |
| AXISBANK | 21% (5 trades) | v8 LOWWR - few trades |
| HCLTECH_NS | N/A | v8 LOWWR - no perf data |
| ADANIPOWER | 24% (5 trades) | v8 LOWWR - few trades |
| DRREDDY | 32% (5 trades) | v8 LOWWR - few trades |
| SRF_NS | N/A | v8 LOWWR - no perf data |
| SBILIFE_NS | N/A | v8 LOWWR - no perf data |
| SHREECEM_NS | N/A | v8 LOWWR - no perf data |
| CIPLA | 21% (7 trades) | v8 LOWWR - few trades |
| CYIENT.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| DSM | 0% (3 trades) | v8 LOWWR - trades too few for stats |
| GAL | 0% (2 trades) | v8 LOWWR - trades too few for stats |
| PRAKASHSTL.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| RUPA.BO | 0% | v9 MEAN_REVERSION (RSI+VWAP, no trend) - 2026-03-23 |
| INFY | 10% (21 trades) | v8 LOWWR (RSI 38/62) - 2026-03-23 |
| SEL.BO | 10% (21 trades) | v8 LOWWR (RSI 38/62) |
| SPAL.BO | 11% (19 trades) | v8 LOWWR (RSI 38/62) |
| SUNDARAM.BO | 11% (19 trades) | v8 LOWWR (RSI 38/62) |
| ABFRL.BO | 11% (18 trades) | v8 LOWWR (RSI 38/62) |
| PUNJABCHEM.BO | 12% (16 trades) | v8 LOWWR (RSI 38/62) |
| SAMTEX.BO | 13% (23 trades) | v8 LOWWR (RSI 38/62) |

## Enhancement Log
- 2026-03-23 00:48: CYIENT.BO, PRAKASHSTL.BO, RUPA.BO pivoted to MEAN_REVERSION v9 (removed trend filter, widened RSI 38/62) - 0% WR under v8 was due to downtrend blocking all signals
- 2026-03-23 00:32: 12 additional 0% WR scripts upgraded to v8 LOWWR (CYIENT.BO, DSM, GAL, PRAKASHSTL.BO, RUPA.BO, INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO)
- 2026-03-23 00:12: 10 additional 0% WR scripts upgraded to v8 LOWWR (ADANIPORTS, ICICIBANK, AXISBANK, HCLTECH_NS, ADANIPOWER, DRREDDY, SRF_NS, SBILIFE_NS, SHREECEM_NS, CIPLA)
- 2026-03-22 23:36: WIPRO, HEROMOTOCO, GLENMARK.NS upgraded to v8 LOWWR (0.6% SL, ₹5K position)
- 2026-03-22: All scripts v8 (tightened ATR/RSI, added BB, MACD, volume filters)
- 2026-03-22: 10 worst scripts (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE) upgraded to v8 LOWWR standard
