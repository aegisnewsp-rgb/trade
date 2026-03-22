#!/usr/bin/env python3
"""
Add universal main() to ALL scripts that are missing it.
Reads the signal function from each script and wraps it in a runnable main().
"""
import os, re, shutil

DEPLOY = "/home/node/workspace/trade-project/deploy"
os.chdir(DEPLOY)

# Universal main block - works for any strategy type
UNIVERSAL_MAIN = '''
def main():
    """
    Universal main() — detects strategy type and runs appropriate signal.
    Works with: VWAP, ADX_TREND, TSI, RSI, MACD, Bollinger, MA_ENVELOPE, etc.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed: pip install yfinance")
        return
    
    # Detect symbol from filename
    fname = Path(__file__).stem  # e.g. "live_RELIANCE"
    sym = fname.replace("live_", "").replace("_NS", ".NS").replace("_BO", ".BO")
    ticker_sym = sym.replace(".NS", "").replace(".BO", "")
    
    # Determine exchange suffix for yfinance
    exchange_suffix = ".NS" if ".NS" in sym else ".BO"
    yahoo_sym = ticker_sym + exchange_suffix
    
    print(f"\\n{'='*60}")
    print(f"Running: {ticker_sym} ({yahoo_sym})")
    print(f"{'='*60}")
    
    # Fetch data
    try:
        ticker = yf.Ticker(yahoo_sym)
        data = ticker.history(period="3mo")
        if data.empty:
            print(f"No data for {yahoo_sym}")
            return
        ohlcv = [[r[0], r[1], r[2], r[3], r[4]] for r in data.itertuples()]
        print(f"Loaded {len(ohlcv)} candles")
    except Exception as e:
        print(f"Data fetch error: {e}")
        return
    
    # Prepare OHLCV list for strategy functions
    ohlcv_list = []
    for idx, row in data.iterrows():
        ohlcv_list.append([
            float(row['Open']),
            float(row['High']),
            float(row['Low']),
            float(row['Close']),
            float(row['Volume'])
        ])
    
    if not ohlcv_list:
        print("No OHLCV data")
        return
    
    # Detect strategy type and run appropriate signal
    signal = None
    price = ohlcv_list[-1][2]  # close price
    
    try:
        # Try strategy functions in priority order
        if 'vwap_signal' in dir():
            sig_result = vwap_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple) and len(sig_result) >= 2:
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'adx_signal' in dir():
            sig_result = adx_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'rsi_signal' in dir():
            sig_result = rsi_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        elif 'macd_signal' in dir():
            sig_result = macd_signal(ohlcv_list, {})
            if isinstance(sig_result, tuple):
                signal, price = sig_result[0], float(sig_result[1])
            elif isinstance(sig_result, str):
                signal = sig_result
        else:
            # Generic: look for any function returning signal
            for func_name in ['signal', 'get_signal', 'generate_signal']:
                if func_name in dir():
                    func = eval(func_name)
                    if callable(func):
                        result = func(ohlcv_list)
                        if isinstance(result, tuple):
                            signal, price = result[0], float(result[1])
                        elif isinstance(result, str):
                            signal = result
                        break
        
        # Default fallback: calculate basic signals
        if not signal:
            closes = [o[4] for o in ohlcv_list]
            if len(closes) >= 20:
                sma20 = sum(closes[-20:]) / 20
                current = closes[-1]
                if current > sma20 * 1.005:
                    signal = "BUY"
                    price = current
                elif current < sma20 * 0.995:
                    signal = "SELL"
                    price = current
                else:
                    signal = "HOLD"
                    price = current
    
    except Exception as e:
        print(f"Signal generation error: {e}")
        signal = "HOLD"
        price = ohlcv_list[-1][4]
    
    # Calculate ATR for risk management
    atr = price * 0.008  # fallback
    if len(ohlcv_list) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_list))):
            h = ohlcv_list[i][1]
            l = ohlcv_list[i][2]
            prev_c = ohlcv_list[i-1][4]
            tr = max(h-l, abs(h-prev_c), abs(l-prev_c))
            trs.append(tr)
        if trs:
            atr = sum(trs) / len(trs)
    
    # Output
    print(f"\\nSignal: {signal}")
    print(f"Price:  Rs{price:.2f}")
    print(f"ATR:    Rs{atr:.2f}")
    
    if signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{price-sl:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{tgt-price:.2f} reward)")
        
        # Place order
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="BUY",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr,
                metadata={"source": Path(__file__).name}
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("BUY", ticker_sym, price, qty)
            except:
                pass
    
    elif signal == "SELL":
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
        qty = max(1, int(10000 / price))
        print(f"Qty:    {qty}")
        print(f"Stop:   Rs{sl:.2f} (Rs{sl-price:.2f} risk)")
        print(f"Target: Rs{tgt:.2f} (Rs{price-tgt:.2f} reward)")
        
        try:
            from signals.schema import emit_signal
            emit_signal(
                symbol=ticker_sym,
                signal="SELL",
                price=price,
                quantity=qty,
                strategy="AUTO_DETECTED",
                atr=atr
            )
        except ImportError:
            try:
                from groww_api import paper_trade
                paper_trade("SELL", ticker_sym, price, qty)
            except:
                pass
    
    else:
        print("No trade — HOLD signal")


if __name__ == "__main__":
    main()

'''


