#!/usr/bin/env python3
"""
Context Compactor — Keep 200k rolling window functional within 128k limit
Run this periodically (every ~30 min during active trading) or when context feels heavy.

Usage: python3 context_compactor.py [--check-only]
"""
import os, sys, json, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).parent.parent
LOG_FILE = ROOT / "logs" / "context_log.jsonl"
ARCHIVE_DIR = ROOT / "logs" / "compacted"
ARCHIVE_DIR.mkdir(exist_ok=True)

# Thresholds
MAX_LOG_SIZE_MB = 1.0      # Compact when log exceeds this
TARGET_KEEP_MB = 0.5        # After compaction, keep this much recent
TOKEN_ESTIMATE_PER_CHAR = 0.25  # rough estimate


def estimate_tokens(text: str) -> int:
    return int(len(text) * TOKEN_ESTIMATE_PER_CHAR)


def estimate_context_size() -> dict:
    """Estimate total context from all sources"""
    total_chars = 0
    details = {}
    
    # Log file
    if LOG_FILE.exists():
        size = LOG_FILE.stat().st_size
        total_chars += size
        details["log_file_chars"] = size
        details["log_file_mb"] = round(size / 1024 / 1024, 2)
    
    # Git diff (uncommitted changes)
    import subprocess
    try:
        r = subprocess.run(["git", "diff", "--stat"],
                          cwd=ROOT, capture_output=True, text=True, timeout=5)
        if r.stdout:
            details["git_diff"] = len(r.stdout)
            total_chars += len(r.stdout)
    except:
        pass
    
    # Recent memory files
    mem_dir = ROOT / "memory"
    if mem_dir.exists():
        for mf in sorted(mem_dir.glob("*.md"))[-3:]:
            try:
                size = len(mf.read_text())
                total_chars += size
                details[f"memory_{mf.name}"] = size
            except:
                pass
    
    total_tokens = estimate_tokens(chr(total_chars))
    
    return {
        "total_chars": total_chars,
        "total_tokens_approx": total_tokens,
        "total_mb": round(total_chars / 1024 / 1024, 2),
        "details": details,
        "fill_pct_128k": min(100, int(total_tokens / 128000 * 100)),
        "fill_pct_200k": min(100, int(total_tokens / 200000 * 100)),
    }


def compact_log() -> dict:
    """Compact the context log file"""
    if not LOG_FILE.exists():
        return {"action": "no_log_file", "entries_removed": 0}
    
    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except:
                pass
    
    if len(entries) < 10:
        return {"action": "too_few_entries", "entries": len(entries)}
    
    # Keep newer 50%
    keep = entries[len(entries)//2:]
    
    # Archive older half
    arc_name = f"arc_{datetime.now(timezone.utc) + datetime.timedelta(hours=5, minutes=30).strftime('%H%M%S')}_{len(entries)//2}.jsonl"
    arc_path = ARCHIVE_DIR / arc_name
    with open(arc_path, "w") as f:
        for e in entries[:len(entries)//2]:
            f.write(json.dumps(e) + "\n")
    
    # Write kept entries back
    with open(LOG_FILE, "w") as f:
        for e in keep:
            f.write(json.dumps(e) + "\n")
    
    return {
        "action": "compacted",
        "entries_removed": len(entries) - len(keep),
        "entries_kept": len(keep),
        "archived_to": str(arc_path),
        "archived_count": len(entries)//2,
    }


def purge_old_archives(max_age_hours=24):
    """Remove archives older than max_age_hours"""
    import time
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    for f in ARCHIVE_DIR.glob("arc_*.jsonl"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed


def auto_compact():
    """
    Main entry point — check and compact if needed.
    Returns (did_compact, report_dict)
    """
    stats = estimate_context_size()
    print(f"[CONTEXT] Size: {stats['total_mb']}MB | "
          f"~{stats['total_tokens_approx']} tokens | "
          f"128k fill: {stats['fill_pct_128k']}%")
    
    if stats["fill_pct_128k"] >= 80:
        print("[CONTEXT] ≥80% fill — triggering compaction...")
        result = compact_log()
        purge_old_archives()
        
        # Re-check
        stats2 = estimate_context_size()
        print(f"[CONTEXT] After compaction: {stats2['total_mb']}MB | "
              f"128k fill: {stats2['fill_pct_128k']}%")
        
        return True, {"before": stats, "compact_result": result, "after": stats2}
    
    print(f"[CONTEXT] OK — no compaction needed")
    return False, {"stats": stats}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    
    if args.check_only:
        stats = estimate_context_size()
        print(json.dumps(stats, indent=2))
    else:
        did_compact, report = auto_compact()
        print(json.dumps(report, indent=2))
        sys.exit(0 if not did_compact else 0)
