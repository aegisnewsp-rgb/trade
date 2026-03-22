#!/usr/bin/env python3
"""
Subagent Pool Manager — Maximize MiniMax API Throughput
Maintains a pool of pre-spawned agents ready to process tasks.

Architecture:
  Main Agent (you)
    ├── Pool Coordinator (persistent subagent, idle waiting)
    │   ├── Worker 1 (idle, ready)
    │   ├── Worker 2 (idle, ready)
    │   ├── Worker 3 (idle, ready)
    │   ├── Worker 4 (idle, ready)
    │   └── Worker 5 (idle, ready)
    └── [More Pool Coordinators...]
"""
import os, json, time
from pathlib import Path
from datetime import datetime

POOL_DIR = Path("/home/node/workspace/trade-project/deploy/agent_pool")
POOL_DIR.mkdir(exist_ok=True)
TASK_QUEUE = POOL_DIR / "task_queue.json"
POOL_STATUS = POOL_DIR / "pool_status.json"

MAX_POOLS = 4          # 4 coordinators × 5 workers = 20 agents
WORKERS_PER_POOL = 5
IDLE_TIMEOUT = 300    # Reap idle workers after 5 min


def load_queue():
    if TASK_QUEUE.exists():
        with open(TASK_QUEUE) as f:
            return json.load(f)
    return []


def save_queue(tasks):
    with open(TASK_QUEUE, "w") as f:
        json.dump(tasks, f, indent=2)


def load_status():
    if POOL_STATUS.exists():
        with open(POOL_STATUS) as f:
            return json.load(f)
    return {"pools": [], "last_update": None}


def save_status(status):
    status["last_update"] = datetime.datetime.now(datetime.timezone.ist) + datetime.timedelta(hours=5, minutes=30).isoformat()
    with open(POOL_STATUS, "w") as f:
        json.dump(status, f, indent=2)


def enqueue_task(task: dict, priority: int = 5):
    """Add a task to the queue. priority 1=highest, 10=lowest."""
    tasks = load_queue()
    tasks.append({
        "task": task["task"],
        "description": task.get("description", ""),
        "priority": priority,
        "added_at": datetime.datetime.now(datetime.timezone.ist) + datetime.timedelta(hours=5, minutes=30).isoformat(),
        "status": "pending",
    })
    tasks.sort(key=lambda x: (x["priority"], x["added_at"]))
    save_queue(tasks)
    return len(tasks)


def get_next_task():
    """Get highest priority pending task."""
    tasks = load_queue()
    for t in tasks:
        if t["status"] == "pending":
            t["status"] = "claimed"
            t["claimed_at"] = datetime.datetime.now(datetime.timezone.ist) + datetime.timedelta(hours=5, minutes=30).isoformat()
            save_queue(tasks)
            return t
    return None


def mark_task_done(task_description: str, status: str = "done"):
    tasks = load_queue()
    for t in tasks:
        if t["description"] == task_description and t["status"] == "claimed":
            t["status"] = status
            t["completed_at"] = datetime.datetime.now(datetime.timezone.ist) + datetime.timedelta(hours=5, minutes=30).isoformat()
            save_queue(tasks)
            return True
    return False


def pool_status_summary():
    status = load_status()
    tasks = load_queue()
    pending = sum(1 for t in tasks if t["status"] == "pending")
    claimed = sum(1 for t in tasks if t["status"] == "claimed")
    
    return {
        "pools": len(status.get("pools", [])),
        "workers_total": len(status.get("pools", [])) * WORKERS_PER_POOL,
        "tasks_pending": pending,
        "tasks_claimed": claimed,
        "tasks_done": sum(1 for t in tasks if t["status"] == "done"),
    }


# ─── Task Templates ────────────────────────────────────────────────────────────

TASK_TEMPLATES = {
    "enhance_script": {
        "description": "Enhance stock script",
        "prompt": "Enhance /home/node/workspace/trade-project/deploy/live_{symbol}.py — add RSI filter, volume confirmation, optimize stop loss. Verify compile. Commit."
    },
    "backtest_script": {
        "description": "Backtest stock script",
        "prompt": "Backtest live_{symbol}.py — run yfinance 90-day backtest, calculate win rate, output ranked results to research/backtest_results/. Commit."
    },
    "analyze_batch": {
        "description": "Analyze batch of scripts",
        "prompt": "Analyze all live_*.py scripts in deploy/ for quality. Compile check, strategy assessment, identify bottom 3. Output ranked list. Commit."
    },
    "run_qa": {
        "description": "QA compile check",
        "prompt": "Run python3 -m py_compile on all live_*.py scripts in deploy/. Report OK/fail count. Fix any failures."
    },
}


