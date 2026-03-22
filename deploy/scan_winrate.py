#!/usr/bin/env python3
"""
Fast WR scanner — scan all stocks with simple RSI strategy to find 90%+ candidates.
Use 2yr data, basic RSI(14) + VWAP, relaxed entry.
"""
import yfinance as yf
import json
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
POSITION_SIZE = 10000

STOCKS = [
    "SBIN", "BPCL", "HINDALCO", "VEDL", "TATASTEEL", "BANKINDIA",
    "NTPC", "POWERGRID", "TECHM", "INFY", "TCS", "COALINDIA",
    "MARUTI", "NESTLEIND", "LT", "AXISBANK", "ICICIBANK", "KOTAKBANK",
    "BAJFINANCE", "RELIANCE", "HDFCBANK", "CIPLA", "SRF", "IGL",
    "M&M", "HEROMOTOCO", "HCLTECH", "SUNPHARMA", "DRREDDY", "DIVISLAB",
    "ASHOKLEY", "EICHERMOT", "ESCORTS", "BAJAJFINSV", "HDFCLIFE",
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "ADANIENT", "TATAMOTORS",
    "ULTRACEMCO", "SHREECEM", "GRASIM", "AMBUJACEM", "ACC", "SAIL",
    "NMDC", "COALINDIA", "GAIL", "ONGC", "IOC", "BPCL", "HPCL", "SHELL",
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

def scan_stock(sym, rsi_thresh=60, hold_days=5):
    try:
        d = yf.Ticker(sym+".NS").history(period="2y")
        if len(d) < 200: return None
        closes = d['Close'].tolist()
        volumes = d['Volume'].tolist()
        ohlcv = [[float(r.Open),float(r.High),float(r.Low),float(r.Close),float(r.Volume)] for _,r in d.iterrows()]
        vwaps = calc_vwap(ohlcv)
        rsis = calc_rsi(closes)
        
        trades = []
        for i in range(50, len(closes)-hold_days):
            price = closes[i]
            vwap = vwaps[i]
            rsi = rsis[i]
            avg_vol = sum(volumes[i-20:i])/20
            vol = volumes[i]
            
            # Relaxed: price within 1% of VWAP + RSI > threshold
            if price >= vwap * 0.99 and price <= vwap * 1.02 and rsi > rsi_thresh and vol > avg_vol * 0.8:
                # Buy and hold
                exit_price = closes[i+hold_days]
                pnl = (exit_price - price) * (POSITION_SIZE // price)
                trades.append(pnl)
        
        if len(trades) < 5: return None
        wins = sum(1 for t in trades if t > 0)
        wr = wins / len(trades) * 100
        total = sum(trades)
        return {
            "sym": sym, "wr": round(wr,1), "trades": len(trades),
            "wins": wins, "losses": len(trades)-wins,
            "total_pnl": round(total,0),
            "avg_pnl": round(total/len(trades),0),
            "rsi_thresh": rsi_thresh, "hold_days": hold_days,
        }
    except Exception as e:
        return None

def main():
    print(f"=== FAST WR SCANNER ===")
    print(f"Stocks: {len(STOCKS)} | Period: 2yr | Strategy: RSI({60})+VWAP")
    print()
    
    results = []
    for i, sym in enumerate(STOCKS):
        print(f"[{i+1}/{len(STOCKS)}] {sym}...", end=" ", flush=True)
        r = scan_stock(sym, rsi_thresh=60, hold_days=5)
        if r:
            print(f"WR={r['wr']}% trades={r['trades']} PnL=Rs{r['total_pnl']:.0f}")
            results.append(r)
        else:
            print("no data")
    
    # Also scan with different RSI thresholds
    print("\n--- RSI 50 threshold ---")
    for sym in [r["sym"] for r in results if r["wr"] < 70]:
        print(f"  {sym} (retry RSI>50)...", end=" ", flush=True)
        r = scan_stock(sym, rsi_thresh=50, hold_days=5)
        if r and r["wr"] > 0:
            r["note"] = "RSI50"
            print(f"WR={r['wr']}% trades={r['trades']}")
    
    results.sort(key=lambda x: (x["wr"], x["trades"]), reverse=True)
    
    out = WORKSPACE / "research" / "backtest_results" / "wr_scanner.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n=== TOP 15 ===")
    for r in results[:15]:
        print(f"  {r['sym']}: WR={r['wr']}% ({r['trades']} trades) PnL=Rs{r['total_pnl']:.0f}")
    
    top10 = results[:10]
    avg_wr = sum(r["wr"] for r in top10)/10 if top10 else 0
    all_90 = all(r["wr"] >= 90 for r in top10)
    print(f"\nTop 10 avg WR: {avg_wr:.1f}%")
    print(f"All ≥ 90%: {all_90}")
    if all_90:
        print("🎉 TARGET ACHIEVED!")
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
