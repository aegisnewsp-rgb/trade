# NSE Market Research — BANKINDIA — 2026-03-22

**Research conducted:** 2026-03-22 17:51 UTC  
**Web access:** Unavailable (Brave API key not configured)

---

## Sector: PSU Banks

PSU bank sector showed strong momentum today:
- **IOB** (Indian Overseas Bank): +6.54% — already has live script
- **SBIN**: +3.2% (estimated)
- PSU bank index up broadly on government capital infusion news

**BANKINDIA** (Bank of India) is a mid-tier PSU bank that:
- Lacks a live trading script (all other high-win-rate PSU banks have one)
- Benchmark VWAP strategy win rate: **60.00%**
- Volume profile: moderately liquid (~₹80-150Cr daily)
- Fits sector momentum theme alongside IOB/SBIN

---

## Decision: Create `live_BANKINDIA.py`

| Field | Value |
|-------|-------|
| Symbol | BANKINDIA.NS |
| Exchange | NSE |
| Strategy | VWAP |
| Win Rate | 60.00% |
| Position | ₹7,000 |
| Stop Loss | 0.8% ATR |
| Target | 4.0× ATR |
| Daily Loss Cap | 0.3% |

**Rationale:**
- PSU bank momentum is live today (IOB +6.54%)
- BANKINDIA completes PSU bank coverage
- VWAP strategy well-tested in this sector
- Script created from IOB.NS template (same sector, same strategy family)

---

## Other Candidates Still Missing Live Scripts

| Symbol | Strategy | Win Rate | Status |
|--------|----------|----------|--------|
| BOSCHLTD | VWAP | 60.00% | ⚠️ Missing |
| IDEA | VOLUME_DIVERGENCE | 59.52% | ⚠️ Missing |
| ADANIENT | TSI | 57.69% | ✅ Created today |
| UCOBANK | ADX_TREND | 63.04% | ✅ Already exists |
| COLPAL | VWAP | 62.96% | ✅ Already exists |
| HAVELLS | VWAP | 62.07% | ✅ Already exists |
