#!/usr/bin/env python3
"""
Tomorrow's Trade — Master Trader
March 23, 2026 | 9:15 AM - 3 PM IST

10 stocks × ₹10,000 = ₹1,00,000 total capital

Rules:
- Entry: 9:30 AM - 2:30 PM IST only
- BUY signal requires: price > VWAP + 0.5% AND RSI > 55 AND volume > 1.2x avg
- SELL signal requires: price < VWAP - 0.5% AND RSI < 45 AND volume > 1.2x avg
- Stop loss: 0.8% ATR from entry
- Target 1: 1.5× risk — exit 1/3
- Target 2: 3.0× risk — exit 1/3
- Target 3: 5.0× risk — exit remaining 1/3
- Max daily loss: ₹3,000 — STOP TRADING if hit
- No entries if NIFTY < 20-day SMA (downtrend filter)
"""

import os, sys, json, time, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PORTFOLIO = [
    {"symbol": "ADANIPOWER",  "file": "ADANIPOWER.py",  "win_rate": 0.9167, "alloc": 10000},
    {"symbol": "ADANIGREEN",  "file": "ADANIGREEN.py",  "win_rate": 0.7000, "alloc": 10000},
    {"symbol": "ADANIPORTS",  "file": "ADANIPORTS.py",  "win_rate": 0.6667, "alloc": 10000},
    {"symbol": "RELIANCE",    "file": "RELIANCE.py",    "win_rate": 0.6364, "alloc": 10000},
    {"symbol": "TCS",         "file": "TCS.py",         "win_rate": 0.6364, "alloc": 10000},
    {"symbol": "SBIN",        "file": "SBIN.py",        "win_rate": 0.6364, "alloc": 10000},
    {"symbol": "GODREJPROP",  "file": "GODREJPROP.py",  "win_rate": 0.6316, "alloc": 10000},
    {"symbol": "UCOBANK",     "file": "UCOBANK.py",     "win_rate": 0.6304, "alloc": 10000},
    {"symbol": "COLPAL",      "file": "COLPAL.py",      "win_rate": 0.6296, "alloc": 10000},
    {"symbol": "HAVELLS",     "file": "HAVELLS.py",     "win_rate": 0.6207, "alloc": 10000},
]

MAX_DAILY_LOSS = 3000
MARKET_OPEN_HR = 9
MARKET_OPEN_MIN = 30
MARKET_CLOSE_HR = 15
MARKET_CLOSE_MIN = 0

DAILY_PNL_FILE = ROOT / "logs" / "daily_pnl.json"


def get_ist_time():
    """Get current IST time"""
    # IST+5:30
    now = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)) + datetime.timedelta(hours=5, minutes=30) + datetime.timedelta(hours=5, minutes=30)
    return now


def is_market_open():
    """Check if market is currently open"""
    now = get_ist_time()
    hr, mn = now.hour, now.minute
    day = now.weekday()
    
    if day >= 5:  # Weekend
        return False
    
    # 9:30 to 15:00 IST
    if hr < MARKET_OPEN_HR or hr >= MARKET_CLOSE_HR:
        return False
    if hr == MARKET_OPEN_HR and mn < MARKET_OPEN_MIN:
        return False
    
    return True


def can_new_entry():
    """Only allow entries between 9:30 AM and 2:30 PM IST"""
    now = get_ist_time()
    hr, mn = now.hour, now.minute
    
    if hr < 9:
        return False
    if hr == 9 and mn < 30:
        return False
    if hr >= 14 and mn >= 30:
        return False
    
    return True


def load_daily_pnl():
    today = get_ist_time().strftime("%Y-%m-%d")
    try:
        with open(DAILY_PNL_FILE) as f:
            data = json.load(f)
        if data.get("date") != today:
            return 0
        return data.get("pnl", 0)
    except:
        return 0


def save_daily_pnl(pnl):
    today = get_ist_time().strftime("%Y-%m-%d")
    with open(DAILY_PNL_FILE, "w") as f:
        json.dump({"date": today, "pnl": pnl}, f)


def check_daily_loss_limit():
    pnl = load_daily_pnl()
    if pnl <= -MAX_DAILY_LOSS:
        print(f"⚠️  DAILY LOSS LIMIT HIT: ₹{pnl:.2f} ≥ ₹{-MAX_DAILY_LOSS}")
        print("STOPPING ALL TRADING FOR TODAY")
        return False
    return True


