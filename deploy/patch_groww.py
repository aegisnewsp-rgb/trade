#!/usr/bin/env python3
"""
Patch all live_*.py files to use the proper groww_api module.
Replaces broken place_groww_order() with groww_api.place_bo() or place_market()
"""
import os, re, shutil

DEPLOY = "/home/node/workspace/trade-project/deploy"

def patch_script(filepath):
    with open(filepath) as f:
        content = f.read()
    
    original = content
    
    # Find the place_groww_order function and replace it
    # Pattern: def place_groww_order(...): ... return result
    # We'll add a new implementation at the end of the file
    
    new_function = '''
def place_groww_order(symbol, signal, quantity, price):
    """
    Place order via Groww API or paper trade.
    Uses Bracket Orders (BO) when GROWW_API_KEY is set.
    Falls back to paper trading otherwise.
    """
    import groww_api
    
    if not groww_api.is_configured():
        return groww_api.paper_trade(signal, symbol, price, quantity)
    
    exchange = "NSE"
    
    if signal == "BUY":
        # Calculate target and stop loss
        atr = price * 0.008  # 0.8% ATR approximation
        stop_loss = price - (atr * 1.0)  # 1x ATR stop
        target = price + (atr * 4.0)  # 4x ATR target
        # Use bracket order for BUY with target + stop loss
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="BUY",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3,
            trailing_target=0.5
        )
    elif signal == "SELL":
        atr = price * 0.008
        stop_loss = price + (atr * 1.0)
        target = price - (atr * 4.0)
        result = groww_api.place_bo(
            exchange=exchange,
            symbol=symbol,
            transaction="SELL",
            quantity=quantity,
            target_price=target,
            stop_loss_price=stop_loss,
            trailing_sl=0.3,
            trailing_target=0.5
        )
    else:
        return None
    
    if result:
        print("Order placed: {} {} {} @ Rs{:.2f}".format(
            signal, quantity, symbol, price))
    return result

'''
    
    # Check if already patched
    if "import groww_api" in content and "def place_groww_order" in content:
        # Already has groww_api, check if it calls place_bo
        if "groww_api.place_bo" in content or "groww_api.place_market" in content:
            return "already_patched"
        # Has groww_api but broken place_groww_order - replace function body
        # Remove old function and add new one
        # Find the function and everything inside it
        pattern = r'def place_groww_order\(.*?\n(?:[^\n]*\n)*?(?=\ndef |\Z)'
        content = re.sub(pattern, new_function.strip(), content, flags=re.DOTALL)
        if content != original:
            return "fixed_function"
        return "no_change"
    
    # Add import groww_api at the top (after other imports)
    if "import groww_api" not in content:
        # Add after 'import logging' or 'import requests'
        if "import logging" in content:
            content = content.replace("import logging", "import logging\nimport groww_api")
        elif "import requests" in content:
            content = content.replace("import requests", "import requests\nimport groww_api")
        else:
            # Add after first import line
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('import '):
                    idx = i
                    break
            else:
                idx = 0
            lines.insert(idx + 1, 'import groww_api')
            content = '\n'.join(lines)
    
    # Append the new function before the main block
    # Find where to insert (before 'if __name__' or at end)
    if 'if __name__' in content:
        content = content.replace('if __name__', new_function + '\nif __name__')
    else:
        content = content + '\n' + new_function
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return "patched"
    return "no_change"


def main():
    os.chdir(DEPLOY)
    files = sorted([f for f in os.listdir('.') if f.startswith('live_') and f.endswith('.py')])
    
    results = {"patched": 0, "fixed_function": 0, "already_patched": 0, "no_change": 0, "errors": 0}
    
    for fname in files:
        try:
            result = patch_script(fname)
            results[result] = results.get(result, 0) + 1
        except Exception as e:
            print("ERROR {}: {}".format(fname, e))
            results["errors"] += 1
    
    print("\nPatch Results:")
    print("  Patched (new import): {}".format(results["patched"]))
    print("  Fixed function: {}".format(results["fixed_function"]))
    print("  Already patched: {}".format(results["already_patched"]))
    print("  No change: {}".format(results["no_change"]))
    print("  Errors: {}".format(results["errors"]))
    
    # Verify all patched files compile
    import subprocess
    ok, fail = 0, 0
    for fname in files:
        r = subprocess.run(["python3", "-m", "py_compile", fname], capture_output=True)
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print("COMPILE FAIL: {}".format(fname))
    
    print("\nCompile check: {} OK, {} FAILED".format(ok, fail))


if __name__ == "__main__":
    main()
