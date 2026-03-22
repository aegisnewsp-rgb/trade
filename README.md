# Trade Project - Live Trading Scripts

**471 live trading scripts** — all compile-verified ✓

## Scripts
- Location: `deploy/live_*.py`
- Exchange: NSE (`.NS`) and BSE (`.BO`)
- Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8)

## Status (2026-03-22 23:48 UTC)
- ✅ All 471 scripts pass `py_compile`
- ✅ Strategy v8 enhancements applied (MACD, volume, trend, BB filters)
- ✅ 3-tier exit system active
- ✅ Telegram status reporting enabled
- ✅ 13 scripts now on v8 LOWWR (WIPRO, HEROMOTOCO, GLENMARK + 10 original)
- ✅ 3 lowest win-rate scripts upgraded: WIPRO/HEROMOTOCO/GLENMARK -> v8 LOWWR
- ✅ QA cycle running — compile check every 5 min (471 checked, 0 fails)

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

## Enhancement Log
- 2026-03-22 23:36: WIPRO, HEROMOTOCO, GLENMARK.NS upgraded to v8 LOWWR (0.6% SL, ₹5K position)
- 2026-03-22: All scripts v8 (tightened ATR/RSI, added BB, MACD, volume filters)
- 2026-03-22: 10 worst scripts (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE) upgraded to v8 LOWWR standard
