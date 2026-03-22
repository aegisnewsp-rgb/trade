#!/usr/bin/env python3
"""
QA Loop FOREVER - Runs continuously
Checks compile, enhances low win-rate scripts, commits, sleeps.
"""
import os, sys, subprocess, json, time, re
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE = Path("/home/node/workspace/trade-project")
DEPLOY = WORKSPACE / "deploy"
LOGS = DEPLOY / "logs"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002381931352")

CYCLE = 0
LOW_WINRATE_THRESHOLD = 45.0
MIN_TRADES_FOR_STATS = 8  # Minimum trades to consider statistically meaningful

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN:
        log(f"[TG-SKIP] {msg[:80]}")
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        r = requests.post(url, data=data, timeout=10)
        log(f"[TG] {'SENT' if r.status_code==200 else f'FAIL {r.status_code}'}: {msg[:60]}")
    except Exception as e:
        log(f"[TG-ERR] {e}")

def git_commit(msg):
    try:
        os.chdir(WORKSPACE)
        subprocess.run(["git", "add", "-A"], capture_output=True)
        r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if r.returncode == 0:
            log(f"[GIT] {msg[:80]}")
            return True
        elif "nothing to commit" in r.stderr.lower():
            log(f"[GIT] No changes")
            return False
        else:
            log(f"[GIT-WARN] {r.stderr[:80]}")
            return False
    except Exception as e:
        log(f"[GIT-ERR] {e}")
        return False

def compile_check():
    scripts = sorted(DEPLOY.glob("live_*.py"))
    failed = []
    for s in scripts:
        r = subprocess.run(["python3", "-m", "py_compile", str(s)], 
                          capture_output=True, text=True)
        if r.returncode != 0:
            failed.append((s.name, r.stderr[:200]))
    if failed:
        for name, err in failed:
            log(f"[COMPILE-FAIL] {name}")
        return False
    log(f"[COMPILE] OK: {len(scripts)} scripts")
    return True

def update_readme():
    readme = DEPLOY / "README.md"
    scripts = list(DEPLOY.glob("live_*.py"))
    count = len(scripts)
    if not readme.exists():
        return False
    content = readme.read_text()
    m = re.search(r'\*\*(\d+) live trading scripts', content)
    if m and int(m.group(1)) != count:
        content = re.sub(r'\*\*\d+ live trading scripts', f'**{count} live trading scripts', content)
        readme.write_text(content)
        log(f"[README] Updated count to {count}")
        return True
    return False

def get_low_winrate_scripts():
    """Return scripts with win_rate < threshold from performance.json."""
    perf_file = LOGS / "performance.json"
    if not perf_file.exists():
        return []
    try:
        data = json.loads(perf_file.read_text())
        low = [(k, v) for k, v in data.items() 
               if isinstance(v, dict) 
               and v.get("win_rate", 1.0) * 100 < LOW_WINRATE_THRESHOLD
               and v.get("trades", 0) >= MIN_TRADES_FOR_STATS]
        low.sort(key=lambda x: x[1].get("win_rate", 1.0))
        return low[:10]
    except Exception as e:
        log(f"[PERF-ERR] {e}")
        return []

def enhance_script(sym):
    """Apply targeted enhancements to fix low win-rate issues."""
    script = DEPLOY / f"live_{sym}.py"
    if not script.exists():
        return None
    
    content = script.read_text()
    original = content
    changes = []
    
    # 1. Fix oversold/overbought = True bug (should be numbers)
    if re.search(r'oversold\s*=\s*True\b', content):
        content = re.sub(r'oversold\s*=\s*True\b', 'oversold = 40', content)
        changes.append("oversold:True→40")
    if re.search(r'overbought\s*=\s*True\b', content):
        content = re.sub(r'overbought\s*=\s*True\b', 'overbought = 60', content)
        changes.append("overbought:True→60")
    
    # 2. Tighten stop loss for low win-rate scripts
    if re.search(r'STOP_LOSS_PCT\s*=\s*0\.008', content):
        content = re.sub(r'STOP_LOSS_PCT\s*=\s*0\.008', 'STOP_LOSS_PCT  = 0.006', content)
        changes.append("SL:0.008→0.006")
    
    # 3. Raise volume threshold
    if re.search(r'VOLUME_RATIO_MIN\s*=\s*1\.0', content):
        content = re.sub(r'VOLUME_RATIO_MIN\s*=\s*1\.0', 'VOLUME_RATIO_MIN = 1.3', content)
        changes.append("Vol:1.0→1.3")
    elif re.search(r'VOLUME_RATIO_MIN\s*=\s*1\.2', content):
        content = re.sub(r'VOLUME_RATIO_MIN\s*=\s*1\.2', 'VOLUME_RATIO_MIN = 1.5', content)
        changes.append("Vol:1.2→1.5")
    
    # 4. Raise RSI buy threshold (sub-50 RSI for BUY = oversold)
    # Look for RSI_FILTER_BUY patterns
    if re.search(r'RSI_FILTER_BUY\s*=\s*50', content):
        content = re.sub(r'RSI_FILTER_BUY\s*=\s*50', 'RSI_FILTER_BUY = 55', content)
        changes.append("RSI_buy:50→55")
    
    # 5. Lower RSI sell threshold
    if re.search(r'RSI_FILTER_SELL\s*=\s*50', content):
        content = re.sub(r'RSI_FILTER_SELL\s*=\s*50', 'RSI_FILTER_SELL = 45', content)
        changes.append("RSI_sell:50→45")
    
    if content != original:
        script.write_text(content)
        log(f"[ENHANCE] {sym}: {', '.join(changes)}")
        return changes
    return None

def run_cycle():
    global CYCLE
    CYCLE += 1
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    log(f"=== CYCLE {CYCLE} ===")
    
    compile_ok = compile_check()
    readme_updated = update_readme()
    
    low_scripts = get_low_winrate_scripts()
    enhanced = []
    for sym, data in low_scripts:
        result = enhance_script(sym)
        if result:
            enhanced.append(sym)
    
    changes = []
    if not compile_ok:
        changes.append("compile-fix")
    if readme_updated:
        changes.append("readme-update")
    if enhanced:
        changes.append(f"enhanced-{len(enhanced)}-scripts")
    
    if changes:
        git_commit(f"QA cycle {CYCLE} ({ts}): {', '.join(changes)}")
    else:
        log(f"[CYCLE] No changes needed")
    
    if compile_ok and enhanced:
        send_telegram(f"🟡 QA Cycle {CYCLE} | Enhanced: {', '.join(enhanced[:5])}")
    elif compile_ok:
        send_telegram(f"🟢 QA Cycle {CYCLE} OK | {len(list(DEPLOY.glob('live_*.py')))} scripts")
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
            log("Sleeping 30 min...")
            time.sleep(1800)
        except KeyboardInterrupt:
            log("⏹ Stopped")
            send_telegram("⏹ QA Loop stopped")
            break
        except Exception as e:
            log(f"ERROR: {e}")
            send_telegram(f"❌ QA Loop error: {str(e)[:100]}")
            time.sleep(60)

if __name__ == "__main__":
    main()
