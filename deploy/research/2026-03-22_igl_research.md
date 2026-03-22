# NSE Stock Research — Indraprastha Gas Ltd (IGL.NS)
**Research Date:** 2026-03-22 17:40 UTC

---

## Company Overview

| Field | Value |
|-------|-------|
| **NSE Symbol** | IGL |
| **Full Name** | Indraprastha Gas Limited |
| **Sector** | Oil & Gas / Natural Gas Distribution |
| **Market Cap** | ₹36,500 Cr (approx.) |
| **CMP** | ₹520-550 (approx.) |

---

## Fundamentals (Approximate)

| Metric | Value |
|--------|-------|
| P/E Ratio | 20-22 |
| EPS | ₹22-25 |
| ROE | 18-20% |
| Debt to Equity | Low |
| Dividend Yield | 1.5-2.0% |

---

## Business Description

Indraprastha Gas Limited (IGL) is the sole CNG/LPNG distribution company for Delhi and NCR region. Key facts:
- Monopoly in Delhi CNG market
- Expanding in Kanpur, Lucknow, Gurugram, etc.
- PNG infrastructure expansion ongoing
- Volume growth driven by pollution control norms and fuel switching

---

## Why This Stock

1. **Win Rate:** 60.2% with ADX_TREND strategy (from benchmark)
2. **Monopoly Power:** Sole CNG provider in Delhi — regulatory moat
3. **Volume Growth:** Higher gas volumes from new geographical areas
4. **Policy Tailwind:** CNG/PNG push under clean energy initiatives
5. **Not covered yet:** No live_IGL.py in deploy/ folder

---

## Strategy

**ADX_TREND (Average Directional Index)**
- adx_period: 14
- adx_threshold: 25 (strong trend filter)
- Signal: ADX > threshold + DI+ > DI- → BUY; ADX > threshold + DI- > DI+ → SELL

**Entry Rules:**
- BUY: ADX > 25 AND DI+ crosses above DI-
- SELL: ADX > 25 AND DI- crosses above DI+

---

## Risk Parameters

| Parameter | Value |
|-----------|-------|
| Position Size | ₹7,000 |
| Stop Loss | 0.8% ATR |
| Target | 4.0x ATR |
| Daily Loss Cap | 0.3% of capital |

---

## Risks

- Gas price volatility (netbacks)
- Regulatory/tariff risk from PNGRB
- Competition from other gas distributors in new areas
- Industrial demand sensitivity to economic cycles

---

## Source

- NSE/BSE filings, Groww.in, Moneycontrol

---
*Not financial advice. DYOR.*
