#!/usr/bin/env python3
"""
RELIANCE.NS — VWAP + EMA20 Breakout BUY
Market: INTRADAY | Exchange: NSE
Stop: -0.8% | Target: +2.4% | Time Exit: 2:30 PM IST

Run: python3 STRATEGY_RELIANCE.py
"""
import os, sys, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────
SYMBOL    = "RELIANCE.NS"
EXCHANGE  = "NSE"
POSITION  = 7000          # ₹7,000 notional
STOP_PCT  = 0.008        # 0.8% stop loss
TGT_PCT   = 0.024        # 2.4% target (3:1 R:R)
ENTRY_VWAP_PCT = 0.005   # price > VWAP + 0.5%
ENTRY_RSI_MIN  = 45      # RSI must be > 45
ENTRY_RSI_MAX  = 65      # RSI must be < 65 (not overbought)

GROWW_KEY    = os.getenv("GROWW_API_KEY", "e31ff23b086b406c8874b2f6d8495313")
GROWW_SECRET = os.getenv("GROWW_API_SECRET", "7*Zf3%-VuyCN%2Yrl0M$^oywYUokW_Bc")
API_BASE = "https://api.groww.in/v1"

# ── Indicator Library ─────────────────────────────────────────────────────
def calc_atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs)/max(len(trs), 1)

def calc_rsi(prices, period=14):
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains  = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    rs = avg_g / avg_l if avg_l > 0 else 100
    return 100 - 100 / (1 + rs)

def calc_vwap(highs, lows, closes, vols):
    cum_pv = sum(((highs[i] + lows[i] + closes[i]) / 3) * vols[i] for i in range(-20, 0))
    cum_v  = sum(vols[i] for i in range(-20, 0))
    return cum_pv / cum_v if cum_v > 0 else closes[-1]

def calc_ema20(closes):
    ema = sum(closes[-20:]) / 20
    k = 2 / 21
    for c in closes[-21:-1]:
        ema = c * k + ema * (1 - k)
    return ema

# ── Groww API ─────────────────────────────────────────────────────────────
def groww_auth():
    import hmac, hashlib, base64
    ts = str(int(time.time() * 1000))
    sig = hmac.new(GROWW_SECRET.encode(), (GROWW_KEY + ts).encode(), hashlib.sha256).digest()
    resp = requests.post(
        f"{API_BASE}/user/tokens",
        headers={
            "Content-Type": "application/json",
            "X-Groww-Auth-Type": "signature",
            "X-Api-Key": GROWW_KEY,
            "X-Request-Timestamp": ts,
            "X-Request-Signature": base64.b64encode(sig).decode(),
        },
        json={"clientId": GROWW_KEY, "clientSecret": GROWW_SECRET, "grantType": "client_credentials"},
        timeout=15
    )
    return resp.json().get("access_token") if resp.status_code == 200 else None

def groww_quote(exchange, symbol, token):
    resp = requests.get(
        f"{API_BASE}/quote/{exchange}",
        headers={"Authorization": f"Bearer {token}", "X-Api-Key": GROWW_KEY},
        params={"symbol": symbol},
        timeout=10
    )
    return resp.json() if resp.status_code == 200 else None

def place_bo(token, exchange, symbol, trans, qty, target, sl, trailing_sl=0.3, trailing_tgt=0.5):
    resp = requests.post(
        f"{API_BASE}/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Api-Key": GROWW_KEY},
        json={
            "exchange": exchange, "symbol": symbol,
            "product": "INTRADAY", "orderType": "BO",
            "transactionType": trans, "quantity": qty,
            "targetPrice": round(target, 2),
            "stopLossPrice": round(sl, 2),
            "trailingTarget": trailing_tgt,
            "trailingStopLoss": trailing_sl,
            "validity": "DAY",
        },
        timeout=15
    )
    if resp.status_code in (200, 201):
        d = resp.json()
        print(f"[GROWW] ✓ {trans} {qty}x {symbol} @ {target} [SL:{sl}] → {d.get('orderId', 'ok')}")
        return d
    print(f"[GROWW] ✗ {trans} {symbol}: {resp.status_code} {resp.text[:150]}")
    return None

def paper_trade(signal, price, qty):
    print(f"[PAPER] {signal} {qty}x {SYMBOL} @ Rs{price:.2f}")
    return {"orderId": f"PAPER_{int(time.time())}", "status": "PAPER"}

# ── Data Fetch ─────────────────────────────────────────────────────────────
def fetch_yfinance(symbol):
    import yfinance as yf
    tk = yf.Ticker(symbol)
    df = tk.history(period="60d", interval="1d")
    if df.empty:
        df = tk.history(period="5d", interval="15m")
    return df

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    print(f"\n{'='*60}")
    print(f"RELIANCE.NS  |  {ist.strftime('%H:%M IST')}  |  VWAP+EMA20 BUY")
    print(f"{'='*60}")

    # Fetch data
    df = fetch_yfinance(SYMBOL)
    if df.empty:
        print("No data"); return

    closes = list(df["Close"])
    highs  = list(df["High"])
    lows   = list(df["Low"])
    vols   = list(df["Volume"])
    price  = float(closes[-1])

    # Indicators
    rsi  = float(calc_rsi(closes))
    atr  = float(calc_atr(highs, lows, closes))
    vwap = float(calc_vwap(highs, lows, closes, vols))
    ema20 = float(calc_ema20(closes))

    # Entry conditions
    cond_vwap = price > vwap * (1 + ENTRY_VWAP_PCT)
    cond_rsi = ENTRY_RSI_MIN < rsi < ENTRY_RSI_MAX
    cond_trend = price > ema20 * 0.995

    print(f"LTP:    Rs{price:.2f}")
    print(f"VWAP:   Rs{vwap:.2f}  {'✓' if cond_vwap else '✗'} (need > {vwap*(1+ENTRY_VWAP_PCT):.2f})")
    print(f"EMA20:  Rs{ema20:.2f}  {'✓' if cond_trend else '✗'}")
    print(f"RSI:    {rsi:.1f}  {'✓' if cond_rsi else '✗'}")
    print(f"ATR:    Rs{atr:.2f}")

    if not (cond_vwap and cond_rsi and cond_trend):
        print("Conditions not met — HOLD"); return

    # Time exit check
    if ist.time() >= __import__("datetime").time(14, 30):
        print("2:30 PM IST — time exit, no new entries"); return

    sl     = round(price * (1 - STOP_PCT), 2)
    target = round(price * (1 + TGT_PCT), 2)
    qty    = max(1, int(POSITION / price))

    print(f"\nSignal:  BUY")
    print(f"Entry:   Rs{price:.2f}")
    print(f"Stop:    Rs{sl:.2f}  ({STOP_PCT*100:.1f}%)")
    print(f"Target:  Rs{target:.2f}  ({TGT_PCT*100:.1f}%, 3:1 R:R)")
    print(f"Qty:     {qty}")

    # Try live Groww execution
    token = groww_auth()
    if token:
        place_bo(token, EXCHANGE, SYMBOL, "BUY", qty, target, sl)
    else:
        paper_trade("BUY", price, qty)

if __name__ == "__main__":
    main()
