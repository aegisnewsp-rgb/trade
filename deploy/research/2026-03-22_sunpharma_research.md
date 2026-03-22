# NSE Stock Research — Sun Pharmaceutical (SUNPHARMA.NS)
**Research Date:** 2026-03-22 17:47 UTC
**Status:** NOT in deploy/ — creating live_SUNPHARMA.py

---

## Company Overview

| Field | Value |
|-------|-------|
| **NSE Symbol** | SUNPHARMA |
| **Full Name** | Sun Pharmaceutical Industries Ltd |
| **Sector** | Pharmaceuticals |
| **Market Cap** | ₹4.35 Trillion |
| **CMP** | ₹1,771 (Mar 20, 2026) |
| **52w High** | ₹1,855.35 |
| **52w Low** | ₹1,244.20 |
| **P/E Ratio** | 38.5x |
| **Avg Volume** | ~2.1M |

---

## Fundamentals (Approximate)

| Metric | Value |
|--------|-------|
| Revenue (FY25E) | ₹56,000 Cr |
| EBITDA Margin | 24-26% |
| ROE | 17-18% |
| EPS | ₹46-48 |
| Dividend Yield | 0.7% |

---

## Why This Stock

1. **Momentum Candidate:** +1.50% on Mar 20, volume ratio 1.41x confirming the move
2. **Defensive Sector:** Pharma holds up well in broader market pullback (~13% below Nifty 52w high)
3. **Global Specialty Pharma:** Sun Pharma is the largest Indian pharma company globally — USFDA-approved facilities, diversified portfolio
4. **Not yet deployed:** No live_SUNPHARMA.py in deploy/ folder
5. **Resilient in volatile markets:** Q3 FY2025 showed stable domestic formulation business

---

## Recent News / Catalysts

- Q3 FY2025: Revenue ₹14,500 Cr (+9% Y/Y), EBITDA margins stable
- USFDA facility inspections passing — no major import alerts
- Specialty pharma push (Lenalidomide / absorterene approvals) adding to growth pipeline
- INR depreciation benefits export revenue

---

## Strategy

**VWAP Momentum** (same pattern as existing IT/Pharma scripts)
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
| Target | 4.0x ATR |
| Daily Loss Cap | 0.3% of capital |

---

## Key Levels (Mar 20 Close)

| Level | Price |
|-------|-------|
| Entry | ₹1,771 |
| Resistance | ₹1,800 → ₹1,855 (52w high) |
| Support | ₹1,750 → ₹1,650 |
| Stop Loss | ₹1,755 (~0.9% below entry) |
| Target | ₹1,830-1,850 range |

---

## Risks

- USFDA regulatory risk (warning letters can hit supply)
- Rupee appreciation could hurt export revenues
- High P/E (38.5x) means limited room for earnings miss
- Pharma sector facing pricing pressure in US generics

---

## Sources

- NSE India, Moneycontrol, Economic Times Market
- NSE scan data: research_20260322_172800.md

---
*Not financial advice. DYOR.*
