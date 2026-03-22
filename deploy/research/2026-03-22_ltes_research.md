# NSE Stock Research — L&T Technology Services (LTES.NS)
**Research Date:** 2026-03-22 18:00 UTC
**Status:** NOT in deploy/ — creating live_LTES.py

---

## Company Overview

| Field | Value |
|-------|-------|
| **NSE Symbol** | LTES.NS |
| **Full Name** | L&T Technology Services Ltd |
| **Sector** | IT Services / Engineering R&D |
| **Market Cap** | ~₹55,000 Cr |
| **CMP** | ~₹5,200-5,300 (Mar 20, 2026) |
| **52w High** | ~₹6,200 |
| **52w Low** | ~₹4,200 |

---

## Why This Stock

1. **IT Sector Momentum:** Nifty IT surged **+2.17%** on Mar 20 — strongest sector of the day. IT momentum continues into next week.
2. **ER&D Focus:** L&T Tech is a pure-play Engineering R&D services company — differentiates from generic IT exporters.
3. **Not yet deployed:** No live_LTES.py in deploy/ folder (verified).
4. **Mid-cap IT with volume:** Good liquidity for ₹7,000 position sizing.
5. **Government/Industrial tailwinds:** L&T group parentage provides stability and cross-selling opportunities in engineering services.

---

## Strategy: VWAP Momentum

Same proven VWAP strategy used across IT scripts (INFY, TCS, TECHM, HCLTECH, TATAELXSI).
- vwap_period: 14
- atr_period: 14
- atr_multiplier: 1.5
- rsi_period: 14
- rsi_overbought: 65 / rsi_oversold: 35

**Signal Rules:**
- BUY: price > VWAP + ATR band AND RSI < overbought threshold
- SELL: price < VWAP - ATR band AND RSI > oversold threshold

---

## Risk Parameters

| Parameter | Value |
|-----------|-------|
| Position Size | ₹7,000 |
| Stop Loss | 0.8% ATR |
| Target | 4.0× ATR |
| Daily Loss Cap | 0.3% of capital |

---

## Key Levels (Approximate — Mar 20)

| Level | Price |
|-------|-------|
| Entry | ~₹5,250 |
| Resistance | ₹5,500 → ₹5,800 |
| Support | ₹5,100 → ₹4,900 |
| Stop Loss | ~₹5,210 (~0.8% below entry) |

---

## Risks

- IT sector volatile to currency (INR/USD) moves
- Smaller mid-cap vs large-cap IT names — wider spreads
- Q3 FY2025 results to be monitored
- US economic slowdown could impact ER&D budgets

---

## Sources

- NSE India, Moneycontrol, Economic Times Market
- IT sector momentum thesis: Nifty IT +2.17% on Mar 20, 2026
- Existing IT live scripts: live_INFY.py, live_TCS.py, live_TECHM.py, live_HCLTECH_NS.py

---
*Not financial advice. DYOR. Validate with live market data before trading.*
