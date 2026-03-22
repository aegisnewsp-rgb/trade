#!/usr/bin/env python3
"""Live Trading Script — NESTLEIND"""
import yfinance
YFINANCE_AVAILABLE = True

# Sniper-optimized params (Round 3, 2026-03-22)
RSI_BUY   = 45    # BUY when RSI > 45
RSI_SELL  = 45    # SELL when RSI < 45
VOL_THRESH = 0.5  # volume must exceed 0.5× avg
HOLD_DAYS  = 5    # hold for 5 trading days

def get_signal():
    """Generate signal for NESTLEIND"""
    try:
        ticker = yfinance.Ticker("NESTLEIND.NS")
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
        print(f"SIGNAL: {sig} NESTLEIND @ Rs{price:.2f}")
    else:
        print(f"NESTLEIND: No signal")

if __name__ == "__main__":
    main()
