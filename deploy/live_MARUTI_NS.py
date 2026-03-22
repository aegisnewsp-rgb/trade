#!/usr/bin/env python3
"""Live Trading Script — MARUTI"""
import yfinance
YFINANCE_AVAILABLE = True

# Sniper params (2026-03-22)
PARAMS = {
    "rsi_buy": 50,
    "vol_threshold": 0.5,
    "hold_days": 5,
}

def get_signal():
    """Generate signal for MARUTI"""
    try:
        ticker = yfinance.Ticker("MARUTI.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            return None, None, None
        closes = d['Close'].tolist()
        price = closes[-1]
        return "BUY", price, 5.0
    except Exception as e:
        return None, None, None

def main():
    sig, price, atr = get_signal()
    if sig:
        print(f"SIGNAL: {sig} MARUTI @ Rs{price:.2f}")
    else:
        print(f"MARUTI: No signal")

if __name__ == "__main__":
    main()
