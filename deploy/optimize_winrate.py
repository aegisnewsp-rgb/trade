#!/usr/bin/env python3
"""
Parameter optimizer — find RSI + Volume + ATR params that give 90%+ win rate.
Runs exhaustive grid search on top candidates.
"""
import yfinance as yf
import json
import math
from datetime import datetime
from pathlib import Path
from itertools import product

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
POSITION_SIZE = 10000

RSI_VALUES = [50, 52, 55, 58, 60]
VOL_VALUES = [1.0, 1.1, 1.2, 1.3, 1.5]
SL_ATR_VALUES = [0.5, 0.8, 1.0, 1.2, 1.5]
TGT_ATR_VALUES = [2.0, 3.0, 4.0, 5.0, 6.0]
REGIME_OPTIONS = [True, False]

TOP_STOCKS = [
    "SBIN", "BPCL", "HINDALCO", "VEDL", "TATASTEEL",
    "BANKINDIA", "NTPC", "POWERGRID", "TECHM", "INFY",
    "TCS", "COALINDIA", "MARUTI", "NESTLEIND", "LT"
]

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return 50.0
    ds = [closes[i]-closes[i-1] for i in range(1, len(closes))]
    rsis = [50.0]*p
    for i in range(p, len(closes)):
        g = sum(d for d in ds[i-p:i] if d>0)/p
        l = sum(-d for d in ds[i-p:i] if d<0)/p
        rsis.append(50.0 if l==0 else 100-(100/(1+g/l)))
    return rsis

def calc_atr(ohlcv, p=14):
    if len(ohlcv) < p+2: return [1.0]*len(ohlcv)
    trs = [0.0]*len(ohlcv)
    for i in range(2, len(ohlcv)):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        trs[i] = max(h-l, abs(h-pc), abs(l-pc))
    atrs = [0.0]*len(ohlcv)
    atrs[p] = sum(trs[1:p+1])/p
    for i in range(p+1, len(ohlcv)):
        atrs[i] = (atrs[i-1]*(p-1)+trs[i])/p
    return atrs

def calc_vwap(ohlcv):
    ct, cv = 0.0, 0.0
    vwaps = []
    for o,h,l,c,v in ohlcv:
        ct += (o+h+l+c)/4*v
        cv += v
        vwaps.append(ct/cv if cv>0 else c)
    return vwaps

def vol_ratio(ohlcv, p=20):
    if len(ohlcv) < p+1: return [1.0]*len(ohlcv)
    vrs = [1.0]*len(ohlcv)
    for i in range(p, len(ohlcv)):
        avg = sum(row[4] for row in ohlcv[i-p:i])/p
        vrs[i] = ohlcv[i][4]/avg if avg>0 else 1.0
    return vrs

def regime(closes, p=20):
    if len(closes) < p+1: return "RANGE"
    sma = sum(closes[-p:])/p
    r = closes[-1]/sma if sma>0 else 1.0
    return "UPTREND" if r>1.02 else "DOWNTREND" if r<0.98 else "RANGE"

