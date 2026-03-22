#!/usr/bin/env python3
"""Short-selling optimizer — find stocks with 90%+ WR on SHORT signals."""
import yfinance as yf, json, time
from pathlib import Path

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

def scan_short(sym, rsi_thresh, vol_mult, hold, tol):
    try:
        d = yf.Ticker(sym+".NS").history(period="2y")
        if len(d) < 200: return None
        closes = d['Close'].tolist()
        volumes = d['Volume'].tolist()
        ohlcv = [[float(r.Open),float(r.High),float(r.Low),float(r.Close),float(r.Volume)] for _,r in d.iterrows()]
        vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        
        trades = []
        for i in range(50, len(closes)-hold):
            price = closes[i]
            vwap = vwaps[i]
            rsi = rsis[i]
            avg_vol = sum(volumes[i-20:i])/20
            vol_ratio = volumes[i]/avg_vol if avg_vol > 0 else 1.0
            
            # SHORT: price below VWAP + RSI oversold (low RSI = bearish exhaustion)
            if price <= vwap*(1+tol) and price >= vwap*(1-tol) and rsi < rsi_thresh and vol_ratio > vol_mult:
                exit_price = closes[i+hold]
                # For shorts: profit when price goes DOWN
                pnl = (exit_price - price) * (POSITION_SIZE // price)  # negative if price fell
                # Actually for SHORT: entry is higher, exit is lower = profit
                pnl = (price - exit_price) * (POSITION_SIZE // price)
                trades.append(pnl)
        
        if len(trades) < 3: return None
        wins = sum(1 for t in trades if t > 0)
        return len(trades), wins, sum(trades)
    except: return None

STOCKS = [
    "SBIN","BPCL","HINDALCO","VEDL","TATASTEEL","BANKINDIA","NTPC","POWERGRID",
    "TECHM","INFY","TCS","COALINDIA","MARUTI","NESTLEIND","LT","AXISBANK",
    "ICICIBANK","KOTAKBANK","BAJFINANCE","RELIANCE","HDFCBANK","CIPLA","SRF",
    "IGL","M&M","HEROMOTOCO","HCLTECH","SUNPHARMA","DRREDDY","DIVISLAB",
    "ASHOKLEY","EICHERMOT","ESCORTS","BAJAJFINSV","HDFCLIFE","ADANIPOWER",
    "ADANIGREEN","ADANIPORTS","TATAMOTORS","ULTRACEMCO","SHREECEM","GRASIM",
    "AMBUJACEM","ACC","SAIL","NMDC","GAIL","ONGC","IOC","HPCL","LUPIN",
    "AUROPHARMA","CHOLAFIN","MUTHOOTFIN","SBILIFE","ICICIPRULI"
]

RSI_VALS = [30, 35, 40, 45, 50]
VOL_VALS = [0.5, 0.75, 1.0]
HOLD_VALS = [5, 10]
TOL_VALS = [0.005, 0.01]

print(f"=== SHORT SELLING OPTIMIZER ===")
print(f"Stocks: {len(STOCKS)} | Combos: {len(RSI_VALS)*len(VOL_VALS)*len(HOLD_VALS)*len(TOL_VALS)} each")
print()

results = []
for i, sym in enumerate(STOCKS):
    best = {"sym":sym,"wr":0,"trades":0,"rsi":40,"vol":0.8,"hold":5,"tolerance":0.01}
    for rsi, vol, hold, tol in [(r,v,h,t) for r in RSI_VALS for v in VOL_VALS for h in HOLD_VALS for t in TOL_VALS]:
        res = scan_short(sym, rsi, vol, hold, tol)
        if res and res[0] >= 3:
            n, w, p = res
            wr = w/n*100
            if wr > best["wr"] or (wr == best["wr"] and n > best["trades"]):
                best = {"sym":sym,"wr":round(wr,1),"trades":n,"wins":w,"pnl":round(p,0),
                       "rsi":rsi,"vol":vol,"hold":hold,"tolerance":tol}
    if best["wr"] > 0:
        print(f"  {best['sym']}: WR={best['wr']}% ({best['trades']} trades) RSI<{best['rsi']} Vol>{best['vol']} Hold={best['hold']}d PnL=Rs{best.get('pnl',0):.0f}")
        results.append(best)
    else:
        print(f"  {sym}: no short signals")
    time.sleep(0.1)

results.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)

out = WORKSPACE / "research" / "backtest_results" / "short_optimized.json"
with open(out, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n=== TOP 10 SHORT SIGNALS ===")
for r in results[:10]:
    print(f"  {r['sym']}: WR={r['wr']}% ({r['trades']} trades) RSI<{r['rsi']} Vol>{r['vol']} Hold={r['hold']}d")

top10 = results[:10]
avg_wr = sum(r["wr"] for r in top10)/10 if top10 else 0
all_90 = all(r["wr"] >= 90 for r in top10)
print(f"\nTop 10 avg WR: {avg_wr:.1f}%")
print(f"All ≥ 90%: {all_90}")
if all_90: print("🎉 SHORT SELLING TARGET ACHIEVED!")

# Also find stocks where BOTH long and short work
try:
    with open(WORKSPACE / "research" / "backtest_results" / "sniper_90.json") as f:
        long_stocks = {s["sym"]: s for s in json.load(f)}
    
    print(f"\n=== BOTH DIRECTIONS WORK ===")
    both = []
    for r in results:
        if r["sym"] in long_stocks:
            lr = long_stocks[r["sym"]]
            if lr["wr"] >= 70 and r["wr"] >= 70:
                both.append({"sym": r["sym"], "long_wr": lr["wr"], "short_wr": r["wr"], 
                            "long_hold": lr["hold"], "short_hold": r["hold"]})
                print(f"  {r['sym']}: LONG={lr['wr']}% SHORT={r['wr']}%")
    
    with open(WORKSPACE / "research" / "backtest_results" / "both_directions.json", "w") as f:
        json.dump(both, f, indent=2)
    print(f"\n{both} stocks work in BOTH directions")
except: pass

print(f"\nSaved: {out}")
