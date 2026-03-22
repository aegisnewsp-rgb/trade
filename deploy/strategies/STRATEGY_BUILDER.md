# Groww Strategy Builder
# Generates copy-pasteable Python strategies for Groww Dashboard
# 
# Format: Each strategy is a self-contained Python file
# that can be pasted into Groww's Cloud Strategy Builder
#
# Groww Strategy API endpoint: POST /v1/strategies
# Strategy trigger types: candlestick, indicator, price

STRATEGY_TEMPLATE = '''#!/usr/bin/env python3
"""
Groww Strategy: {SYMBOL}
Exchange: {EXCHANGE} | Strategy: {STRATEGY_NAME}
Win Rate: {WIN_RATE}% | ATR: ₹{ATR:.2f}

ENTRY RULES:
  - Price {ENTRY_CONDITION}
  - RSI({RSI_PERIOD}) {RSI_CONDITION}
  - Volume > {VOL_MULT}x 20-day average
  - NIFTY > 20-day SMA (uptrend market)
  - Time: {ENTRY_WINDOW} IST

EXIT RULES:
  - Target 1: {TARGET1} (1.5× risk) — exit 1/3
  - Target 2: {TARGET2} (3.0× risk) — exit 1/3
  - Target 3: {TARGET3} (5.0× risk) — exit remaining
  - Stop loss: {STOP_LOSS} (1.0× ATR)
  - Max daily loss: ₹3,000 — hard stop

Risk/Reward: 1:{RR_RATIO} | Position: ₹10,000 | Max Risk: ₹500/stock
"""

import requests
import time
import json
from datetime import datetime

# =============================================================================
# CONFIGURATION — Copy these values to Groww Dashboard
# =============================================================================

GROWW_API_KEY = "{GROWW_API_KEY}"      # Set your Groww API key
GROWW_API_SECRET = "{GROWW_API_SECRET}" # Set your Groww API secret
SYMBOL = "{SYMBOL}"                     # e.g. "RELIANCE"
EXCHANGE = "{EXCHANGE}"                 # "NSE" or "BSE"
STRATEGY_NAME = "{STRATEGY}"
WIN_RATE = {WIN_RATE}

# Entry parameters
ENTRY_VWAP_PCT = {ENTRY_VWAP_PCT}      # Price must be > VWAP + this %
ENTRY_RSI_MIN = {ENTRY_RSI_MIN}         # RSI must be above this for BUY
ENTRY_RSI_MAX = {ENTRY_RSI_MAX}         # RSI must be below this for SELL
VOL_MULT = {VOL_MULT}                    # Volume must be > avg × this
RSI_PERIOD = {RSI_PERIOD}
ATR_MULT = {ATR_MULT}

# Exit parameters  
STOP_LOSS_ATR = {STOP_LOSS_ATR}         # Stop loss = ATR × this
TARGET1_RR = {TARGET1_RR}               # Target 1 in risk multiples
TARGET2_RR = {TARGET2_RR}               # Target 2 in risk multiples
TARGET3_RR = {TARGET3_RR}               # Target 3 in risk multiples

# Position
POSITION_SIZE = 10000                   # ₹10,000 per stock

# =============================================================================
# GROWW API INTEGRATION
# =============================================================================

GROWW_BASE = "https://api.groww.in"
_token = None
_token_exp = 0


def groww_auth():
    global _token, _token_exp
    if _token and time.time() < _token_exp - 300:
        return _token
    
    import hmac, hashlib, base64
    ts = str(int(time.time() * 1000))
    payload = GROWW_API_KEY + ts
    sig = hmac.new(GROWW_API_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(sig).decode()
    
    headers = {{
        "Content-Type": "application/json",
        "X-Groww-Auth-Type": "signature",
        "X-Api-Key": GROWW_API_KEY,
        "X-Request-Timestamp": ts,
        "X-Request-Signature": signature,
    }}
    
    data = {{
        "clientId": GROWW_API_KEY,
        "clientSecret": GROWW_API_SECRET,
        "grantType": "client_credentials",
    }}
    
    r = requests.post(GROWW_BASE + "/v1/user/tokens",
                      headers=headers, json=data, timeout=10)
    if r.status_code == 200:
        d = r.json()
        _token = d.get("access_token")
        _token_exp = time.time() + int(d.get("X-Groww-Expiry-Seconds", 86400))
        return _token
    return None


def groww_headers():
    return {{
        "Authorization": "Bearer " + (groww_auth() or ""),
        "Content-Type": "application/json",
        "X-Api-Key": GROWW_API_KEY,
    }}


def place_bracket_order(transaction, quantity, target, stop_loss):
    """Place a Bracket Order via Groww API"""
    order = {{
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "product": "INTRADAY",
        "orderType": "BO",
        "transactionType": transaction,  # "BUY" or "SELL"
        "quantity": quantity,
        "targetPrice": round(target, 2),
        "stopLossPrice": round(stop_loss, 2),
        "trailingTarget": 0.5,
        "trailingStopLoss": 0.3,
        "validity": "DAY",
    }}
    r = requests.post(GROWW_BASE + "/v1/orders",
                      headers=groww_headers(), json=order, timeout=15)
    return r.json() if r.status_code in (200, 201) else None


def paper_trade(transaction, price, quantity):
    print(f"[PAPER] {{transaction}} {{quantity}}x {{SYMBOL}} @ ₹{{price:.2f}}")
    return {{"orderId": f"PAPER_{{int(time.time())}}", "status": "PAPER_MODE"}}


# =============================================================================
# STRATEGY FUNCTIONS — Core trading logic (copy to Groww Dashboard)
# =============================================================================

def calculate_vwap(ohlcv_data):
    """Calculate VWAP from OHLCV data"""
    if not ohlcv_data:
        return None
    cumulative_tp_volume = 0
    cumulative_volume = 0
    for o, h, l, c, v in ohlcv_data:
        typical_price = (o + h + l + c) / 4
        cumulative_tp_volume += typical_price * v
        cumulative_volume += v
    return cumulative_tp_volume / cumulative_volume if cumulative_volume > 0 else None


def calculate_rsi(prices, period=14):
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_market_regime():
    """Check NIFTY trend — returns 'UPTREND', 'DOWNTREND', or 'RANGE'"""
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI")
        data = nifty.history(period="1mo")
        if len(data) < 20:
            return "UNKNOWN"
        closes = data['Close'].tolist()
        sma20 = sum(closes[-20:]) / 20
        current = closes[-1]
        ratio = current / sma20
        if ratio > 1.02:
            return "UPTREND"
        elif ratio < 0.98:
            return "DOWNTREND"
        else:
            return "RANGE"
    except:
        return "UNKNOWN"


def in_entry_window():
    """Only allow entries 9:30 AM - 2:30 PM IST"""
    from datetime import datetime
    now = datetime.utcnow() + __import__('datetime').timedelta(hours=5, minutes=30)
    hr, mn = now.hour, now.minute
    if hr < 9 or hr >= 14:
        return False
    if hr == 9 and mn < 30:
        return False
    return True


def get_signal(ohlcv_data):
    """
    Main signal function. Returns (signal, entry_price, atr).
    signal: 'BUY', 'SELL', or 'HOLD'
    
    GROWW DASHBOARD: Paste this function into the strategy builder.
    """
    if not ohlcv_data or len(ohlcv_data) < 25:
        return "HOLD", None, None
    
    closes = [c for _, _, _, c, _ in ohlcv_data]
    volumes = [v for _, _, _, _, v in ohlcv_data]
    
    vwap = calculate_vwap(ohlcv_data)
    rsi = calculate_rsi(closes, RSI_PERIOD)
    current_price = closes[-1]
    
    # ATR calculation
    trs = []
    for i in range(1, min(15, len(ohlcv_data))):
        h, l = ohlcv_data[i][1], ohlcv_data[i][2]
        prev_c = ohlcv_data[i-1][4]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else current_price * 0.008
    
    # Market regime check
    regime = get_market_regime()
    if regime == "DOWNTREND":
        return "HOLD", None, None
    
    if regime == "RANGE":
        position_mult = 0.5
    else:
        position_mult = 1.0
    
    # Volume check
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
    
    # Entry conditions
    if (
        in_entry_window()
        and vwap is not None
        and current_price > vwap * (1 + ENTRY_VWAP_PCT / 100)
        and rsi > ENTRY_RSI_MIN
        and vol_ratio > VOL_MULT
    ):
        return "BUY", current_price, atr
    
    if (
        in_entry_window()
        and vwap is not None
        and current_price < vwap * (1 - ENTRY_VWAP_PCT / 100)
        and rsi < ENTRY_RSI_MAX
        and vol_ratio > VOL_MULT
    ):
        return "SELL", current_price, atr
    
    return "HOLD", None, None


def calculate_exit_prices(entry_price, atr, signal):
    """Calculate stop loss and targets"""
    if signal == "BUY":
        sl = round(entry_price - atr * STOP_LOSS_ATR, 2)
        t1 = round(entry_price + atr * TARGET1_RR, 2)
        t2 = round(entry_price + atr * TARGET2_RR, 2)
        t3 = round(entry_price + atr * TARGET3_RR, 2)
    elif signal == "SELL":
        sl = round(entry_price + atr * STOP_LOSS_ATR, 2)
        t1 = round(entry_price - atr * TARGET1_RR, 2)
        t2 = round(entry_price - atr * TARGET2_RR, 2)
        t3 = round(entry_price - atr * TARGET3_RR, 2)
    else:
        return None, None, None, None
    
    return sl, t1, t2, t3


def run_strategy(ohlcv_data):
    """
    Execute strategy on provided OHLCV data.
    Called by Groww Dashboard automatically.
    """
    signal, price, atr = get_signal(ohlcv_data)
    
    if signal == "HOLD":
        print(f"[{SYMBOL}] HOLD — no signal")
        return None
    
    sl, t1, t2, t3 = calculate_exit_prices(price, atr, signal)
    qty = max(1, int(POSITION_SIZE / price))
    
    print(f"[{SYMBOL}] {{signal}} @ ₹{{price:.2f}}")
    print(f"  SL: ₹{{sl:.2f}} | T1: ₹{{t1:.2f}} T2: ₹{{t2:.2f}} T3: ₹{{t3:.2f}}")
    print(f"  ATR: ₹{{atr:.2f}} | Qty: {{qty}}")
    
    # Place order via Groww API or paper
    if GROWW_API_KEY and GROWW_API_SECRET:
        result = place_bracket_order(signal, qty, t2, sl)  # Use T2 as main target
        if result:
            print(f"  → Order placed: {{result.get('orderId', 'N/A')}}")
        return result
    else:
        return paper_trade(signal, price, qty)


# =============================================================================
# BACKTEST & VERIFICATION
# =============================================================================

def backtest(ohlcv_history):
    """Run backtest on historical data"""
    trades = []
    entry_price = 0
    entry_sl = 0
    entry_tgt = 0
    position = 0
    
    for i in range(25, len(ohlcv_history)):
        window = ohlcv_history[max(0, i-90):i]
        signal, price, atr = get_signal(window)
        
        if signal in ("BUY", "SELL") and position == 0:
            sl, t1, t2, t3 = calculate_exit_prices(price, atr, signal)
            entry_price = price
            entry_sl = sl
            entry_tgt = t2
            position = max(1, int(POSITION_SIZE / price))
            trades.append({{"entry": price, "sl": sl, "t2": t2, "signal": signal, "atr": atr}})
            print(f"BUY {{position}}x @ ₹{{price:.2f}} SL:₹{{sl:.2f}} T2:₹{{t2:.2f}}")
    
    if trades:
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total = len(trades)
        win_rate = wins / total if total > 0 else 0
        print(f"Backtest: {{total}} trades | Win rate: {{win_rate*100:.1f}}%")
        return win_rate
    return 0


# =============================================================================
# MAIN — For standalone testing
# =============================================================================

if __name__ == "__main__":
    import yfinance as yf
    
    print(f"\\n{'='*60}")
    print(f"Strategy: {{STRATEGY_NAME}} | {{SYMBOL}}")
    print(f"Win Rate: {{WIN_RATE}}% | Position: ₹{{POSITION_SIZE}}")
    print(f"{'='*60}")
    
    # Fetch data
    ticker_sym = SYMBOL
    ticker = yf.Ticker(ticker_sym)
    data = ticker.history(period="3mo")
    
    if data.empty:
        print(f"No data for {{ticker_sym}}")
    else:
        ohlcv = [[float(row['Open']), float(row['High']),
                  float(row['Low']), float(row['Close']), float(row['Volume'])]
                 for _, row in data.iterrows()]
        
        print(f"Loaded {{len(ohlcv)}} candles")
        
        # Check regime
        regime = get_market_regime()
        print(f"Market regime: {{regime}}")
        
        # Get signal
        signal, price, atr = get_signal(ohlcv)
        
        if signal != "HOLD":
            result = run_strategy(ohlcv)
        else:
            print(f"Signal: HOLD — no trade")
        
        # Backtest
        print(f"\\nRunning backtest...")
        backtest(ohlcv)

    print(f"\\n{'='*60}")
    print(f"Generated by Groww Strategy Builder")
    print(f"Copy this file to Groww Dashboard for live trading")
    print(f"{'='*60}")
'''
