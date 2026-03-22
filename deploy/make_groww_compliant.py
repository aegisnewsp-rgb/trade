#!/usr/bin/env python3
"""
Make all live_*.py scripts Groww Strategy Dashboard compliant.
Each script will have:
  1. run_strategy(ohlcv) — called by Groww with live OHLCV data
  2. get_signal(ohlcv) — core signal logic
  3. main() — local execution with yfinance fetch
  4. Proper order placement via groww_api
"""
import os, re, glob, shutil

DEPLOY = "/home/node/workspace/trade-project/deploy"
os.chdir(DEPLOY)

BACKUP_DIR = DEPLOY + "/.groww_compliant_backup"
os.makedirs(BACKUP_DIR, exist_ok=True)


# Standard signal function that all scripts will have
STANDARD_GET_SIGNAL = '''
def get_signal(ohlcv):
    """
    Core signal generation — works for any OHLCV data.
    Returns: (signal, price, atr) where signal is "BUY", "SELL", or "HOLD"
    
    Compatible with Groww Dashboard which passes [[O,H,L,C,V], ...] per candle.
    """
    if not ohlcv or len(ohlcv) < 25:
        return "HOLD", None, None
    
    # Unpack OHLCV
    opens   = [c[0] for c in ohlcv]
    highs   = [c[1] for c in ohlcv]
    lows    = [c[2] for c in ohlcv]
    closes  = [c[3] for c in ohlcv]
    volumes = [c[4] for c in ohlcv] if len(ohlcv[0]) > 4 else [1]*len(ohlcv)
    
    price   = closes[-1]
    if price <= 0:
        return "HOLD", None, None
    
    # VWAP
    cum_tp_vol = 0
    cum_vol = 0
    for o, h, l, c, v in ohlcv:
        tp = (o + h + l + c) / 4
        cum_tp_vol += tp * v
        cum_vol += v
    vwap = cum_tp_vol / cum_vol if cum_vol > 0 else price
    
    # RSI
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-14:]]
        losses = [-d if d < 0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = 50 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    else:
        rsi = 50
    
    # ATR
    if len(ohlcv) >= 15:
        trs = []
        for i in range(1, min(15, len(ohlcv))):
            h, l = highs[i], lows[i]
            pc = closes[i-1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else price * 0.008
    else:
        atr = price * 0.008
    
    # Volume
    if len(volumes) >= 20:
        avg_vol = sum(volumes[-20:]) / 20
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
    else:
        vol_ratio = 1
    
    # Entry conditions (configurable via globals)
    vwap_pct = globals().get("ENTRY_VWAP_PCT", 0.5)
    rsi_min  = globals().get("ENTRY_RSI_MIN", 55)
    rsi_max  = globals().get("ENTRY_RSI_MAX", 45)
    vol_min  = globals().get("ENTRY_VOL_MIN", 1.2)
    
    regime = get_market_regime() if "get_market_regime" in dir() else "UPTREND"
    if regime == "DOWNTREND":
        return "HOLD", None, None
    
    # BUY
    if (price > vwap * (1 + vwap_pct / 100)
            and rsi > rsi_min
            and vol_ratio > vol_min):
        return "BUY", price, atr
    
    # SELL
    if (price < vwap * (1 - vwap_pct / 100)
            and rsi < rsi_max
            and vol_ratio > vol_min):
        return "SELL", price, atr
    
    return "HOLD", None, None


def get_market_regime():
    """Check NIFTY trend — UPTREND/DOWNTREND/RANGE"""
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI")
        data = nifty.history(period="1mo")
        if len(data) < 20:
            return "UPTREND"
        closes = data['Close'].tolist()
        sma20 = sum(closes[-20:]) / 20
        ratio = closes[-1] / sma20
        if ratio > 1.02:
            return "UPTREND"
        elif ratio < 0.98:
            return "DOWNTREND"
        return "RANGE"
    except:
        return "UPTREND"


'''