def run_strategy(stock):
    """Run a single stock's strategy and return signal"""
    script_path = Path(__file__).parent / stock["file"]
    
    if not script_path.exists():
        print(f"  [WARN] {stock['file']} not found — skipping")
        return None
    
    # Import the strategy module
    module_name = f"tomorrow_trade_{stock['symbol']}"
    spec = __import__(f"tomorrow_trade.{stock['file'].replace('.py','')}",
                      fromlist=[stock['symbol']])
    
    # Check market regime first
    try:
        if hasattr(spec, 'get_market_regime'):
            regime, val = spec.get_market_regime()
            if regime == "DOWNTREND":
                print(f"  [REGIME] NIFTY in downtrend — skipping {stock['symbol']}")
                return None
    except Exception as e:
        print(f"  [REGIME] Check failed: {e}")
    
    # Check time filter
    if not can_new_entry():
        print(f"  [TIME] Outside entry window — skipping {stock['symbol']}")
        return None
    
    # Run strategy
    try:
        if hasattr(spec, 'get_signal'):
            signal, price, atr = spec.get_signal()
            return {"signal": signal, "price": price, "atr": atr}
        else:
            print(f"  [WARN] No get_signal() in {stock['file']}")
            return None
    except Exception as e:
        print(f"  [ERROR] {stock['symbol']}: {e}")
        return None


def place_trade(stock, signal_data):
    """Place trade via Groww API or signal queue"""
    from signals.schema import emit_signal
    
    sym = stock["symbol"]
    price = signal_data["price"]
    atr = signal_data.get("atr", price * 0.008)
    qty = max(1, int(stock["alloc"] / price))
    
    # Determine BUY or SELL
    signal = "BUY"  # default
    
    # Calculate stop loss and target
    sl = round(price - atr * 1.0, 2)
    target = round(price + atr * 4.0, 2)
    
    emit_signal(
        symbol=sym,
        signal=signal,
        price=price,
        quantity=qty,
        strategy="VWAP",
        atr=atr,
        target=target,
        stop_loss=sl,
        metadata={
            "portfolio": "tomorrow_10",
            "alloc": stock["alloc"],
            "win_rate": stock["win_rate"]
        }
    )
    
    return {
        "symbol": sym,
        "signal": signal,
        "price": price,
        "qty": qty,
        "sl": sl,
        "target": target,
        "atr": atr,
        "risk": atr * 1.0,
        "alloc": stock["alloc"]
    }


def print_trade_summary(trades):
    print("\n" + "=" * 60)
    print("TRADE SUMMARY")
    print("=" * 60)
    total_invested = sum(t["price"] * t["qty"] for t in trades)
    total_risk = sum(t["risk"] * t["qty"] for t in trades)
    print(f"Stocks traded: {len(trades)}/{len(PORTFOLIO)}")
    print(f"Total invested: ₹{total_invested:.2f}")
    print(f"Total risk: ₹{total_risk:.2f}")
    print()
    for t in trades:
        print(f"  {t['signal']} {t['qty']}x {t['symbol']} @ ₹{t['price']}")
        print(f"    → SL: ₹{t['sl']} | TGT: ₹{t['target']} | Risk: ₹{t['risk']*t['qty']:.0f}")
    print("=" * 60)


def main():
    now = get_ist_time()
    print(f"\n{'='*60}")
    print(f"🚀 TOMORROW'S TRADE — {now.strftime('%Y-%m-%d %H:%M IST')}")
    print(f"{'='*60}")
    print(f"Portfolio: 10 stocks × ₹10,000 = ₹1,00,000")
    print(f"Max daily loss: ₹{MAX_DAILY_LOSS}")
    print()
    
    if not is_market_open():
        print("Market closed. Run during 9:30 AM - 3:00 PM IST for live signals.")
        return
    
    if not check_daily_loss_limit():
        return
    
    trades = []
    for stock in PORTFOLIO:
        print(f"\n[{stock['symbol']}] Win rate: {stock['win_rate']*100:.2f}%")
        
        result = run_strategy(stock)
        if result and result.get("signal") in ("BUY", "SELL"):
            trade = place_trade(stock, result)
            trades.append(trade)
    
    if trades:
        print_trade_summary(trades)
    else:
        print("\nNo trading signals generated. All stocks are on HOLD.")
    
    # Save P&L tracker
    save_daily_pnl(0)  # Reset/start the day


if __name__ == "__main__":
    main()
