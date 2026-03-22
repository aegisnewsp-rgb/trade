#!/usr/bin/env python3
"""
Night Shift Orchestrator — Non-stop until 9 AM IST
Spawns batches of 5 agents continuously.
"""
import os, sys, time, json
from datetime import datetime, timezone, timedelta

WORKSPACE = "/home/node/workspace/trade-project/deploy"
os.chdir(WORKSPACE)
sys.path.insert(0, WORKSPACE)


def ist_now():
    return datetime.now(timezone.ist) + timedelta(hours=5, minutes=30)


def should_keep_running():
    """Run until 9 AM IST"""
    return ist_now().hour < 9


ENHANCEMENT_QUEUE = [
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "RELIANCE", "TCS",
    "SBIN", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA",
    "CIPLA", "SRF", "IGL", "BANKINDIA", "NESTLEIND",
    "MARUTI", "HINDALCO", "HCLTECH", "HEROMOTOCO", "M&M",
    "KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
    "NTPC", "POWERGRID", "ONGC", "GAIL", "BPCL",
    "ITC", "NESTLEIND", "HINDUNILVR", "BRITANNIA", "DMART",
    "VEDL", "TATASTEEL", "JINDALSTL", "NMDC", "HINDALCO",
    "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM",
    "SUNPHARMA", "CIPLA", "DRREDDY", "LUPIN", "ZYDUS",
    "MARUTI", "BAJAJ_AUTO", "HEROMOTOCO", "M&M", "TATAMOTORS",
    "LT", "ADANIPORTS", "GMRINFRA", "BHARTIARTL", "HDFCAMC",
]


def get_next_batch():
    """Get next 5 symbols from queue"""
    queue_file = WORKSPACE + "/.enhancement_queue.json"
    if os.path.exists(queue_file):
        with open(queue_file) as f:
            queue = json.load(f)
    else:
        queue = ENHANCEMENT_QUEUE

    if not queue:
        return [], []

    batch = queue[:5]
    remaining = queue[5:]

    with open(queue_file, "w") as f:
        json.dump(remaining, f, indent=2)

    return remaining, batch


def log(msg):
    ts = ist_now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(WORKSPACE + "/logs", exist_ok=True)
    with open(WORKSPACE + "/logs/night_shift.log", "a") as f:
        f.write(line + "\n")


def make_enhance_prompt(symbols):
    """Build enhancement prompt for 5 symbols"""
    items = "\n".join(f"  - live_{s}.py" for s in symbols)
    sym_yf = "\n".join(f"  - live_{s}.py → {s}" for s in symbols)
    ticker_yf = "\n".join(f"yf.Ticker('{s}.NS')" for s in symbols)

    return f"""NIGHT SHIFT — Enhance Agent

WORKSPACE: /home/node/workspace/trade-project/deploy/

TASK: Enhance ALL 5 scripts. For EACH script:
  1. Read the live_*.py file
  2. Add: RSI filter (55/45), volume confirmation (1.2x avg),
     smart entry window (9:30 AM-2:30 PM IST),
     3-tier targets (1.5x/3x/5x risk)
  3. Verify compile: python3 -m py_compile live_<SYMBOL>.py
  4. Test data: python3 -c "import yfinance as yf; t=yf.Ticker('{symbols[0]}.NS'); print(t.history('3mo').tail(3))"
  5. Commit: git add live_<SYMBOL>.py && git commit -m "feat: {symbols[0]} enhanced for Groww production"

SCRIPTS:
{sym_yf}

Send Telegram when done:
message(action=send, channel=telegram, target=8692074549, message="NIGHT: {', '.join(symbols)} enhanced ✓")

Start NOW with the first script."""


def make_qa_prompt():
    return """NIGHT SHIFT — QA Agent

WORKSPACE: /home/node/workspace/trade-project/deploy/

TASK:
1. Run: python3 -m py_compile on ALL live_*.py files
2. Report: "QA: X OK, Y FAIL"
3. Fix any failures (common: missing main(), bad indent, wrong attr)
4. Run: python3 live_TITAN.py 2>&1 | head -5 (test a few)
5. Commit fixes
6. Send Telegram: message(action=send, channel=telegram, target=8692074549, message="QA complete: X scripts verified")

Start NOW."""


def make_backtest_prompt():
    return """NIGHT SHIFT — Backtest Agent

WORKSPACE: /home/node/workspace/trade-project/deploy/

TASK:
1. Run backtest on top 50 scripts with yfinance
2. For each: 90d data, VWAP strategy, win rate
3. Save: research/backtest_results/ranked_all.json
4. Update: research/backtest_results/top_50.json
5. Verify all top 50 compile
6. Commit
7. Telegram: message(action=send, channel=telegram, target=8692074549, message="Backtest complete: X scripts ranked")

Start NOW."""


def make_sync_prompt():
    return """NIGHT SHIFT — GitHub Sync Agent

WORKSPACE: /home/node/workspace/trade-project/deploy/

TASK:
1. python3 -m py_compile on all 99 strategies/groww_*.py
2. Report: "Strategies: X OK, Y FAIL"
3. Fix any failures
4. Copy enhanced live_*.py → strategies/groww_*.py
5. Ensure all have: def run_strategy(ohlcv) entry point
6. git add -A && git commit -m "chore: nightly sync $(date +%H:%M)"
7. git push 2>&1 | tail -3
8. Telegram: message(action=send, channel=telegram, target=8692074549, message="GitHub synced: X commits pushed")

Start NOW."""


# Round-robin through task types
TASK_CYCLE = ["enhance", "qa", "backtest", "sync", "enhance", "qa", "enhance", "enhance", "qa", "backtest"]
task_idx = 0


def get_next_prompt():
    global task_idx
    remaining, batch = get_next_batch()

    task_type = TASK_CYCLE[task_idx % len(TASK_CYCLE)]
    task_idx += 1

    if task_type == "enhance" and batch:
        return make_enhance_prompt(batch), f"enhance:{batch[0]}"
    elif task_type == "qa":
        return make_qa_prompt(), "qa_all"
    elif task_type == "backtest":
        return make_backtest_prompt(), "backtest_all"
    elif task_type == "sync":
        return make_sync_prompt(), "sync_github"
    else:
        # Fallback: sync
        return make_sync_prompt(), "sync_github"


if __name__ == "__main__":
    batch_num = 0
    log("NIGHT SHIFT STARTED — non-stop until 9 AM IST")

    while should_keep_running():
        batch_num += 1
        prompt, desc = get_next_prompt()

        # Write prompt to file for main agent to pick up
        spawn_file = WORKSPACE + f"/.next_spawn.json"
        with open(spawn_file, "w") as f:
            json.dump({"batch": batch_num, "prompt": prompt, "desc": desc,
                      "ist_time": ist_now().isoformat()}, f, indent=2)

        log(f"Batch {batch_num} ready: {desc}")

        # Sleep 60 seconds between batches
        time.sleep(60)

    log(f"NIGHT SHIFT COMPLETE. {batch_num} batches prepared.")
