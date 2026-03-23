# Trade Project - Live Trading Scripts

**471 live trading scripts** — all compile-verified ✓

## Scripts
- Location: `deploy/live_*.py`
- Exchange: NSE (`.NS`) and BSE (`.BO`)
- Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8)

## Status (2026-03-23 00:32 UTC)
- ✅ All 471 scripts pass `py_compile` (QA cycle 39 ✓)
- ✅ Strategy v8 enhancements applied (MACD, volume, trend, BB filters)
- ✅ 3-tier exit system active
- ✅ Telegram status reporting enabled
- ✅ 25 scripts on v8 LOWWR (13 previous + 12 newly upgraded)
- ✅ 12 new 0% WR scripts upgraded to v8 LOWWR: CYIENT.BO, DSM, GAL, PRAKASHSTL.BO, RUPA.BO, INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO
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
| COMPINFO.BO | ~5% base | v8 LOWWR upgraded |
| ADANIPORTS | 0% | v8 LOWWR upgraded (2026-03-23) |
| ICICIBANK | 0% | v8 LOWWR upgraded (2026-03-23) |
| AXISBANK | 0% | v8 LOWWR upgraded (2026-03-23) |
| HCLTECH_NS | 0% | v8 LOWWR upgraded (2026-03-23) |
| ADANIPOWER | 0% | v8 LOWWR upgraded (2026-03-23) |
| DRREDDY | 0% | v8 LOWWR upgraded (2026-03-23) |
| SRF_NS | 0% | v8 LOWWR upgraded (2026-03-23) |
| SBILIFE_NS | 0% | v8 LOWWR upgraded (2026-03-23) |
| SHREECEM_NS | 0% | v8 LOWWR upgraded (2026-03-23) |
| CIPLA | 0% | v8 LOWWR upgraded (2026-03-23) |
| CYIENT.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| DSM | 0% | v8 LOWWR upgraded (2026-03-23) |
| GAL | 0% | v8 LOWWR upgraded (2026-03-23) |
| PRAKASHSTL.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| RUPA.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| INFY | 0% | v8 LOWWR upgraded (2026-03-23) |
| SEL.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| SPAL.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| SUNDARAM.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| ABFRL.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| PUNJABCHEM.BO | 0% | v8 LOWWR upgraded (2026-03-23) |
| SAMTEX.BO | 0% | v8 LOWWR upgraded (2026-03-23) |

## Enhancement Log
- 2026-03-23 00:32: 12 additional 0% WR scripts upgraded to v8 LOWWR (CYIENT.BO, DSM, GAL, PRAKASHSTL.BO, RUPA.BO, INFY, SEL.BO, SPAL.BO, SUNDARAM.BO, ABFRL.BO, PUNJABCHEM.BO, SAMTEX.BO)
- 2026-03-23 00:12: 10 additional 0% WR scripts upgraded to v8 LOWWR (ADANIPORTS, ICICIBANK, AXISBANK, HCLTECH_NS, ADANIPOWER, DRREDDY, SRF_NS, SBILIFE_NS, SHREECEM_NS, CIPLA)
- 2026-03-22 23:36: WIPRO, HEROMOTOCO, GLENMARK.NS upgraded to v8 LOWWR (0.6% SL, ₹5K position)
- 2026-03-22: All scripts v8 (tightened ATR/RSI, added BB, MACD, volume filters)
- 2026-03-22: 10 worst scripts (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE) upgraded to v8 LOWWR standard
