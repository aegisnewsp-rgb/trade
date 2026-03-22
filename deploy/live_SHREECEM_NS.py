#!/usr/bin/env python3
"""Live Trading Script — SHREECEM"""
import yfinance
YFINANCE_AVAILABLE = True

def get_signal():
    """Generate signal for SHREECEM"""
    try:
        ticker = yfinance.Ticker("SHREECEM.NS")
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
        print(f"SIGNAL: {sig} SHREECEM @ Rs{price:.2f}")
    else:
        print(f"SHREECEM: No signal")

if __name__ == "__main__":
    main()
