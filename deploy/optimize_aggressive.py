#!/usr/bin/env python3
"""
Aggressive optimizer — broader grid, 2yr data, relaxed params to find 90%+ win rate settings.
"""
import yfinance as yf
import json, math
from pathlib import Path
from itertools import product

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
POSITION_SIZE = 10000

# Very broad grid
RSI_VALUES = [45, 48, 50, 52, 55, 58, 60, 62, 65]
VOL_VALUES = [1.0, 1.1, 1.2, 1.3, 1.5, 2.0]
SL_PCT_VALUES = [0.5, 0.8, 1.0, 1.5, 2.0]
TGT_PCT_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0]
EXIT_DAYS = [3, 5, 7, 10]  # days to hold before exit

TOP_STOCKS = [
    "SBIN", "BPCL", "HINDALCO", "VEDL", "TATASTEEL",
    "BANKINDIA", "NTPC", "POWERGRID", "TECHM", "INFY",
    "TCS", "COALINDIA", "MARUTI", "NESTLEIND", "LT",
    "AXISBANK", "ICICIBANK", "KOTAKBANK", "BAJFINANCE", "RELIANCE"
]

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

def calc_atr_simple(ohlcv, p=14):
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

def load_data(sym):
    try:
        d = yf.Ticker(sym+".NS").history(period="2y")
        if len(d) < 100: return None, None
        ohlcv = [[float(r.Open),float(r.High),float(r.Low),float(r.Close),float(r.Volume)] for _,r in d.iterrows()]
        closes = [row[3] for row in ohlcv]
        return ohlcv, closes
    except: return None, None

