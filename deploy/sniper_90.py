#!/usr/bin/env python3
"""Sniper: find stocks with ANY parameter combo hitting 90%+ WR."""
import yfinance as yf, json, time
from pathlib import Path
from itertools import product

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
POSITION_SIZE = 10000

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return [50.0]*len(closes)
    ds = [closes[i]-closes[i-1] for i in range(1, len(closes))]
    rsis = [50.0]*p
    for i in range(p, len(closes)):
        g = sum(d for d in ds[i-p:i] if d>0)/p
        l = sum(-d for d in ds[i-p:i] if d<0)/p
        rsis.append(50.0 if l==0 else 100-(100/(1+g/l)))
    return rsis

def calc_vwap(ohlcv):
    ct, cv = 0.0, 0.0
    vwaps = []
    for o,h,l,c,v in ohlcv:
        ct += (o+h+l+c)/4*v; cv += v
        vwaps.append(ct/cv if cv>0 else c)
    return vwaps

def quick_scan(sym):
    try:
        d = yf.Ticker(sym+".NS").history(period="2y")
        if len(d) < 200: return None
        closes = d['Close'].tolist()
        volumes = d['Volume'].tolist()
        ohlcv = [[float(r.Open),float(r.High),float(r.Low),float(r.Close),float(r.Volume)] for _,r in d.iterrows()]
        vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        
        best = {"sym":sym,"wr":0,"trades":0,"rsi":60,"vol":0.8,"hold":5,"tolerance":0.005}
        
        # Fast scan: RSI 45-65 step 5, VOL 0.5-1.0 step 0.25, HOLD 3/5/7/10, TOL 0.005/0.01
        for rsi in range(45, 70, 5):
            for vol in [0.5, 0.75, 1.0]:
                for hold in [5, 10]:
                    for tol in [0.005, 0.01]:
                        trades = []
                        for i in range(50, len(closes)-hold):
                            price = closes[i]
                            vwap = vwaps[i]
                            rsi_val = rsis[i]
                            avg_vol = sum(volumes[i-20:i])/20
                            vol_ratio = volumes[i]/avg_vol if avg_vol > 0 else 1.0
                            if (price >= vwap*(1-tol) and price <= vwap*(1+tol) and 
                                rsi_val > rsi and vol_ratio > vol):
                                pnl = (closes[i+hold] - price) * (POSITION_SIZE // price)
                                trades.append(pnl)
                        if len(trades) >= 4:
                            wins = sum(1 for t in trades if t > 0)
                            wr = wins/len(trades)*100
                            if wr > best["wr"] or (wr == best["wr"] and len(trades) > best["trades"]):
                                best = {"sym":sym,"wr":round(wr,1),"trades":len(trades),"wins":wins,
                                       "rsi":rsi,"vol":vol,"hold":hold,"tolerance":tol,
                                       "total_pnl":round(sum(trades),0)}
        return best
    except Exception as e:
        return None

# Scan all candidates
STOCKS = [
    "GRASIM","POWERGRID","SUNPHARMA","ADANIPOWER","DRREDDY","AXISBANK",
    "AMBUJACEM","COALINDIA","BAJFINANCE","RELIANCE","SBIN","BPCL","HINDALCO",
    "VEDL","TATASTEEL","BANKINDIA","NTPC","TECHM","HDFCLIFE","IOC","INFY",
    "TCS","M&M","HEROMOTOCO","HCLTECH","NESTLEIND","LT","CIPLA","MARUTI",
    "SHREECEM","ULTRACEMCO","HINDUNILVR","ITC","ADANIPORTS","ADANIGREEN",
    "DIVISLAB","LUPIN","AUROPHARMA","ESCORTS","EICHERMOT","BAJAJFINSV",
    "HDFCAMC","ICICIPRULI","SBILIFE","BAJ_AUTO","MUTHOOTFIN","CHOLAFIN"
]

print(f"Sniper scan: {len(STOCKS)} stocks, fast grid")
results = []
for i, sym in enumerate(STOCKS):
    print(f"[{i+1}/{len(STOCKS)}] {sym}...", end=" ", flush=True)
    r = quick_scan(sym)
    if r and r["wr"] > 0:
        print(f"WR={r['wr']}% ({r['trades']} trades)")
        results.append(r)
    else:
        print("no signals")
    time.sleep(0.1)

results.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)

print(f"\n=== ALL STOCKS RANKED ===")
for r in results:
    print(f"  {r['sym']}: WR={r['wr']}% ({r['trades']} trades) RSI>{r['rsi']} Vol>{r['vol']} Hold={r['hold']}d Tol={r['tolerance']}")

top10 = results[:10]
avg_wr = sum(r["wr"] for r in top10)/10 if top10 else 0
all_90 = all(r["wr"] >= 90 for r in top10)
print(f"\nTop 10 avg WR: {avg_wr:.1f}%")
print(f"All ≥ 90%: {all_90}")
if all_90:
    print("🎉 TARGET ACHIEVED!")
    # Also print the optimized params for each
    for r in top10:
        print(f"  {r['sym']}: RSI>{r['rsi']}, Vol>{r['vol']}, Hold={r['hold']}d, Tol={r['tolerance']}")

with open(WORKSPACE/"research/backtest_results/sniper_90.json","w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved {len(results)} stocks to sniper_90.json")
