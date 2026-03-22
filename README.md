# Trade Project - Live Trading Scripts

**471 live trading scripts** — all compile-verified ✓

## Scripts
- Location: `deploy/live_*.py`
- Exchange: NSE (`.NS`) and BSE (`.BO`)
- Strategy: VWAP + RSI + MACD + Volume + Trend + Bollinger Band (v8)

## Status (2026-03-22 23:31 UTC)
- ✅ All 471 scripts pass `py_compile`
- ✅ Strategy v8 enhancements applied (MACD, volume, trend, BB filters)
- ✅ 3-tier exit system active
- ✅ Telegram status reporting enabled
- ✅ 10 worst scripts upgraded to v8 LOWWR (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE)
- ✅ QA cycle complete — next cycle in 30min

## Quick Check
```bash
cd deploy && for f in live_*.py; do python3 -m py_compile "$f" || echo "FAIL: $f"; done
```

## Low Win-Rate Scripts (Target: 60%+)
| Script | Win Rate | Notes |
|--------|----------|-------|
| GLENMARK.NS | 56% | v8 enhanced |
| HEROMOTOCO | 55% | v8 enhanced |
| WIPRO | 52% | v8 enhanced |
| COMPINFO.BO | ~5% base | v8 LOWWR upgraded |
| SHIVALIK.BO | ~5% base | v8 LOWWR upgraded |
| AMTL.BO | ~6% base | v8 LOWWR upgraded |

## Enhancement Log
- 2026-03-22: All scripts v8 (tightened ATR/RSI, added BB, MACD, volume filters)
- 2026-03-22: 10 worst scripts (COMPINFO, SHIVALIK, AMTL, ALANKIT, COROMANDEL, PFL, SFL, PARACABLES, TBZ, ARISE) upgraded to v8 LOWWR standard
