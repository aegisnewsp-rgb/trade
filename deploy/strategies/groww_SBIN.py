#!/usr/bin/env python3
"""
Groww Strategy - SBIN
Generated from live trading script
Win rates based on 6mo backtest
"""
import os, sys, json
from datetime import datetime, timedelta

WORKSPACE = "/home/node/workspace/trade-project/deploy"
sys.path.insert(0, WORKSPACE)

YFINANCE_AVAILABLE = True

def get_signal():
    """Generate trading signal for SBIN. Returns (signal, price, atr)"""
    try:
        import yfinance as yf
        ticker = yf.Ticker("SBIN.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            return None, None, None
        
        ohlcv = [[float(r.Open), float(r.High), float(r.Low),
                   float(r.Close), float(r.Volume)] for r in d.itertuples()]
        closes = [row[3] for row in ohlcv]
        
        # VWAP
        cum_tp, cum_v = 0.0, 0.0
        vwaps = []
        for o, h, l, c, v in ohlcv:
            cum_tp += (o + h + l + c) / 4.0 * v
            cum_v += v
            vwaps.append(cum_tp / cum_v if cum_v > 0 else c)
        vwap = vwaps[-1]
        
        # RSI
        ds = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        g = [d for d in ds[-14:] if d > 0]
        l = [-d for d in ds[-14:] if d < 0]
        ag = sum(g) / 14 if g else 0
        al = sum(l) / 14 if l else 0
        rsi = 50 if al == 0 else 100 - (100 / (1 + ag / al))
        
        # ATR
        trs = []
        for i in range(2, len(ohlcv)):
            h, l_ = ohlcv[i][1], ohlcv[i][2]
            pc = ohlcv[i-1][3]
            trs.append(max(h - l_, abs(h - pc), abs(l_ - pc)))
        atr = sum(trs[-14:]) / 14 if trs else 1.0
        
        # Volume ratio
        vols = [row[4] for row in ohlcv]
        avg_v = sum(vols[-20:]) / 20
        vr = vols[-1] / avg_v if avg_v > 0 else 1.0
        
        price = closes[-1]
        
        # Regime
        sma20 = sum(closes[-20:]) / 20
        regime = "UPTREND" if price > sma20 * 1.02 else "DOWNTREND" if price < sma20 * 0.98 else "RANGE"
        
        # Signal
        if regime != "DOWNTREND":
            vr_thresh = 1.5 if regime == "RANGE" else 1.2
            if price > vwap * 1.005 and rsi > 55 and vr > vr_thresh:
                return "BUY", price, atr
            elif price < vwap * 0.995 and rsi < 45 and vr > vr_thresh:
                return "SELL", price, atr
        
        return None, None, None
    except Exception as e:
        return None, None, None

def main():
    sig, price, atr = get_signal()
    if sig:
        print(f"SIGNAL: {sig} SBIN @ Rs{price:.2f} ATR:{atr:.2f}")
    else:
        print(f"SBIN: No signal")

if __name__ == "__main__":
    main()
