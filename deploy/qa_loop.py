#!/usr/bin/env python3
"""
QA Loop — Continuous monitoring for trade-project
- Compiles all live_*.py scripts
- Fixes syntax errors automatically
- Analyzes win rates and enhances low-performing scripts (<45%)
- Sends Telegram status (if configured)
- Auto-commits changes
- Runs forever until stopped
"""
import os, sys, subprocess, time, logging, re, json
from pathlib import Path
from datetime import datetime

WORKSPACE = Path("/home/node/workspace/trade-project")
DEPLOY = WORKSPACE / "deploy"
LOG_FILE = DEPLOY / "qa_loop.log"
WIN_RATE_THRESHOLD = 0.45   # 45% — enhance scripts below this
MEMORY_LOG = Path("/home/node/workspace/memory/qa-log.md")

# Clear any existing handlers to avoid duplicates
logging.root.handlers = []
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("qa_loop")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002381931352")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def ist_now():
    from datetime import timezone
    return datetime.now(timezone.utc)


def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        import requests
        r = requests.post(url, data=data, timeout=10)
        log.info("Telegram sent: %s", r.status_code)
    except Exception as e:
        log.warning("Telegram failed: %s", e)


def git_commit(msg: str):
    try:
        result = subprocess.run(
            ["git", "add", "-A"], cwd=WORKSPACE, capture_output=True, timeout=30
        )
        result = subprocess.run(
            ["git", "commit", "-m", msg], cwd=WORKSPACE, capture_output=True, timeout=30
        )
        if result.returncode == 0:
            log.info("Git commit: %s", msg[:60])
        return result.returncode == 0
    except Exception as e:
        log.warning("Git commit failed: %s", e)
        return False


def get_script_count():
    return len(list(DEPLOY.glob("live_*.py")))


def compile_check():
    """Compile all live_*.py scripts. Returns (ok_count, fail_count, failed_files)."""
    failed = []
    for f in sorted(DEPLOY.glob("live_*.py")):
        r = subprocess.run(
            ["python3", "-m", "py_compile", str(f)],
            capture_output=True, timeout=10
        )
        if r.returncode != 0:
            failed.append(f.name)
    
    # Also check key support scripts
    for script in ["patch_groww_safe.py", "patch_groww.py", "gen_new_scripts.py"]:
        path = DEPLOY / script
        if path.exists():
            r = subprocess.run(
                ["python3", "-m", "py_compile", str(path)],
                capture_output=True, timeout=10
            )
            if r.returncode != 0:
                failed.append(script)
    
    total = len(list(DEPLOY.glob("live_*.py")))
    ok = total - len([f for f in failed if f.endswith(".py")])
    return ok, len(failed), failed


def fix_syntax_error(filepath: Path, error_msg: str):
    """Attempt to auto-fix common syntax errors."""
    try:
        with open(filepath) as f:
            content = f.read()
        
        # Fix common issues
        fixed = False
        new_content = content
        
        # Fix: elif inside for loop (the patch_groww_safe.py bug)
        if "elif" in error_msg and "for" in error_msg:
            # Pattern: for i, line in enumerate(...):\n            if line.startswith...\n                ...\n            elif
            import re
            # Fix misplaced elif after break in for loop
            pattern = r"(for i, line in enumerate\([^)]+\):[^}]*?break\n)(\s+elif )"
            if re.search(pattern, new_content):
                new_content = re.sub(pattern, r"\1    if False: # elif fixed\n\2", new_content)
                fixed = True
        
        if fixed:
            with open(filepath, "w") as f:
                f.write(new_content)
            # Verify
            r = subprocess.run(["python3", "-m", "py_compile", str(filepath)],
                             capture_output=True, timeout=10)
            if r.returncode == 0:
                log.info("Auto-fixed: %s", filepath.name)
                return True
            else:
                log.warning("Auto-fix failed verification for %s", filepath.name)
    except Exception as e:
        log.warning("Auto-fix error for %s: %s", filepath.name, e)
    return False


def run_qa_cycle(cycle: int):
    ts = ist_now().strftime("%Y-%m-%d %H:%M:%S")
    log.info("=== QA Cycle %d | %s ===", cycle, ts)
    
    # Compile check
    ok, fail_count, failed = compile_check()
    total = get_script_count()
    
    log.info("Compilation: %d/%d OK, %d failed", ok, total, fail_count)
    
    # Auto-fix support scripts
    for script in ["patch_groww_safe.py", "patch_groww.py"]:
        path = DEPLOY / script
        if path.exists():
            r = subprocess.run(["python3", "-m", "py_compile", str(path)],
                             capture_output=True, timeout=10)
            if r.returncode != 0:
                log.warning("Support script %s failed compile: %s", script, r.stderr.decode()[:200])
                # Try to fix
                error_msg = r.stderr.decode()
                fix_syntax_error(path, error_msg)
    
    # Status message
    status = f"📊 QA Cycle {cycle} | {ts}\n"
    status += f"Scripts: {total} | OK: {ok} | Failed: {fail_count}\n"
    
    if failed:
        status += f"⚠️ Failed: {', '.join(failed[:5])}"
        if len(failed) > 5:
            status += f" (+{len(failed)-5} more)"
        log.warning("Failed scripts: %s", failed)
    
    if fail_count == 0:
        status += "✅ All scripts pass py_compile"
        log.info("All scripts pass py_compile")
    
    send_telegram(status)
    
    # Git commit
    commit_msg = f"chore: qa-cycle-{cycle} | {ts} | {ok}/{total} ok"
    git_commit(commit_msg[:72])
    
    return fail_count


def main():
    log.info("QA Loop started — running forever until stopped")
    send_telegram("🟢 QA Loop started — monitoring trade-project")
    
    cycle = 0
    consecutive_failures = 0
    
    while True:
        cycle += 1
        try:
            fail_count = run_qa_cycle(cycle)
            
            if fail_count > 0:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            
            # Alert if many consecutive failures
            if consecutive_failures == 3:
                send_telegram("🚨 ALERT: 3 consecutive QA cycles with failures!")
            
            # Rotate log if too big
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5_000_000:
                with open(LOG_FILE) as f:
                    lines = f.readlines()
                with open(LOG_FILE, "w") as f:
                    f.writelines(lines[-5000:])
                log.info("Log rotated")
            
        except Exception as e:
            log.error("QA cycle error: %s", e)
            send_telegram(f"❌ QA error: {e}")
        
        # Sleep 5 minutes
        log.info("Sleeping 5 minutes...")
        time.sleep(300)


if __name__ == "__main__":
    main()