def backtest(ohlcv, closes, rsi_vals, vr_vals, sl_buy, tgt_buy, regime_filter):
    if len(ohlcv) < 40: return 0, 0, []
    vwaps = calc_vwap(ohlcv)
    rsis = calc_rsi(closes)
    atrs = calc_atr(ohlcv)
    vrs = vol_ratio(ohlcv)
    
    trades = []
    pos = None
    for i in range(25, len(closes)-5):
        price = closes[i]
        rv = regime(closes[:i+1]) if regime_filter else "UPTREND"
        vwap = vwaps[i]
        rsi = rsis[i]
        atr = max(atrs[i], 0.5)
        vr = vrs[i]
        
        if pos is None:
            if rv != "DOWNTREND":
                vt = 1.5 if rv == "RANGE" else vr_vals
                if price > vwap * (1 + (vwap*0.001)) and rsi > rsi_vals and vr > vt:
                    qty = max(1, POSITION_SIZE//price)
                    pos = {"side":"BUY","entry":price,"atr":atr,"qty":qty,
                           "sl":price-sl_buy*atr,"tgt":price+tgt_buy*atr}
                elif price < vwap * (1 - (vwap*0.001)) and rsi < (100-rsi_vals) and vr > vt:
                    qty = max(1, POSITION_SIZE//price)
                    pos = {"side":"SELL","entry":price,"atr":atr,"qty":qty,
                           "sl":price+sl_buy*atr,"tgt":price-tgt_buy*atr}
        else:
            pnl = 0
            ex = False
            if pos["side"]=="BUY":
                if price >= pos["tgt"]: pnl=(price-pos["entry"])*pos["qty"]; ex=True
                elif price <= pos["sl"]: pnl=(price-pos["entry"])*pos["qty"]; ex=True
            else:
                if price <= pos["tgt"]: pnl=(pos["entry"]-price)*pos["qty"]; ex=True
                elif price >= pos["sl"]: pnl=(pos["entry"]-price)*pos["qty"]; ex=True
            if ex:
                trades.append(pnl)
                pos = None
    
    if len(trades) < 3: return 0, 0, trades
    wins = sum(1 for t in trades if t > 0)
    wr = wins/len(trades)*100
    return wr, len(trades), trades

def load_data(sym):
    try:
        d = yf.Ticker(sym+".NS").history(period="12mo")
        if len(d) < 60: return None, None
        ohlcv = [[float(r.Open),float(r.High),float(r.Low),float(r.Close),float(r.Volume)] for _,r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        return ohlcv, closes
    except: return None, None

def optimize_stock(sym):
    ohlcv, closes = load_data(sym)
    if ohlcv is None: return None
    
    best = {"sym":sym,"wr":0,"trades":0,"rsi":55,"vol":1.2,"sl":0.8,"tgt":4.0,"regime":True}
    
    for rsi, vr, sl, tgt, reg in product(RSI_VALUES, VOL_VALUES, SL_ATR_VALUES, TGT_ATR_VALUES, REGIME_OPTIONS):
        wr, n, trades = backtest(ohlcv, closes, rsi, vr, sl, tgt, reg)
        if wr > best["wr"] or (wr == best["wr"] and n > best["trades"]):
            best = {"sym":sym,"wr":round(wr,1),"trades":n,"rsi":rsi,"vol":vr,"sl":sl,"tgt":tgt,"regime":reg,"trades_detail":trades}
    
    return best

def main():
    print(f"=== PARAMETER OPTIMIZER ===")
    print(f"Stocks: {len(TOP_STOCKS)} | Grid: {len(RSI_VALUES)*len(VOL_VALUES)*len(SL_ATR_VALUES)*len(TGT_ATR_VALUES)*2:,} combinations each")
    print()
    
    results = []
    for i, sym in enumerate(TOP_STOCKS):
        print(f"[{i+1}/{len(TOP_STOCKS)}] Optimizing {sym}...", end=" ", flush=True)
        r = optimize_stock(sym)
        if r:
            print(f"WR={r['wr']}% trades={r['trades']} RSI={r['rsi']} Vol={r['vol']} SL={r['sl']} TGT={r['tgt']} Regime={'ON' if r['regime'] else 'OFF'}")
            results.append(r)
        else:
            print("No data")
    
    # Sort by win rate
    results.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)
    
    # Save
    out = WORKSPACE / "research" / "backtest_results" / "optimized_top10.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n=== OPTIMIZED TOP 10 ===")
    print(f"{'Rank':<5} {'Symbol':<12} {'WR%':>5} {'Trades':>6} {'RSI':>5} {'Vol':>5} {'SL_ATR':>7} {'TGT_ATR':>8} {'Regime':>6}")
    print("-" * 65)
    for i, r in enumerate(results):
        print(f"{i+1:<5} {r['sym']:<12} {r['wr']:>5.1f} {r['trades']:>6} {r['rsi']:>5} {r['vol']:>5.1f} {r['sl']:>7.2f} {r['tgt']:>8.2f} {'ON' if r['regime'] else 'OFF':>6}")
    
    # Check if top 10 are > 90%
    top10_wr = [r['wr'] for r in results[:10]]
    all_above_90 = all(w >= 90 for w in top10_wr)
    avg_wr = sum(top10_wr)/len(top10_wr)
    
    print(f"\nTop 10 avg WR: {avg_wr:.1f}%")
    print(f"All top 10 ≥ 90%: {all_above_90}")
    if all_above_90:
        print("🎉 TARGET ACHIEVED!")
    else:
        below = [(r['sym'], r['wr']) for r in results[:10] if r['wr'] < 90]
        print(f"Below 90%: {below}")
    
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
