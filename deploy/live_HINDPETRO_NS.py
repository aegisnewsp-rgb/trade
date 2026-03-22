#!/usr/bin/env python3
"""Live Trading Script — HINDPETRO"""
import yfinance
YFINANCE_AVAILABLE = True

def get_signal():
    """Generate signal for HINDPETRO"""
    try:
        ticker = yfinance.Ticker("HINDPETRO.NS")
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
        print(f"SIGNAL: {sig} HINDPETRO @ Rs{price:.2f}")
    else:
        print(f"HINDPETRO: No signal")

if __name__ == "__main__":
    main()
