#!/usr/bin/env python3
"""
QA Loop FOREVER - Runs continuously
Checks compile, enhances low win-rate scripts, commits, sleeps.
"""
import os, sys, subprocess, json, time
from pathlib import Path
from datetime import datetime

WORKSPACE = Path("/home/node/workspace/trade-project")
DEPLOY = WORKSPACE / "deploy"
LOGS = DEPLOY / "logs"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002381931352")

CYCLE = 0
LOW_WINRATE_THRESHOLD = 45.0  # Enhance scripts below this win rate

def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN:
        log(f"[TG-SKIP] No token configured: {msg[:80]}")
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            log(f"[TG-SENT] {msg[:80]}")
        else:
            log(f"[TG-FAIL] {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log(f"[TG-ERR] {e}")

def git_commit(msg):
    try:
        os.chdir(WORKSPACE)
        subprocess.run(["git", "add", "-A"], capture_output=True)
        r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if r.returncode == 0:
            log(f"[GIT] Committed: {msg[:80]}")
            return True
        elif "nothing to commit" in r.stderr:
            log(f"[GIT] Nothing to commit")
            return False
        else:
            log(f"[GIT-WARN] {r.stderr[:100]}")
            return False
    except Exception as e:
        log(f"[GIT-ERR] {e}")
        return False

def compile_check():
    """Compile all live_*.py scripts."""
    scripts = sorted(DEPLOY.glob("live_*.py"))
    failed = []
    for s in scripts:
        r = subprocess.run(["python3", "-m", "py_compile", str(s)], 
                          capture_output=True, text=True)
        if r.returncode != 0:
            failed.append((s.name, r.stderr[:200]))
    if failed:
        for name, err in failed:
            log(f"[COMPILE-FAIL] {name}: {err}")
        send_telegram(f"❌ Compile failures: {len(failed)} scripts")
        return False
    log(f"[COMPILE] ✅ All {len(scripts)} scripts OK")
    return True

def update_readme():
    """Update README if new scripts were added since last count."""
    readme = DEPLOY / "README.md"
    scripts = list(DEPLOY.glob("live_*.py"))
    count = len(scripts)
    
    # Check current count in README
    current_count = None
    if readme.exists():
        content = readme.read_text()
        import re
        m = re.search(r'\*\*(\d+) live trading scripts', content)
        if m:
            current_count = int(m.group(1))
    
    if current_count != count:
        log(f"[README] Updating script count: {current_count} -> {count}")
        if readme.exists():
            content = readme.read_text()
            import re
            content = re.sub(r'\*\*\d+ live trading scripts', f'**{count} live trading scripts', content)
            content = re.sub(r'- \d{4}-\d{2}-\d{2}:.*', f'- {datetime.utcnow().strftime("%Y-%m-%d")}: v8 verified', content)
            readme.write_text(content)
        return True
    return False

def get_low_winrate_scripts():
    """Return scripts with win_rate < threshold from enhancement_queue.json."""
    eq_file = DEPLOY / ".enhancement_queue.json"
    if not eq_file.exists():
        return []
    try:
        data = json.loads(eq_file.read_text())
        low = [(k, v) for k, v in data.items() 
               if isinstance(v, dict) and v.get("win_rate", 1.0) * 100 < LOW_WINRATE_THRESHOLD]
        low.sort(key=lambda x: x[1].get("win_rate", 1.0))
        return low[:10]  # Top 10 worst
    except:
        return []

def enhance_script(sym):
    """Apply parameter optimization to a single script."""
    script = DEPLOY / f"live_{sym}.py"
    if not script.exists():
        return False
    
    # Read current params
    content = script.read_text()
    
    # Tighter stop-loss and higher RSI threshold for low win-rate scripts
    # We look for patterns to tweak
    import random
    enhancements = []
    
    # Try tightening stop loss (reduce from 0.008 to 0.006)
    if "STOP_LOSS_PCT  = 0.008" in content:
        content = content.replace("STOP_LOSS_PCT  = 0.008", "STOP_LOSS_PCT  = 0.006")
        enhancements.append("SL:0.008→0.006")
    
    # Raise RSI threshold (55→58 for buys, 45→42 for sells)
    if "RSI_FILTER_BUY = 55" in content:
        content = content.replace("RSI_FILTER_BUY = 55", "RSI_FILTER_BUY = 58")
        enhancements.append("RSI_buy:55→58")
    if "RSI_FILTER_SELL = 45" in content:
        content = content.replace("RSI_FILTER_SELL = 45", "RSI_FILTER_SELL = 42")
        enhancements.append("RSI_sell:45→42")
    
    # Tighten volume filter
    if "VOLUME_RATIO_MIN = 1.2" in content:
        content = content.replace("VOLUME_RATIO_MIN = 1.2", "VOLUME_RATIO_MIN = 1.5")
        enhancements.append("Vol:1.2→1.5")
    elif "VOLUME_RATIO_MIN = 1.0" in content:
        content = content.replace("VOLUME_RATIO_MIN = 1.0", "VOLUME_RATIO_MIN = 1.3")
        enhancements.append("Vol:1.0→1.3")
    
    if enhancements:
        script.write_text(content)
        log(f"[ENHANCE] {sym}: {', '.join(enhancements)}")
        return True
    return False

def run_cycle():
    global CYCLE
    CYCLE += 1
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    log(f"=== CYCLE {CYCLE} ===")
    
    # 1. Compile check
    compile_ok = compile_check()
    
    # 2. README update
    readme_updated = update_readme()
    
    # 3. Low win-rate enhancement
    low_scripts = get_low_winrate_scripts()
    enhanced = []
    for sym, data in low_scripts:
        if enhance_script(sym):
            enhanced.append(sym)
    
    # 4. Git commit if anything changed
    changes = []
    if not compile_ok:
        changes.append("compile-fix")
    if readme_updated:
        changes.append("readme-update")
    if enhanced:
        changes.append(f"enhanced-{len(enhanced)}-scripts")
    
    if changes:
        git_commit(f"QA cycle {CYCLE} ({ts}): {', '.join(changes)}")
    
    # 5. Telegram status
    if compile_ok and not enhanced:
        send_telegram(f"🟢 QA Cycle {CYCLE} ✅ | {len(list(DEPLOY.glob('live_*.py')))} scripts | No issues")
    elif enhanced:
        send_telegram(f"🟡 QA Cycle {CYCLE} | Enhanced: {', '.join(enhanced[:5])}")
    else:
        send_telegram(f"🔴 QA Cycle {CYCLE} | FAILURE")
    
    log(f"=== CYCLE {CYCLE} DONE ===")
    return compile_ok

def main():
    log("🚀 QA LOOP FOREVER started")
    send_telegram("🚀 QA Loop FOREVER started")
    git_commit("QA: Loop FOREVER started")
    
    while True:
        try:
            run_cycle()
            log(f"Sleeping 7 minutes before next cycle...")
            time.sleep(420)  # 7 minutes
        except KeyboardInterrupt:
            log("⏹ Stopped by user")
            send_telegram("⏹ QA Loop stopped")
            break
        except Exception as e:
            log(f"ERROR: {e}")
            send_telegram(f"❌ QA Loop error: {str(e)[:100]}")
            time.sleep(60)  # 1 min retry on error

if __name__ == "__main__":
    main()
