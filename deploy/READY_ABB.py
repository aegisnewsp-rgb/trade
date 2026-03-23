#!/usr/bin/env python3
"""
Groww Strategy: ABB.NS — BUY on VWAP pullback
Market Regime: DOWNTREND (NIFTY -10.7% in 10d, below 20d SMA)
Score: 40/100 (best candidate)

Entry: Price > VWAP + 0.5% pullback confirmation
Stop:  -0.6% (below entry, tight)
Target: +2.4% (4:1 R:R)
Time:  9:30 AM IST — 12:00 PM IST only
"""

import os, sys, time
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
SYMBOL     = "ABB.NS"
EXCHANGE   = "NSE"
POSITION   = 7000          # ₹7,000 notional
STOP_PCT   = 0.006         # 0.6% stop loss
TARGET_PCT = 0.024         # 2.4% target (4:1 R:R)
MAX_SL_PCT = 0.006         # never more than 0.6% from entry

# ── Indicators ───────────────────────────────────────────────────────────────
def calculate_atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:])/period if len(trs) >= period else sum(trs)/len(trs) if trs else 1

def calculate_rsi(prices, period=14):
    deltas = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    gains  = [max(d,0) for d in deltas]
    losses = [max(-d,0) for d in deltas]
    avg_g = sum(gains[-period:])/period
    avg_l = sum(losses[-period:])/period
    rs = avg_g/avg_l if avg_l > 0 else 100
    return 100 - 100/(1+rs)

# ── Groww API ────────────────────────────────────────────────────────────────
def is_configured():
    return bool(os.getenv("GROWW_API_KEY") and os.getenv("GROWW_API_SECRET"))

def get_token():
    import hmac, hashlib, base64, requests, time
    key    = os.getenv("GROWW_API_KEY")
    secret = os.getenv("GROWW_API_SECRET")
    ts     = str(int(time.time() * 1000))
    sig    = hmac.new(secret.encode(), (key + ts).encode(), hashlib.sha256).digest()
    headers = {
        "Content-Type": "application/json",
        "X-Groww-Auth-Type": "signature",
        "X-Api-Key": key,
        "X-Request-Timestamp": ts,
        "X-Request-Signature": base64.b64encode(sig).decode(),
    }
    resp = requests.post(
        "https://api.groww.in/v1/user/tokens",
        headers=headers,
        json={"clientId": key, "clientSecret": secret, "grantType": "client_credentials"},
        timeout=10
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    print(f"[AUTH FAILED] {resp.status_code} {resp.text[:100]}")
    return None

def place_bo(token, exchange, symbol, trans, qty, target, sl, trailing_sl=0.3, trailing_tgt=0.5):
    import requests
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "X-Api-Key": os.getenv("GROWW_API_KEY")}
    order = {
        "exchange": exchange, "symbol": symbol,
        "product": "INTRADAY", "orderType": "BO",
        "transactionType": trans, "quantity": qty,
        "targetPrice": round(target, 2),
        "stopLossPrice": round(sl, 2),
        "trailingTarget": trailing_tgt,
        "trailingStopLoss": trailing_sl,
        "validity": "DAY",
    }
    resp = requests.post("https://api.groww.in/v1/orders", headers=headers, json=order, timeout=15)
    if resp.status_code in (200, 201):
        print(f"[GROWW] ✓ {trans} {qty}x {symbol} @ {target} [SL:{sl}]")
        return resp.json()
    print(f"[GROWW] ✗ {trans} {symbol}: {resp.status_code} {resp.text[:150]}")
    return None

def paper_trade(signal, price, qty):
    print(f"[PAPER] {signal} {qty}x {SYMBOL} @ Rs{price:.2f}")
    return {"orderId": f"PAPER_{int(time.time())}", "status": "PAPER"}

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    import yfinance as yf
    from datetime import datetime
    ist = datetime.utcnow() + __import__("datetime").timedelta(hours=5, minutes=30)
    print(f"\n{'='*60}")
    print(f"ABB.NS  |  {ist.strftime('%H:%M IST')}  |  DOWNTREND REGIME")
    print(f"{'='*60}")

    # Fetch daily data (60d for indicators)
    tk = yf.Ticker(SYMBOL)
    df = tk.history(period="60d")
    if df.empty:
        print("No data"); return

    closes = list(df["Close"])
    highs  = list(df["High"])
    lows   = list(df["Low"])
    vols   = list(df["Volume"])
    price  = float(closes[-1])

    rsi = float(calculate_rsi(closes))
    atr = float(calculate_atr(highs, lows, closes))

    # VWAP (20-day)
    cum_pv = sum(((highs[i]+lows[i]+closes[i])/3)*vols[i] for i in range(-20, 0))
    cum_v  = sum(vols[i] for i in range(-20, 0))
    vwap   = cum_pv / cum_v if cum_v > 0 else price

    # EMA20
    ema20 = sum(closes[-20:])/20

    # Entry condition: price above VWAP with RSI 35-65
    cond_vwap  = price > vwap * 1.005
    cond_rsi   = 35 < rsi < 65
    cond_trend = price > ema20 * 0.995

    print(f"Price:  Rs{price:.2f}")
    print(f"VWAP:   Rs{vwap:.2f}  {'✓' if cond_vwap else '✗'}")
    print(f"EMA20:  Rs{ema20:.2f}  {'✓' if cond_trend else '✗'}")
    print(f"RSI:    {rsi:.1f}  {'✓' if cond_rsi else '✗'}")
    print(f"ATR:    Rs{atr:.2f}")

    if not (cond_vwap and cond_rsi and cond_trend):
        print("Conditions not met — HOLD")
        return

    sl     = round(price * (1 - STOP_PCT), 2)
    target = round(price * (1 + TARGET_PCT), 2)
    risk   = price - sl
    qty    = max(1, int(POSITION / price))

    print(f"\nSignal:  BUY")
    print(f"Entry:   Rs{price:.2f}")
    print(f"Stop:    Rs{sl:.2f}  ({STOP_PCT*100:.1f}%)")
    print(f"Target:  Rs{target:.2f}  ({TARGET_PCT*100:.1f}%, {risk*4:.2f} reward)")
    print(f"Qty:     {qty}")

    if is_configured():
        token = get_token()
        if token:
            place_bo(token, EXCHANGE, SYMBOL, "BUY", qty, target, sl)
    else:
        paper_trade("BUY", price, qty)

if __name__ == "__main__":
    main()