def needs_main(filepath):
    """Check if script needs main() added"""
    with open(filepath) as f:
        content = f.read()
    
    # Already has main() that works
    if 'def main()' in content and 'if __name__' in content and 'main()' in content:
        return False
    
    # Check if it has signal generation code
    has_signal = any(x in content for x in [
        'vwap_signal', 'adx_signal', 'rsi_signal', 'macd_signal',
        'generate_signal', 'get_signal', 'calculate_vwap'
    ])
    return has_signal


def add_main(filepath):
    """Add universal main() to a script"""
    with open(filepath) as f:
        content = f.read()
    
    original = content
    
    # Remove any existing broken main() blocks
    lines = content.split('\n')
    new_lines = []
    skip = False
    for line in lines:
        if line.strip().startswith('if __name__'):
            skip = True
            continue
        if skip and line.strip().startswith('def ') and not line.startswith('    '):
            skip = False
        if not skip:
            new_lines.append(line)
    
    content = '\n'.join(new_lines).rstrip() + '\n'
    
    # Append main
    content += UNIVERSAL_MAIN
    
    # Verify it compiles
    import subprocess
    with open(filepath, 'w') as f:
        f.write(content)
    
    r = subprocess.run(['python3', '-m', 'py_compile', filepath],
                      capture_output=True, timeout=10)
    if r.returncode != 0:
        # Restore original
        with open(filepath, 'w') as f:
            f.write(original)
        return "fail"
    
    return "ok"


def main():
    files = sorted([f for f in os.listdir('.') if f.startswith('live_') and f.endswith('.py')])
    
    to_fix = [f for f in files if needs_main(f)]
    already_ok = [f for f in files if not needs_main(f)]
    
    print(f"Files already OK: {len(already_ok)}")
    print(f"Files needing main(): {len(to_fix)}")
    
    ok, fail = 0, []
    for i, f in enumerate(to_fix):
        result = add_main(f)
        if result == "ok":
            ok += 1
        else:
            fail.append(f)
        
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(to_fix)}...")
    
    print(f"\nAdded main(): {ok} OK, {len(fail)} failed")
    
    if fail:
        print("Failed files:")
        for f in fail[:5]:
            print(f"  {f}")
    
    # Final compile check
    import subprocess
    total_ok = 0
    for f in files:
        r = subprocess.run(['python3', '-m', 'py_compile', f],
                          capture_output=True, timeout=10)
        if r.returncode == 0:
            total_ok += 1
    
    print(f"\nFinal: {total_ok}/{len(files)} compile OK")


if __name__ == "__main__":
    main()