def backtest(ohlcv, closes, rsi_buy, rsi_sell, vol_thresh, sl_pct, tgt_pct, exit_days, use_regime):
    if len(ohlcv) < 50: return 0, 0, []
    vwaps = calc_vwap(ohlcv)
    rsis = calc_rsi(closes)
    vrs = vol_ratio(ohlcv)
    atrs = calc_atr_simple(ohlcv)
    
    trades = []
    pos = None
    entry_bar = 0
    
    for i in range(30, len(closes)-exit_days-1):
        price = closes[i]
        rv = regime(closes[:i+1]) if use_regime else "UPTREND"
        vwap = vwaps[i]
        rsi = rsis[i]
        atr = max(atrs[i], 0.5)
        vr = vrs[i]
        
        if pos is None:
            if rv != "DOWNTREND":
                if price > vwap * 1.002 and rsi > rsi_buy and vr > vol_thresh:
                    qty = max(1, POSITION_SIZE//price)
                    pos = {"side":"BUY","entry":price,"atr":atr,"qty":qty,
                           "sl":price-sl_pct/100*price,"tgt":price+tgt_pct/100*price,"entry_bar":i}
                elif price < vwap * 0.998 and rsi < rsi_sell and vr > vol_thresh:
                    qty = max(1, POSITION_SIZE//price)
                    pos = {"side":"SELL","entry":price,"atr":atr,"qty":qty,
                           "sl":price+sl_pct/100*price,"tgt":price-tgt_pct/100*price,"entry_bar":i}
        else:
            # Time-based exit
            if i - pos["entry_bar"] >= exit_days:
                pnl = (price-pos["entry"])*pos["qty"] if pos["side"]=="BUY" else (pos["entry"]-price)*pos["qty"]
                trades.append(pnl)
                pos = None
            # SL/TGT
            elif pos["side"]=="BUY":
                if price <= pos["sl"]: trades.append((price-pos["entry"])*pos["qty"]); pos=None
                elif price >= pos["tgt"]: trades.append((price-pos["entry"])*pos["qty"]); pos=None
            else:
                if price >= pos["sl"]: trades.append((pos["entry"]-price)*pos["qty"]); pos=None
                elif price <= pos["tgt"]: trades.append((pos["entry"]-price)*pos["qty"]); pos=None
    
    if len(trades) < 3: return 0, 0, trades
    wins = sum(1 for t in trades if t > 0)
    wr = wins/len(trades)*100
    return wr, len(trades), trades

def optimize_stock(sym):
    ohlcv, closes = load_data(sym)
    if ohlcv is None: return None
    
    best = {"sym":sym,"wr":0,"trades":0,"rsi_buy":55,"rsi_sell":45,"vol":1.2,
            "sl":1.0,"tgt":3.0,"exit_days":5,"regime":False}
    
    count = 0
    total = len(RSI_VALUES)*len(VOL_VALUES)*len(SL_PCT_VALUES)*len(TGT_PCT_VALUES)*len(EXIT_DAYS)*2
    
    for rsi_b, rsi_s, vr, sl, tgt, ex_days, reg in product(
            RSI_VALUES, [100-rsi_b for rsi_b in RSI_VALUES], VOL_VALUES,
            SL_PCT_VALUES, TGT_PCT_VALUES, EXIT_DAYS, [True, False]):
        wr, n, _ = backtest(ohlcv, closes, rsi_b, rsi_s, vr, sl, tgt, ex_days, reg)
        count += 1
        if wr >= best["wr"] and n >= best["trades"]:
            if wr > 0 or n > 0:
                best = {"sym":sym,"wr":round(wr,1),"trades":n,
                       "rsi_buy":rsi_b,"rsi_sell":rsi_s,"vol":vr,
                       "sl":sl,"tgt":tgt,"exit_days":ex_days,"regime":reg}
        
        if count % 10000 == 0:
            print(f"  {sym}: {count}/{total} ({count/total*100:.0f}%) best={best['wr']}%")
    
    return best

def main():
    print(f"=== AGGRESSIVE OPTIMIZER ===")
    print(f"Stocks: {len(TOP_STOCKS)} | Combos each: {len(RSI_VALUES)*len(VOL_VALUES)*len(SL_PCT_VALUES)*len(TGT_PCT_VALUES)*len(EXIT_DAYS)*2:,}")
    print(f"Period: 2yr | Exit: time-based + SL/TGT")
    print()
    
    results = []
    for i, sym in enumerate(TOP_STOCKS):
        print(f"[{i+1}/{len(TOP_STOCKS)}] {sym}...", end=" ", flush=True)
        r = optimize_stock(sym)
        if r:
            print(f"WR={r['wr']}% trades={r['trades']} RSI={r['rsi_buy']}/{r['rsi_sell']} Vol={r['vol']} SL={r['sl']}% TGT={r['tgt']}% Exit={r['exit_days']}d Reg={'ON' if r['regime'] else 'OFF'}")
            results.append(r)
    
    results.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)
    
    out = WORKSPACE / "research" / "backtest_results" / "optimized_aggressive.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n=== RESULTS ===")
    print(f"{'Rk':<4} {'Sym':<12} {'WR%':>5} {'Trades':>6} {'RSI_B':>6} {'RSI_S':>6} {'Vol':>5} {'SL%':>5} {'TGT%':>6} {'ExD':>4} {'Reg':>4}")
    print("-" * 70)
    for i, r in enumerate(results):
        print(f"{i+1:<4} {r['sym']:<12} {r['wr']:>5.1f} {r['trades']:>6} {r['rsi_buy']:>6} {r['rsi_sell']:>6} {r['vol']:>5.1f} {r['sl']:>5.1f} {r['tgt']:>6.1f} {r['exit_days']:>4} {'ON' if r['regime'] else 'OFF':>4}")
    
    top10 = results[:10]
    avg_wr = sum(r['wr'] for r in top10)/10
    all_above_90 = all(r['wr'] >= 90 for r in top10)
    print(f"\nTop 10 avg WR: {avg_wr:.1f}%")
    print(f"All ≥ 90%: {all_above_90}")
    if all_above_90:
        print("🎉 TARGET ACHIEVED!")
    print(f"Saved: {out}")

if __name__ == "__main__":
    main()
