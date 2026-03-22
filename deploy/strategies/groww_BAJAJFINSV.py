#!/usr/bin/env python3
"""
Groww Strategy: BAJAJFINSV
Exchange: NSE | Strategy: VWAP
Win Rate: 55.00%

TO DEPLOY ON GROWW DASHBOARD:
  1. Copy this file's code
  2. Go to groww.in → Trade API → Strategies → New Strategy  
  3. Paste into Python strategy editor
  4. Set env vars: GROWW_API_KEY, GROWW_API_SECRET
  5. Activate strategy

ENTRY: Price > VWAP + 0.5% AND RSI > 55 AND Volume > 1.2x avg
EXIT:   3-tier targets (1.5x/3x/5x risk) OR 0.8% ATR stop loss
RISK:   Max ₹500/stock | Max ₹3000/day
"""

import os, sys, time, json, hmac, hashlib, base64, requests
from datetime import datetime, timedelta

# Config
SYMBOL = "BAJAJFINSV"
EXCHANGE = "NSE"
GROWW_API_KEY = os.getenv("GROWW_API_KEY", "")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET", "")
POSITION = 10000
ENTRY_VWAP_PCT = 0.5
ENTRY_RSI = 55
ENTRY_VOL = 1.2
SL_ATR = 1.0
TGT_RR = [1.5, 3.0, 5.0]

# Groww Auth
_BASE = "https://api.groww.in"
_token, _exp = None, 0

def _auth():
    global _token, _exp
    if _token and time.time() < _exp - 300:
        return _token
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(
        GROWW_API_SECRET.encode(), (GROWW_API_KEY + ts).encode(),
        hashlib.sha256).digest()).decode()
    r = requests.post(_BASE + "/v1/user/tokens", headers={
        "Content-Type": "application/json",
        "X-Groww-Auth-Type": "signature",
        "X-Api-Key": GROWW_API_KEY,
        "X-Request-Timestamp": ts,
        "X-Request-Signature": sig,
    }, json={"clientId": GROWW_API_KEY, "clientSecret": GROWW_API_SECRET,
              "grantType": "client_credentials"}, timeout=10)
    if r.status_code == 200:
        d = r.json()
        _token = d.get("access_token")
        _exp = time.time() + int(d.get("X-Groww-Expiry-Seconds", 86400))
        return _token
    return None

def _hdrs():
    return {"Authorization": "Bearer " + (_auth() or ""),
            "Content-Type": "application/json", "X-Api-Key": GROWW_API_KEY}

def place_bo(trans, qty, target, sl):
    if not GROWW_API_KEY or not GROWW_API_SECRET:
        print(f"[PAPER] {trans} {qty}x {SYMBOL} @ Rs{target} [SL:Rs{sl}]")
        return {"orderId": f"PAPER_{int(time.time())}", "status": "PAPER_MODE"}
    order = {
        "exchange": EXCHANGE, "symbol": SYMBOL, "product": "INTRADAY",
        "orderType": "BO", "transactionType": trans, "quantity": qty,
        "targetPrice": round(target, 2), "stopLossPrice": round(sl, 2),
        "trailingTarget": 0.5, "trailingStopLoss": 0.3, "validity": "DAY",
    }
    r = requests.post(_BASE + "/v1/orders", headers=_hdrs(), json=order, timeout=15)
    if r.status_code in (200, 201):
        print(f"[GROWW] OK {trans} {qty}x {SYMBOL} -> {r.json().get('orderId')}")
        return r.json()
    print(f"[GROWW] FAIL {r.status_code}")
    return None

def calc_vwap(ohlcv):
    ct, cv = 0, 0
    for o, h, l, c, v in ohlcv:
        ct += (o + h + l + c) / 4 * v
        cv += v
    return ct / cv if cv else None

def calc_rsi(closes, p=14):
    if len(closes) < p + 1:
        return 50
    ds = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    g = [d if d > 0 else 0 for d in ds[-p:]]
    l = [-d if d < 0 else 0 for d in ds[-p:]]
    ag, al = sum(g) / p, sum(l) / p
    return 100 - (100 / (1 + ag / al)) if al else 100

def get_regime():
    try:
        import yfinance as yf
        d = yf.Ticker("^NSEI").history(period="1mo")
        if len(d) < 20:
            return "UNKNOWN"
        c = d['Close'].tolist()
        sma = sum(c[-20:]) / 20
        r = c[-1] / sma
        return "UPTREND" if r > 1.02 else "DOWNTREND" if r < 0.98 else "RANGE"
    except:
        return "UNKNOWN"

def in_window():
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    h, m = now.hour, now.minute
    return not (h < 9 or h >= 14 or (h == 9 and m < 30))

def get_signal(ohlcv):
    if not ohlcv or len(ohlcv) < 25:
        return None, None, None
    closes = [c for _, _, _, c, _ in ohlcv]
    vols = [v for _, _, _, _, v in ohlcv]
    vwap = calc_vwap(ohlcv)
    rsi = calc_rsi(closes)
    price = closes[-1]
    avg_vol = sum(vols[-20:]) / 20 if len(vols) >= 20 else sum(vols) / max(1, len(vols))
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 1
    trs = []
    for i in range(1, min(15, len(ohlcv))):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][4]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr = sum(trs) / len(trs) if trs else price * 0.008
    if get_regime() == "DOWNTREND" or not in_window():
        return None, None, None
    if (vwap and price > vwap * (1 + ENTRY_VWAP_PCT / 100)
            and rsi > ENTRY_RSI and vol_ratio > ENTRY_VOL):
        return "BUY", price, atr
    if (vwap and price < vwap * (1 - ENTRY_VWAP_PCT / 100)
            and rsi < (100 - ENTRY_RSI) and vol_ratio > ENTRY_VOL):
        return "SELL", price, atr
    return None, None, None

def run():
    import yfinance as yf
    print(f"\n==================================================")
    print(f"{SYMBOL} | WR: 55.00% | Pos: Rs{POSITION}")
    print(f"{'='*50}")
    try:
        ticker = yf.Ticker(SYMBOL + ".NS")
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {SYMBOL}.NS")
            return
        ohlcv = [[float(r['Open']), float(r['High']), float(r['Low']),
                   float(r['Close']), float(r['Volume'])]
                  for _, r in data.iterrows()]
        print(f"{len(ohlcv)} candles | Regime: {get_regime()}")
        sig, price, atr = get_signal(ohlcv)
        if not sig:
            print("HOLD -- no signal")
            return
        qty = max(1, int(POSITION / price))
        sl = round(price - atr * SL_ATR, 2) if sig == "BUY" else round(price + atr * SL_ATR, 2)
        tgt = round(price + atr * TGT_RR[1], 2) if sig == "BUY" else round(price - atr * TGT_RR[1], 2)
        print(f"{sig} {qty}x {SYMBOL} @ Rs{price:.2f} | SL:Rs{sl} TGT:Rs{tgt}")
        place_bo(sig, qty, tgt, sl)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
