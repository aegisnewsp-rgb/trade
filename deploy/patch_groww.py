#!/usr/bin/env python3
"""Patch all live_*.py files to use proper groww_api.place_bo()"""
import os, re, shutil

DEPLOY = "/home/node/workspace/trade-project/deploy"

NEW_FUNC = '''
def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API (real) or paper trade.
    Uses Bracket Order (BO) for BUY/SELL with target + stop loss built-in.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    atr = price * 0.008  # 0.8% of price as ATR approximation
    
    if signal == "BUY":
        stop_loss = round(price - atr * 1.0, 2)
        target = round(price + atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="BUY", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    elif signal == "SELL":
        stop_loss = round(price + atr * 1.0, 2)
        target = round(price - atr * 4.0, 2)
        result = groww_api.place_bo(
            exchange=exchange, symbol=symbol,
            transaction="SELL", quantity=quantity,
            target_price=target, stop_loss_price=stop_loss,
            trailing_sl=0.3, trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("ORDER: {} {}x {} @ Rs{} [SL:{} TGT:{}]".format(
            signal, quantity, symbol, price, stop_loss, target))
    return result

'''


def patch_file(filepath):
    with open(filepath) as f:
        content = f.read()
    
    original = content
    
    # Add import groww_api if missing
    if "import groww_api" not in content:
        # Find a good place to add it
        if "import logging" in content:
            content = content.replace("import logging", "import logging\nimport groww_api")
        elif "import requests" in content:
            content = content.replace("import requests", "import requests\nimport groww_api")
        elif "import yfinance" in content:
            content = content.replace("import yfinance", "import yfinance\nimport groww_api")
        elif "import json" in content:
            content = content.replace("import json", "import json\nimport groww_api")
        else:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('import '):
                    lines.insert(i+1, 'import groww_api')
                    content = '\n'.join(lines)
                    break
    
    # Remove old place_groww_order function completely
    # Match: def place_groww_order(...) up to the next def or end of file
    pattern = r'def place_groww_order\([^)]*\):[^\n]*\n(?:.*?\n)*?(?=\n(?:def |if __name__|$))'
    content = re.sub(pattern, NEW_FUNC.strip(), content, flags=re.MULTILINE)
    
    # Also handle case where function goes to end of file
    if "def place_groww_order" in original:
        # Already replaced if pattern matched, but if the function was at end of file...
        if "def place_groww_order" in content:
            pattern2 = r'\n*def place_groww_order\([^)]*\):[^\n]*\n(?:.*)$'
            content = re.sub(pattern2, '\n' + NEW_FUNC.strip(), content, flags=re.MULTILINE)
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return "patched"
    return "unchanged"


def main():
    os.chdir(DEPLOY)
    files = sorted([f for f in os.listdir('.') if f.startswith('live_') and f.endswith('.py')])
    
    stats = {"patched": 0, "unchanged": 0, "errors": 0}
    
    for fname in files:
        try:
            r = patch_file(fname)
            stats[r] = stats.get(r, 0) + 1
        except Exception as e:
            print("ERROR {}: {}".format(fname, e))
            stats["errors"] += 1
    
    print("Patch: {} patched, {} unchanged, {} errors".format(
        stats["patched"], stats["unchanged"], stats["errors"]))
    
    # Compile check
    import subprocess
    ok, fail = 0, []
    for fname in files:
        r = subprocess.run(["python3", "-m", "py_compile", fname], capture_output=True)
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
