#!/usr/bin/env python3
import yfinance as yf

def calc_rsi(prices, period=14):
    deltas = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    gains = [max(d,0) for d in deltas]
    losses = [max(-d,0) for d in deltas]
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    rs = avg_gain/avg_loss if avg_loss > 0 else 100
    return 100 - 100/(1+rs)

def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes))]
    return sum(trs[-period:])/period

scripts = {
    'RELIANCE.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 50, 'vwap_pct': 0.005},
    'SBIN.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 45, 'vwap_pct': 0.003},
    'ADANIPOWER.NS': {'sl_pct': 0.01, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'TATASTEEL.NS': {'sl_pct': 0.01, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'ICICIBANK.NS': {'sl_pct': 0.006, 'tgt_mult': 4.0, 'rsi_buy': 35, 'vwap_pct': 0.005},
    'HDFCBANK.NS': {'sl_pct': 0.006, 'tgt_mult': 4.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'COALINDIA.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'SBILIFE.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'ABB.NS': {'sl_pct': 0.006, 'tgt_mult': 4.0, 'rsi_buy': 35, 'vwap_pct': 0.005},
    'GRASIM.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'CIPLA.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
    'LUPIN.NS': {'sl_pct': 0.008, 'tgt_mult': 3.0, 'rsi_buy': 40, 'vwap_pct': 0.005},
}

print('='*70)
print('PRE-MARKET SIGNAL SCAN (60d daily data)')
print('='*70)

nifty = yf.Ticker('^NSEI')
ndf = nifty.history(period='20d')
nifty_above_sma20 = ndf['Close'].iloc[-1] > ndf['Close'].mean()
print(f'NIFTY: {ndf["Close"].iloc[-1]:.2f} | Above SMA20: {nifty_above_sma20}')
print()

buy_signals = []
sell_signals = []

for sym, p in scripts.items():
    try:
        tk = yf.Ticker(sym)
        df = tk.history(period='60d')
        if df.empty:
            continue

        closes = df['Close'].tolist()
        highs = df['High'].tolist()
        lows = df['Low'].tolist()
        vols = df['Volume'].tolist()

        price = closes[-1]
        rsi = calc_rsi(closes)[-1]
        atr = calc_atr(highs, lows, closes)

        cum_pv = sum(((highs[i]+lows[i]+closes[i])/3)*vols[i] for i in range(-20,0))
        cum_v = sum(vols[i] for i in range(-20,0))
        vwap = cum_pv/cum_v

        ema20 = closes[-1]
        k = 2/21
        for c in closes[-21:-1]:
            ema20 = c*k + ema20*(1-k)

        vwap_cross = price > vwap * (1 + p['vwap_pct'])
        rsi_ok = rsi > p['rsi_buy']
        trend_up = price > ema20

        sl = round(price * (1 - p['sl_pct']), 2)
        tgt = round(price + (price - sl) * p['tgt_mult'], 2)
        risk = price - sl
        reward = tgt - price
        rr = reward/risk if risk > 0 else 0

        if vwap_cross and rsi_ok and trend_up:
            signal = 'BUY'
            conf = sum([vwap_cross, rsi_ok, trend_up])
            buy_signals.append((sym, price, sl, tgt, rr, rsi, atr))
        elif not vwap_cross and not rsi_ok and not trend_up:
            signal = 'SELL'
            conf = 3
            sell_signals.append((sym, price, sl, tgt, rr, rsi, atr))
        else:
            signal = 'HOLD'
            conf = 0

        star = '  ★' if signal != 'HOLD' else ''
        print(f"{sym:<20} {signal:<5} {price:>8.2f} | RSI:{rsi:>5.1f} | VWAP:{vwap:>8.2f} | ATR:{atr:>6.2f}")
        print(f"  SL:{sl:>8.2f} ({p['sl_pct']*100:.1f}%) | TGT:{tgt:>8.2f} ({p['tgt_mult']}:1 R:R {rr:.1f}){star}")

    except Exception as e:
        print(f'{sym}: ERROR {e}')

print()
print('='*70)
print('ACTIONABLE SIGNALS:')
print('='*70)
if buy_signals:
    print('BUY:')
    for s in sorted(buy_signals, key=lambda x: -x[4]):
        print(f"  {s[0]:<20} Price:{s[1]:>8.2f} | SL:{s[2]:>8.2f} | TGT:{s[3]:>8.2f} | RR:{s[4]:.1f}:1 | RSI:{s[5]:.1f}")
else:
    print('No BUY signals')
if sell_signals:
    print('SELL:')
    for s in sorted(sell_signals, key=lambda x: -x[4]):
        print(f"  {s[0]:<20} Price:{s[1]:>8.2f} | SL:{s[2]:>8.2f} | TGT:{s[3]:>8.2f} | RR:{s[4]:.1f}:1 | RSI:{s[5]:.1f}")
else:
    print('No SELL signals')
