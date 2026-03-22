#!/usr/bin/env python3
"""
Rolling Portfolio Manager — Bottom 5 Replace + Grow
After each trading evaluation window:
  1. Score all 99 active scripts by today's P&L
  2. Drop bottom 5 (worst performers)
  3. Bring in top 5 from reserve pool
  4. Update GitHub with new 99-script set

Usage: python3 rolling_portfolio.py --action rotate
       python3 rolling_portfolio.py --action status
"""
import os, sys, json, argparse, glob
from datetime import datetime
from pathlib import Path

DEPLOY = Path("/home/node/workspace/trade-project/deploy")
STRATEGY_DIR = DEPLOY / "strategies"
RESERVE_POOL_FILE = DEPLOY / "reserve_pool.json"
ACTIVE_FILE = DEPLOY / "active_portfolio.json"
PERF_FILE = DEPLOY / "logs" / "performance.json"
PERF_FILE.parent.mkdir(exist_ok=True)

# Reserve pool — all scripts NOT in top 99
RESERVE_POOL = [
    # All 370+ scripts from deploy/live_*.py not in top 99
    # These are maintained as a ranked queue
]


def load_active():
    if ACTIVE_FILE.exists():
        with open(ACTIVE_FILE) as f:
            return json.load(f)
    return {}


def load_reserve():
    if RESERVE_POOL_FILE.exists():
        with open(RESERVE_POOL_FILE) as f:
            return json.load(f)
    return []


def save_active(data):
    with open(ACTIVE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_reserve(data):
    with open(RESERVE_POOL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_performance():
    if PERF_FILE.exists():
        with open(PERF_FILE) as f:
            return json.load(f)
    return {}


def save_performance(data):
    with open(PERF_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_active_scripts():
    """Get list of active (top 99) script names"""
    scripts = sorted([f.name for f in STRATEGY_DIR.glob("groww_*.py")])
    return scripts[:99]


def rank_reserve():
    """
    Rank all scripts in deploy/live_*.py not in active top 99.
    Returns ranked list by estimated win rate.
    """
    active = set(get_active_scripts())
    active_names = {s.replace("groww_", "").replace(".py", "") for s in active}
    
    ranked = []
    for f in DEPLOY.glob("live_*.py"):
        sym = f.stem.replace("live_", "").replace("_NS", "").replace("_BO", "")
        if sym not in active_names:
            # Placeholder ranking — in production, use actual backtest data
            ranked.append({"symbol": sym, "script": f.name, "estimated_wr": 0.50})
    
    # Sort by estimated win rate (descending)
    ranked.sort(key=lambda x: x["estimated_wr"], reverse=True)
    return ranked


def rotate_bottom_5():
    """
    Main rotation logic:
    1. Load today's performance data
    2. Rank active scripts by P&L
    3. Drop bottom 5
    4. Pull top 5 from reserve
    5. Symlink/copy new scripts to strategies/
    6. Commit to git
    """
    perf = load_performance()
    active = get_active_scripts()
    
    if not perf:
        print("No performance data — cannot rotate. Run trading first.")
        return
    
    # Score each active script
    scored = []
    for script in active:
        sym = script.replace("groww_", "").replace(".py", "")
        pnl = perf.get(sym, {}).get("pnl", 0)
        trades = perf.get(sym, {}).get("trades", 0)
        scored.append({"script": script, "symbol": sym, "pnl": pnl, "trades": trades})
    
    # Sort by P&L (worst first)
    scored.sort(key=lambda x: (x["pnl"], x["trades"]))
    
    bottom_5 = scored[:5]
    print("\nBottom 5 performers to DROP:")
    for s in bottom_5:
        print(f"  {s['symbol']}: ₹{s['pnl']:.2f} ({s['trades']} trades)")
    
    # Get top 5 from reserve
    reserve = load_reserve()
    if not reserve:
        reserve = rank_reserve()
        save_reserve(reserve)
    
    top_5_reserve = reserve[:5]
    print("\nTop 5 from reserve to ADD:")
    for s in top_5_reserve:
        wr = s.get("estimated_wr", 0.50)
        print(f"  {s['symbol']}: est. {wr*100:.1f}% WR")
    
    # Remove bottom 5 from active
    bottom_5_syms = {s["symbol"] for s in bottom_5}
    active_set = set(active) - {s["script"] for s in bottom_5}
    
    # Add top 5 from reserve
    new_scripts = []
    for r in top_5_reserve:
        # Find actual file by symbol
        matches = list(DEPLOY.glob(f"live_*{r['symbol']}*.py"))
        if matches:
            src_file = matches[0]
            dst_file = STRATEGY_DIR / f"groww_{r['symbol']}.py"
            # Copy strategy file
            strat_file = STRATEGY_DIR / f"groww_{r['symbol']}.py"
            if not strat_file.exists():
                # Use live script as base
                import shutil
                shutil.copy2(src_file, strat_file)
            new_scripts.append(r["symbol"])
    
    # Update active portfolio
    active_data = {
        "updated": datetime.utcnow().isoformat(),
        "scripts": sorted(list(active_set) + [f"groww_{s}.py" for s in new_scripts]),
        "dropped": [s["symbol"] for s in bottom_5],
        "added": new_scripts,
    }
    save_active(active_data)
    
    print(f"\n✅ Portfolio rotated: dropped {len(bottom_5)}, added {len(new_scripts)}")
    print(f"Active scripts: {len(active_data['scripts'])}")
    
    # Commit
    os.system("cd /home/node/workspace/trade-project && git add -A && "
               "git commit -m 'chore: rolling portfolio — dropped bottom 5, added top 5 reserve' 2>/dev/null")
    
    return active_data


def status():
    """Show current portfolio status"""
    active = get_active_scripts()
    perf = load_performance()
    
    print(f"\n{'='*50}")
    print(f"PORTFOLIO STATUS — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")
    print(f"Active scripts: {len(active)}/99")
    
    if perf:
        scored = []
        for script in active:
            sym = script.replace("groww_", "").replace(".py", "")
            pnl = perf.get(sym, {}).get("pnl", 0)
            scored.append({"symbol": sym, "pnl": pnl})
        scored.sort(key=lambda x: x["pnl"])
        
        print(f"\nTop 5 performers:")
        for s in reversed(scored[-5:]):
            print(f"  {s['symbol']}: ₹{s['pnl']:.2f}")
        
        print(f"\nBottom 5 performers:")
        for s in scored[:5]:
            print(f"  {s['symbol']}: ₹{s['pnl']:.2f}")
    else:
        print("\nNo performance data yet")
    
    print(f"\nGitHub scripts: {len(list(STRATEGY_DIR.glob('groww_*.py')))} strategy files")
    print(f"Reserve pool: {len(load_reserve())} scripts queued")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", default="status",
                      choices=["rotate", "status", "rank_reserve"])
    args = parser.parse_args()
    
    if args.action == "status":
        status()
    elif args.action == "rotate":
        rotate_bottom_5()
    elif args.action == "rank_reserve":
        reserve = rank_reserve()
        print(f"Reserve pool: {len(reserve)} scripts")
        for r in reserve[:10]:
            print(f"  {r['symbol']}: {r['estimated_wr']*100:.1f}%")
        save_reserve(reserve)


if __name__ == "__main__":
    main()
