#!/usr/bin/env python3
"""Patch all live_*.py to emit signals to queue instead of direct Groww API calls"""
import os, re

DEPLOY = "/home/node/workspace/trade-project/deploy"
os.chdir(DEPLOY)

NEW_FUNC = '''
def place_groww_order(symbol, signal, quantity, price):
    """
    Emit trading signal to queue for Master Orchestrator.
    Orchestrator coalesces all signals and places orders via Groww API
    (single connection = no rate limiting across 468 scripts).
    Paper mode: orchestrator prints signals instead of placing.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from signals.schema import emit_signal
        # Get ATR from script's atr variable if available
        _atr = price * 0.008
        try:
            if 'atr' in globals() and isinstance(globals().get('atr'), (int, float)):
                _atr = float(globals()['atr'])
        except:
            _atr = price * 0.008
        _strategy = str(globals().get('STRATEGY_NAME', 'VWAP'))
        emit_signal(
            symbol=symbol, signal=signal, price=price,
            quantity=quantity, strategy=_strategy, atr=_atr,
            metadata={"source": Path(__file__).name}
        )
        return {"status": "queued", "symbol": symbol, "signal": signal}
    except ImportError:
        print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
        return {"status": "paper", "symbol": symbol, "signal": signal}


def place_order(symbol, signal, quantity, price):
    return place_groww_order(symbol, signal, quantity, price)
'''


def patch_file(filepath):
    with open(filepath) as f:
        content = f.read()
    
    if "emit_signal" in content and "status: queued" in content:
        return "already_patched"
    
    original = content
    
    # Remove old place_groww_order function (find next top-level def)
    lines = content.split('\n')
    new_lines = []
    skip_until_next_def = False
    skip_until_name_main = False
    
    for i, line in enumerate(lines):
        # Start skipping at old place_groww_order
        if line.startswith('def place_groww_order'):
            skip_until_next_def = True
            continue
        # Stop skipping at next top-level def or class or if __name__
        if skip_until_next_def:
            if (line.startswith('def ') or line.startswith('class ') or
                line.startswith('if __name__')):
                skip_until_next_def = False
                new_lines.append(line)
            continue
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    # Add emit_signal import if missing
    if "from signals.schema import emit_signal" not in content:
        lines = content.split('\n')
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') and i > 0:
                insert_at = i + 1
                break
        # Insert after last import
        lines.insert(insert_at, '')
        lines.insert(insert_at + 1, 'import sys')
        lines.insert(insert_at + 2, 'from pathlib import Path')
        content = '\n'.join(lines)
    
    # Append new function before if __name__
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
            print("ERROR {}: {}".format(fname, e))
            stats["errors"] += 1
    
    print("Patch: {} patched, {} already, {} unchanged, {} errors".format(
        stats["patched"], stats["already_patched"], stats["unchanged"], stats["errors"]))
    
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
    
    print("Compile: {} OK, {} FAILED".format(ok, len(fail)))
    if fail:
        for f in fail[:5]:
            print("  FAIL:", f)


if __name__ == "__main__":
    main()
