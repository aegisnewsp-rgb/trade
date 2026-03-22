#!/usr/bin/env python3
"""
Master Orchestrator Runner
= Signal Queue Processor + Context Compactor

Run every 60 seconds via cron:
  * * * * * cd /home/node/workspace/trade-project/deploy && python3 run_master.py >> logs/orchestrator.log 2>&1

Architecture:
  Worker scripts → signals/pending/*.json → ORCHESTRATOR (coalesces) → Groww API (single connection)
"""
import os, sys, subprocess, json
from pathlib import Path
from datetime import datetime

ROOT = Path("/home/node/workspace/trade-project/deploy")
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "orchestrator.log"

# Ensure signals dir exists
(ROOT / "signals" / "pending").mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))


def log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def check_context():
    """Run context compactor if needed"""
    try:
        from signals.context_compactor import auto_compact
        did_compact, report = auto_compact()
        if did_compact:
            log(f"CONTEXT COMPACTED: {report['compact_result'].get('entries_removed', 0)} entries removed")
            # Delegate deep reasoning synthesis
            _delegate_summarization(report)
    except Exception as e:
        log(f"CONTEXT CHECK ERROR: {e}")


def _delegate_summarization(report: dict):
    """Queue a deep reasoning task for MiniMax about compacted context"""
    try:
        delegate_file = LOG_DIR / "delegate_queue.json"
        prompt = f"""Context was auto-compacted. Before it was cleared, the system processed signals. 
Analyze this report and create a 2-3 sentence memory summary for future trading sessions:

{json.dumps(report, indent=2)}

Write your summary to MEMORY.md or memory/YYYY-MM-DD.md"""
        
        with open(delegate_file, "a") as f:
            f.write(json.dumps({"prompt": prompt, "time": datetime.utcnow().isoformat()}) + "\n")
        
        log(f"DELEGATE: Summarization queued for MiniMax")
    except Exception as e:
        log(f"DELEGATE ERROR: {e}")


def process_signals_cycle():
    """Run one signal processing cycle"""
    try:
        from signals.orchestrator import run_cycle
        placed, failed = run_cycle()
        log(f"SIGNALS: {placed} placed, {failed} failed")
        return placed, failed
    except Exception as e:
        log(f"SIGNAL PROCESSING ERROR: {e}")
        return 0, 1


def main():
    log("=" * 50)
    log("MASTER ORCHESTRATOR CYCLE START")
    
    # Step 1: Context check (lightweight)
    check_context()
    
    # Step 2: Process signals
    placed, failed = process_signals_cycle()
    
    # Step 3: Clean up processed signals
    try:
        from signals.schema import Signal
        Signal.clear_processed()
    except Exception as e:
        log(f"CLEANUP ERROR: {e}")
    
    log(f"CYCLE COMPLETE: {placed} placed, {failed} failed")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