def enqueue_enhance(symbol: str, priority: int = 5):
    template = TASK_TEMPLATES["enhance_script"]
    task = template["prompt"].format(symbol=symbol)
    return enqueue_task({"task": task, "description": f"Enhance {symbol}"}, priority)


def enqueue_backtest(symbol: str, priority: int = 5):
    template = TASK_TEMPLATES["backtest_script"]
    task = template["prompt"].format(symbol=symbol)
    return enqueue_task({"task": task, "description": f"Backtest {symbol}"}, priority)


def enqueue_batch_analysis(batch_name: str, symbols: list, priority: int = 5):
    """Enqueue analysis for a batch of symbols."""
    prompt = f"Analyze these {len(symbols)} scripts: {', '.join(symbols)}. For each: compile check, strategy quality, risk mgmt, groww_api integration. Rank by quality. Commit."
    return enqueue_task({"task": prompt, "description": f"Batch analysis: {batch_name}"}, priority)


# ─── Pool Spawner ─────────────────────────────────────────────────────────────

def spawn_pool_coordinator(pool_id: int, task_batch: list) -> dict:
    """
    Spawn a pool coordinator with a batch of tasks.
    Returns spawn result dict.
    """
    # Combine tasks into one prompt for the coordinator
    combined_prompt = f"""SUBAGENT POOL COORDINATOR {pool_id}

You are coordinating {len(task_batch)} tasks. Process them in order.
After each task: verify compile, commit.

TASKS:
"""
    for i, task in enumerate(task_batch):
        combined_prompt += f"\n{i+1}. {task['description']}\n   {task['task'][:200]}..."

    combined_prompt += "\n\nStart with task 1 immediately. Use sessions_spawn to delegate subtasks if needed."

    return {
        "pool_id": pool_id,
        "task_count": len(task_batch),
        "spawn_prompt": combined_prompt,
        "created_at": datetime.datetime.now(datetime.timezone.ist) + datetime.timedelta(hours=5, minutes=30).isoformat(),
    }


# ─── Display ─────────────────────────────────────────────────────────────────

def print_status():
    s = pool_status_summary()
    print(f"""
╔══════════════════════════════════════════════╗
║       SUBAGENT POOL STATUS                   ║
╠══════════════════════════════════════════════╣
║  Active Pools:       {s['pools']:<25}║
║  Total Workers:       {s['workers_total']:<25}║
║  Tasks Pending:       {s['tasks_pending']:<25}║
║  Tasks In Progress:   {s['tasks_claimed']:<25}║
║  Tasks Completed:     {s['tasks_done']:<25}║
╚══════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print_status()
        print("Usage:")
        print("  python3 agent_pool.py enqueue <type> <args>  — add task")
        print("  python3 agent_pool.py status                 — show status")
        print("  python3 agent_pool.py queue                 — show queue")
        print("  python3 agent_pool.py spawn <pool_id>       — spawn coordinator")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        print_status()
    elif cmd == "queue":
        tasks = load_queue()
        print(f"\nTask Queue ({len(tasks)} tasks):")
        for t in tasks:
            print(f"  [{t['status']:7}] P{t['priority']} — {t['description']}")
    elif cmd == "enqueue":
        if len(sys.argv) < 3:
            print("Usage: agent_pool.py enqueue <symbol|batch_name>")
        else:
            arg = sys.argv[2]
            count = enqueue_enhance(arg) if "_" not in arg or arg.isupper() else enqueue_batch_analysis(arg, [])
            print(f"Added '{arg}' to queue. Total: {count} tasks")
    elif cmd == "spawn" and len(sys.argv) >= 3:
        pool_id = int(sys.argv[2])
        tasks = load_queue()[:WORKERS_PER_POOL]
        result = spawn_pool_coordinator(pool_id, tasks)
        print(f"Spawned coordinator {pool_id} with {len(tasks)} tasks")
        print(result["spawn_prompt"][:500] + "...")
