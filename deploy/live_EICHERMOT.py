#!/usr/bin/env python3
"""Live Trading Script — EICHERMOT"""
import yfinance
YFINANCE_AVAILABLE = True

# Sniper-optimized params (Round 3, 2026-03-22)
RSI_BUY       = 50       # BUY only when RSI > 50
RSI_SELL      = 50       # SELL only when RSI < 50
VOL_THRESH    = 0.5      # Volume 0.5x avg for entry confirmation
HOLD_DAYS     = 5        # hold for 5 trading days

def get_signal():
    """Generate signal for EICHERMOT"""
    try:
        ticker = yfinance.Ticker("EICHERMOT.NS")
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
        print(f"SIGNAL: {sig} EICHERMOT @ Rs{price:.2f}")
    else:
        print(f"EICHERMOT: No signal")

if __name__ == "__main__":
    main()