STANDARD_RUN_STRATEGY = '''
def run_strategy(ohlcv):
    """
    Groww Dashboard entry point — called with live OHLCV data.
    ohlcv: [[open, high, low, close, volume], ...] per candle
    
    Returns dict with signal, price, atr, stop_loss, target, quantity.
    """
    signal, price, atr = get_signal(ohlcv)
    
    if signal == "HOLD" or price is None:
        return {"action": "HOLD", "reason": "No signal"}
    
    # Risk management
    risk_per_share = atr * globals().get("SL_ATR_MULT", 1.0)
    
    if signal == "BUY":
        stop_loss = round(price - risk_per_share, 2)
        target   = round(price + atr * globals().get("TGT_RR", 4.0), 2)
    else:  # SELL
        stop_loss = round(price + risk_per_share, 2)
        target   = round(price - atr * globals().get("TGT_RR", 4.0), 2)
    
    position = globals().get("POSITION", 10000)
    quantity = max(1, int(position / price))
    
    # Place order
    try:
        from signals.schema import emit_signal
        result = emit_signal(
            symbol=globals().get("SYMBOL", "UNKNOWN"),
            signal=signal,
            price=price,
            quantity=quantity,
            strategy=globals().get("STRATEGY_NAME", "VWAP"),
            atr=atr,
            target=target,
            stop_loss=stop_loss,
            metadata={"source": "groww_compliant", "regime": get_market_regime()}
        )
    except ImportError:
        try:
            from groww_api import place_bo
            result = place_bo(
                exchange=globals().get("EXCHANGE", "NSE"),
                symbol=globals().get("SYMBOL", "UNKNOWN"),
                transaction=signal,
                quantity=quantity,
                target_price=target,
                stop_loss_price=stop_loss,
            )
        except Exception as e:
            print(f"[PAPER] {signal} {quantity}x @{price} SL:{stop_loss} TGT:{target}")
            result = {"status": "paper"}
    
    return {
        "action": signal,
        "price": price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "target": target,
        "atr": atr,
        "result": result,
    }


'''

STANDARD_MAIN = '''
def main():
    """
    Local execution — fetch yfinance data and run strategy.
    Usage: python3 live_RELIANCE.py
    """
    import sys, yfinance
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
    symbol = globals().get("SYMBOL", Path(__file__).stem.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO"))
    exchange = globals().get("EXCHANGE", "NSE")
    ticker_sym = symbol.replace(".NS", "").replace(".BO", "") + (".NS" if ".NS" in symbol else ".BO")
    
    print(f"\\n{'='*55}")
    print(f"{symbol} | {globals().get('STRATEGY_NAME', 'VWAP')} | Pos: Rs{globals().get('POSITION', 10000)}")
    print(f"{'='*55}")
    
    try:
        ticker = yfinance.Ticker(ticker_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {ticker_sym}")
            return
        
        ohlcv = [[float(row['Open']), float(row['High']),
                   float(row['Low']),  float(row['Close']), float(row['Volume'])]
                  for _, row in data.iterrows()]
        print(f"Candles: {len(ohlcv)} | Regime: {get_market_regime()}")
        
        result = run_strategy(ohlcv)
        
        if result.get("action") != "HOLD":
            print(f"\\nSignal: {result['action']}")
            print(f"Price:  Rs{result['price']:.2f}")
            print(f"Qty:    {result['quantity']}")
            print(f"SL:     Rs{result['stop_loss']:.2f}")
            print(f"TGT:    Rs{result['target']:.2f}")
            print(f"ATR:    Rs{result['atr']:.2f}")
        else:
            print(f"\\nHOLD — no signal generated")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()

'''


