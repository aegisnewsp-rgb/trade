
# OPTIMIZED PARAMS (sniper scan — 2yr data)
RSI_BUY = 50
RSI_SELL = 50
VOL_THRESH = 0.5
HOLD_DAYS = 5
VWAP_TOL = 0.005
SL_PCT = 1.0
TGT_PCT = 3.0
TRAIL_ATR_MULT = 0.3
BEST_ENTRY_START = "09:30"
BEST_ENTRY_END = "14:30"

#!/usr/bin/env python3
"""Live Trading Script — POWERGRID"""
import yfinance
YFINANCE_AVAILABLE = True

def get_signal():
    """Generate signal for POWERGRID"""
    try:
        ticker = yfinance.Ticker("POWERGRID.NS")
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
        print(f"SIGNAL: {sig} POWERGRID @ Rs{price:.2f}")
    else:
        print(f"POWERGRID: No signal")

if __name__ == "__main__":
    main()
