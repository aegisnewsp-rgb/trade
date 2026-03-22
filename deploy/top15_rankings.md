# Top 15 Benchmark-Verified Stocks by Win Rate
**Generated:** 2026-03-22  
**Ranking Criteria:** Win Rate (benchmark-verified) descending

| Rank | Symbol | Strategy | Win Rate | Confidence Score | Position Size | Notes |
|------|--------|----------|----------|------------------|---------------|-------|
| 1 | ADANIPOWER.NS | VWAP | 91.67% | 0.88 | 10-15% | **TOP PICK** - Exceptional win rate. High conviction. Volume and trend aligned. |
| 2 | ADANIGREEN.NS | VWAP | 70.00% | 0.75 | 8-12% | Strong performer. Watch for sector momentum. |
| 3 | ADANIPORTS.NS | VWAP | 66.67% | 0.72 | 8-10% | Consistent VWAP performer. |
| 4 | RELIANCE.NS | TSI | 63.64% | 0.70 | 8-10% | TSI momentum strategy. Fast:13, Slow:25, Signal:13 |
| 5 | TCS.NS | VWAP | 63.64% | 0.70 | 8-10% | IT sector leader. VWAP with 14-period, ATR 1.5x |
| 6 | SBIN.NS | VWAP | 63.64% | 0.70 | 8-10% | PSU bank leader. VWAP strategy. |
| 7 | UCOBANK.NS | ADX_TREND | 63.04% | 0.69 | 6-8% | ADX trend following. Period:14, Threshold:25 |
| 8 | GODREJPROP.NS | VWAP | 63.16% | 0.69 | 6-8% | Real estate play. VWAP momentum. |
| 9 | COLPAL.NS | VWAP | 62.96% | 0.68 | 6-8% | FMCG sector. VWAP strategy. |
| 10 | TATASTEEL.NS | VWAP | 61.54% | 0.67 | 6-8% | Metal/steel sector. VWAP momentum. |
| 11 | TITAN.NS | VWAP | 61.11% | 0.67 | 6-8% | Consumer discretionary. VWAP. |
| 12 | HDFCBANK.NS | ADX_TREND | 60.61% | 0.66 | 6-8% | Private banking leader. ADX trend. |
| 13 | HAVELLS.NS | VWAP | 62.07% | 0.68 | 6-8% | Electricals sector. VWAP momentum. |
| 14 | IGL.NS | ADX_TREND | 60.20% | 0.65 | 5-7% | Gas utility. ADX trend following. |
| 15 | MARUTI.NS | VWAP | 59.26% | 0.64 | 5-7% | Auto sector. VWAP momentum. |

---

## Strategy Breakdown

### VWAP Strategies (9 stocks)
**Parameters:** vwap_period=14, atr_multiplier=1.5

**Entry Rules:**
- BUY: Price > VWAP + (ATR × 1.5)
- SELL: Price < VWAP - (ATR × 1.5)

**Strengths:**
- Works well in trending markets
- Volume-weighted = institutional flow aware
- ATR multiplier filters false breakouts

**Weaknesses:**
- Lagging indicator
- Whipsaws in ranging markets
- Requires clear volume spikes

### ADX_TREND Strategies (3 stocks)
**Parameters:** adx_period=14, adx_threshold=25

**Entry Rules:**
- BUY: Price change > 50% of volatility + positive direction
- SELL: Price change > 50% of volatility + negative direction

**Strengths:**
- Catches strong trends early
- Clear threshold-based entry

**Weaknesses:**
- Simplified ADX calculation
- May miss early reversals
- Sensitive to threshold parameter

### TSI Strategy (1 stock)
**Parameters:** fast_period=13, slow_period=25, signal_period=13

**Entry Rules:**
- BUY: Fast TSI > Slow TSI
- SELL: Fast TSI < Slow TSI

**Strengths:**
- Double-smoothed momentum
- Less noise than single momentum

**Weaknesses:**
- Complex calculation
- Lag in fast-moving markets

---

## Confidence Score Formula

```
confidence = 0.40 × win_rate + 0.30 × min(volume_ratio/2, 1.0) + 0.30 × trend_strength
```

**Adjustments:**
- RSI > 70 or < 30: 8-15% reduction
- Very low volatility (< 10%): 15% reduction
- Non-benchmark verified: 10% penalty

---

## Recommended Position Sizing

| Confidence | Position Size |
|------------|--------------|
| > 0.80 | 10-15% of capital |
| 0.70 - 0.80 | 8-12% of capital |
| 0.60 - 0.70 | 6-8% of capital |
| 0.50 - 0.60 | 4-6% of capital |
| < 0.50 | 0-4% (avoid if possible) |

---

## Files Generated

- `master_scanner.py` - Scans all 100 stocks, calculates confidence scores, ranks by conviction
- `strategy_enhancer.py` - Adds multi-filter confirmation (volume, trend, volatility, RSI) to any strategy
- `top15_rankings.md` - This file

## Usage

```bash
# Run master scanner
cd deploy
python master_scanner.py --top 5 --min-confidence 0.65

# Enhance a strategy
python strategy_enhancer.py --input ../RELIANCE_NS.py --output enhanced_RELIANCE.py --strategy TSI
```