def backup_and_patch(filepath):
    """Patch one script to be Groww compliant"""
    with open(filepath) as f:
        content = f.read()
    
    original = content
    
    # Backup
    shutil.copy2(filepath, os.path.join(BACKUP_DIR, os.path.basename(filepath) + ".bak"))
    
    # Remove old run_strategy/get_signal/main if present (replace with standard)
    # Find and remove existing functions
    lines = content.split('\n')
    new_lines = []
    skip_until = []  # stack of function names to skip
    
    for line in lines:
        # Start skipping old functions
        if line.startswith('def get_signal(') or line.startswith('def run_strategy(') or line.startswith('def get_market_regime('):
            skip_until.append(line.split('(')[0].replace('def ', ''))
            continue
        if skip_until:
            # Check if we've reached a new top-level function
            if line.startswith('def ') or line.startswith('class ') or line.startswith('if __name__'):
                skip_until.pop()
                if not skip_until and line.startswith('def '):
                    new_lines.append(line)
                    continue
            if skip_until:
                continue
        
        # Skip old main (we'll add new one at the end)
        if 'if __name__' in line and '__main__' in line:
            # Skip the whole if __name__ block
            new_lines.append('# === Groww compliant main block appended at end ===')
            continue
        
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    # Remove trailing 'if __name__ == ...' block content (we'll replace it)
    main_block_end = content.find('if __name__ == "__main__":')
    if main_block_end != -1:
        content = content[:main_block_end]
    
    # Append standard functions BEFORE the main block
    content = content.rstrip() + '\n' + STANDARD_GET_SIGNAL + '\n' + STANDARD_RUN_STRATEGY + '\n' + STANDARD_MAIN
    
    # Ensure globals() setup exists
    symbol = os.path.basename(filepath).replace('live_', '').replace('.py', '')
    if symbol.endswith('_NS'):
        exchange = 'NSE'
        symbol_name = symbol.replace('_NS', '')
    elif symbol.endswith('_BO'):
        exchange = 'BSE'
        symbol_name = symbol.replace('_BO', '')
    else:
        exchange = 'NSE'
        symbol_name = symbol
    
    # Add global config if missing
    if 'SYMBOL' not in content:
        config_block = f'''
# Global config (used by run_strategy and main)
SYMBOL = "{symbol_name}"
EXCHANGE = "{exchange}"
STRATEGY_NAME = "VWAP"
POSITION = 10000
ENTRY_VWAP_PCT = 0.5
ENTRY_RSI_MIN = 55
ENTRY_RSI_MAX = 45
ENTRY_VOL_MIN = 1.2
SL_ATR_MULT = 1.0
TGT_RR = 4.0

'''
        # Insert after first import or at top
        import_idx = -1
        for i, line in enumerate(content.split('\n')):
            if line.startswith('import ') or line.startswith('from '):
                import_idx = i
        if import_idx >= 0:
            lines = content.split('\n')
            lines.insert(import_idx + 1, config_block)
            content = '\n'.join(lines)
        else:
            content = config_block + content
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return "patched"
    return "unchanged"


def main():
    files = sorted(glob.glob("live_*.py"))
    stats = {"patched": 0, "unchanged": 0, "fail": 0, "fails": []}
    
    for i, f in enumerate(files):
        try:
            result = backup_and_patch(f)
            stats[result] += 1
        except Exception as e:
            stats["fail"] += 1
            stats["fails"].append((f, str(e)))
        
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(files)}...")
    
    print(f"\nResults: {stats['patched']} patched, {stats['unchanged']} unchanged, {stats['fail']} failed")
    
    if stats['fails']:
        for f, e in stats['fails'][:5]:
            print(f"  FAIL: {f} — {e}")
    
    # Verify compile
    import subprocess
    ok, fail_list = 0, []
    for f in files:
        r = subprocess.run(['python3', '-m', 'py_compile', f],
                         capture_output=True, timeout=10)
        if r.returncode == 0:
            ok += 1
        else:
            fail_list.append(f)
    
    print(f"Compile: {ok}/{len(files)} OK")
    if fail_list:
        print(f"Failed: {fail_list[:3]}")
        # Restore failed files
        for f in fail_list:
            bak = os.path.join(BACKUP_DIR, os.path.basename(f) + ".bak")
            if os.path.exists(bak):
                shutil.copy2(bak, f)
        # Recheck
        ok2 = sum(1 for f in files
                  if subprocess.run(['python3', '-m', 'py_compile', f],
                                 capture_output=True, timeout=10).returncode == 0)
        print(f"After restore: {ok2}/{len(files)} OK")


if __name__ == "__main__":
    main()
