#!/usr/bin/env python3
"""
SAFE Patch: Replace place_groww_order in all live_*.py with proper groww_api integration.
This version processes files one-by-one with verification after EACH file.
If a file fails to compile, it's reverted before continuing.
"""
import os, shutil, subprocess

DEPLOY = "/home/node/workspace/trade-project/deploy"
os.chdir(DEPLOY)

BACKUP_DIR = DEPLOY + "/.patch_backup"
os.makedirs(BACKUP_DIR, exist_ok=True)

NEW_FUNC = '''
def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API or emit to signal queue for orchestrator.
    - If GROWW_API_KEY set: place BO via groww_api (real trading)
    - Else: emit signal to queue for Master Orchestrator (paper/live coalesced)
    """
    import groww_api

    if not groww_api.is_configured():
        # Paper mode: emit to signal queue for orchestrator
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent))
            from signals.schema import emit_signal
            _atr = price * 0.008
            try:
                if 'atr' in globals() and isinstance(globals().get('atr'), (int, float)):
                    _atr = float(globals()['atr'])
            except:
                _atr = price * 0.008
            emit_signal(
                symbol=symbol, signal=signal, price=price,
                quantity=quantity,
                strategy=str(globals().get('STRATEGY_NAME', 'VWAP')),
                atr=_atr,
                metadata={"source": Path(__file__).name}
            )
            return {"status": "queued", "symbol": symbol, "signal": signal}
        except ImportError:
            # Fallback: pure paper print
            print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
            return {"status": "paper", "symbol": symbol, "signal": signal}

    # Live mode: place Bracket Order via Groww API
    exchange = "NSE"
    atr = price * 0.008
    if signal == "BUY":
        sl = round(price - atr * 1.0, 2)
        tgt = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(exchange, symbol, "BUY", quantity, tgt, sl, 0.3, 0.5)
    elif signal == "SELL":
        sl = round(price + atr * 1.0, 2)
        tgt = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(exchange, symbol, "SELL", quantity, tgt, sl, 0.3, 0.5)
    else:
        return None

    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, sl, tgt))
    return result


def place_order(symbol, signal, quantity, price):
    """Alias for compatibility"""
    return place_groww_order(symbol, signal, quantity, price)

'''


def backup_file(filepath):
    shutil.copy2(filepath, os.path.join(BACKUP_DIR, os.path.basename(filepath) + ".bak"))


def patch_one(filepath):
    """Patch ONE file safely. Returns 'patched', 'skip', or 'fail'"""
    with open(filepath) as f:
        lines = f.readlines()

    # Check if already patched
    if "groww_api.place_bo" in ''.join(lines):
        return "skip"

    # Backup
    backup_file(filepath)

    # Find place_groww_order function start
    func_start = -1
    for i, line in enumerate(lines):
        if line.startswith('def place_groww_order'):
            func_start = i
            break

    if func_start == -1:
        return "skip"

    # Find function end (next top-level def/class/if __name__)
    func_end = len(lines)
    base_indent = len(lines[func_start]) - len(lines[func_start].lstrip())
    for i in range(func_start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        # Top-level: no indent
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped.startswith(('def ', 'class ', 'if __name__')):
            func_end = i
            break

    # Also remove any place_order alias
    order_start = -1
    for i, line in enumerate(lines):
        if line.startswith('def place_order'):
            order_start = i
            break
    if order_start != -1:
        for i in range(order_start + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0 and stripped.startswith(('def ', 'class ', 'if __name__')):
                # Remove from order_start to i
                lines = lines[:order_start] + lines[i:]
                break

    # Build new file
    new_lines = lines[:func_start] + [NEW_FUNC + '\n'] + lines[func_end:]

    # Add groww_api import if missing
    new_content = ''.join(new_lines)
    if "import groww_api" not in new_content:
        inserted = False
        for i, line in enumerate(new_lines):
            if line.startswith('import ') and i > 0:
                new_lines.insert(i + 1, 'import groww_api\n')
                inserted = True
                break
        if not inserted and "import yfinance" in new_content:
            for i, line in enumerate(new_lines):
                if "import yfinance" in line:
                    new_lines.insert(i + 1, 'import groww_api\n')
                    break

    new_content = ''.join(new_lines)

    # Verify it compiles
    with open(filepath, 'w') as f:
        f.write(new_content)

    r = subprocess.run(['python3', '-m', 'py_compile', filepath],
                      capture_output=True, timeout=10)
    if r.returncode != 0:
        # Revert
        shutil.copy2(os.path.join(BACKUP_DIR, os.path.basename(filepath) + ".bak"), filepath)
        return "fail"

    return "patched"


def main():
    files = sorted([f for f in os.listdir('.') if f.startswith('live_') and f.endswith('.py')])

    stats = {"patched": 0, "skip": 0, "fail": 0}
    failed_files = []

    for i, fname in enumerate(files):
        result = patch_one(fname)
        stats[result] = stats.get(result, 0) + 1
        if result == "fail":
            failed_files.append(fname)
        elif result == "patched":
            pass

        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(files)}...")

    print(f"\nResults: {stats['patched']} patched, {stats['skip']} skipped, {stats['fail']} failed")
    if failed_files:
        print("Failed files:")
        for f in failed_files[:5]:
            print(f"  {f}")
        # Restore failed files from backup
        for f in failed_files:
            bak = os.path.join(BACKUP_DIR, os.path.basename(f) + ".bak")
            if os.path.exists(bak):
                shutil.copy2(bak, f)
        print(f"Restored {len(failed_files)} files from backup")

    # Final compile check
    ok, fail = 0, []
    for fname in files:
        r = subprocess.run(['python3', '-m', 'py_compile', fname],
                         capture_output=True, timeout=10)
        if r.returncode == 0:
            ok += 1
        else:
            fail.append(fname)

    print(f"Final compile: {ok} OK, {len(fail)} FAIL")


if __name__ == "__main__":
    main()
