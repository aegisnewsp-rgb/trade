#!/usr/bin/env python3
"""Live Trading Script — SBILIFE (Regime-filtered VWAP)"""
import yfinance
YFINANCE_AVAILABLE = True

# REGIME FILTER (QA iteration — fix 0% WR in DOWNTREND)
NIFTY_SYMBOL = "^NSEI"
SMA_PERIOD   = 20
REGIME_RANGE_SIZE = 0.5

def get_market_regime() -> str:
    try:
        ticker = yf.Ticker(NIFTY_SYMBOL)
        data = ticker.history(period="3mo")
        if len(data) < SMA_PERIOD + 5:
            return "UPTREND"
        closes = data['Close'].tolist()
        sma = sum(closes[-SMA_PERIOD:]) / SMA_PERIOD
        ratio = closes[-1] / sma
        if ratio > 1.02:
            return "UPTREND"
        elif ratio < 0.98:
            return "DOWNTREND"
        return "RANGE"
    except Exception:
        return "UPTREND"

def get_position_multiplier(regime: str) -> float:
    if regime == "DOWNTREND":
        return 0.0
    elif regime == "RANGE":
        return REGIME_RANGE_SIZE
    return 1.0

def calculate_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_vwap(ohlcv: list, period: int = 14) -> float:
    if len(ohlcv) < period:
        return ohlcv[-1]['Close']
    tp_sum = sum((r['High'] + r['Low'] + r['Close']) / 3 for r in ohlcv[-period:])
    vol_sum = sum(r['Volume'] for r in ohlcv[-period:])
    return tp_sum / vol_sum * period if vol_sum > 0 else ohlcv[-1]['Close']

def get_signal():
    """Generate regime-filtered signal for SBILIFE"""
    try:
        regime = get_market_regime()
        pos_mult = get_position_multiplier(regime)
        
        ticker = yfinance.Ticker("SBILIFE.NS")
        d = ticker.history(period="3mo")
        if len(d) < 30:
            return None, None, None, regime, pos_mult
        
        ohlcv = d.to_dict('records')
        closes = [r['Close'] for r in ohlcv]
        price = closes[-1]
        
        vwap = calculate_vwap(ohlcv)
        rsi = calculate_rsi(closes)
        
        # Simple VWAP + RSI signal
        if regime == "DOWNTREND":
            signal = "HOLD"
        elif price > vwap and rsi > 55:
            signal = "BUY"
        elif price < vwap and rsi < 45:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return signal, price, 5.0, regime, pos_mult
    except Exception as e:
        return None, None, None, "UPTREND", 1.0

def main():
    sig, price, atr, regime, pos_mult = get_signal()
    if sig and sig != "HOLD":
        print(f"SIGNAL: {sig} SBILIFE @ Rs{price:.2f} | Regime: {regime} | Mult: {pos_mult}")
    elif sig == "HOLD":
        print(f"SBILIFE: HOLD (Regime: {regime}, Mult: {pos_mult})")
    else:
        print(f"SBILIFE: No signal")

if __name__ == "__main__":
    main()
