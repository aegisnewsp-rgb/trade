#!/usr/bin/env python3
"""
Patch all live_*.py scripts to write signals to the queue
instead of calling Groww API directly.
This enables coalesced order placement (1 API connection = no rate limits).
"""
import os, re

DEPLOY = "/home/node/workspace/trade-project/deploy"
os.chdir(DEPLOY)


NEW_FUNC = '''
def place_groww_order(symbol, signal, quantity, price):
    """
    Write signal to queue — Master Orchestrator places the actual order.
    This avoids 468 scripts each hitting Groww API independently.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        from signals.schema import emit_signal
        # Try to get ATR from script context
        atr = price * 0.008  # fallback
        if 'atr' in globals():
            try:
                atr = float(atr) if isinstance(atr, (int, float)) else price * 0.008
            except:
                atr = price * 0.008
        
        emit_signal(
            symbol=symbol,
            signal=signal,
            price=price,
            quantity=quantity,
            strategy=str(globals().get('STRATEGY_NAME', 'VWAP')),
            atr=atr,
            metadata={"source": Path(__file__).name}
        )
        return {"status": "queued", "symbol": symbol, "signal": signal}
    except ImportError:
        # Fallback: print signal (paper mode)
        print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
        return {"status": "paper", "symbol": symbol, "signal": signal}


def place_order(symbol, signal, quantity, price):
    """Alias for compatibility"""
    return place_groww_order(symbol, signal, quantity, price)

'''


def patch_file(filepath):
    with open(filepath) as f:
        content = f.read()
    
    if "SIGNAL QUEUED" in content and "emit_signal" in content:
        return "already_patched"
    
    original = content
    
    # Add emit_signal import if not present
    if "from signals.schema import emit_signal" not in content:
        # Find insertion point (after other imports)
        lines = content.split('\n')
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') and i > 0:
                insert_at = i + 1
        
        # Or after 'import groww_api'
        for i, line in enumerate(lines):
            if 'import groww_api' in line:
                insert_at = i + 1
                break
        
        lines.insert(insert_at, 'import sys')
        lines.insert(insert_at + 1, 'from pathlib import Path')
        
        content = '\n'.join(lines)
    
    # Remove old place_groww_order function
    # Match from 'def place_groww_order' to next 'def ' at column 0
    pattern = r'def place_groww_order\([^)]*\):[^\n]*\n(?:.*?\n)*?(?=\n(?:def [a-zA-Z]|if __name__|class |$
    )'
    content = re.sub(pattern, '', content, flags=re.MULTILINE)
    
    # Also remove place_order alias if exists
    pattern2 = r'def place_order\([^)]*\):[^\n]*\n(?:.*?\n)*?(?=\n(?:def [a-zA-Z]|if __name__|class |$
    )'
    content = re.sub(pattern2, '', content, flags=re.MULTILINE)
    
    # Append new function before main block
    if 'if __name__' in content:
        content = content.replace('if __name__', NEW_FUNC + '\nif __name__')
    else:
        content = content + '\n' + NEW_FUNC
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return "patched"
    return "unchanged"


def main():
    files = sorted([f for f in os.listdir('.') if f.startswith('live_') and f.endswith('.py')])
    stats = {"patched": 0, "already_patched": 0, "unchanged": 0, "errors": 0}
    
    for fname in files:
        try:
            result = patch_file(fname)
            stats[result] = stats.get(result, 0) + 1
        except Exception as e:
            print(f"ERROR {fname}: {e}")
            stats["errors"] += 1
    
    print(f"Patch: {stats['patched']} patched, {stats['already_patched']} already, "
          f"{stats['unchanged']} unchanged, {stats['errors']} errors")
    
    # Compile check
    import subprocess
    ok, fail = 0, []
    for fname in files:
        r = subprocess.run(["python3", "-m", "py_compile", fname],
                          capture_output=True, timeout=10)
        if r.returncode == 0:
            ok += 1
        else:
            fail.append(fname)
    
    print(f"Compile: {ok} OK, {len(fail)} FAILED")
    if fail:
        for f in fail[:5]:
            print(f"  FAIL: {f}")


if __name__ == "__main__":
    main()
