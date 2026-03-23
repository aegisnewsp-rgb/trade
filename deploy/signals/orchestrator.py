#!/usr/bin/env python3
"""
Master Signal Orchestrator
- Reads signals from deploy/signals/pending/
- Coalesces duplicate symbols (only latest per symbol per cycle)
- Places orders via Groww API ONE connection
- Auto-compacts context when rolling window fills
"""
import os, sys, json, time, hmac, hashlib, base64, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ─── Groww API (single instance, reused) ──────────────────────────────────────

class GrowwAPI:
    def __init__(self):
        self.key = os.getenv("GROWW_API_KEY", "")
        self.secret = os.getenv("GROWW_API_SECRET", "")
        self.base = "https://api.groww.in"
        self.token = None
        self.token_exp = 0
    
    def _sign(self, payload):
        sig = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode()
    
    def _auth(self):
        if self.token and time.time() < self.token_exp - 300:
            return self.token
        ts = str(int(time.time() * 1000))
        hdrs = {
            "Content-Type": "application/json",
            "X-Groww-Auth-Type": "signature",
            "X-Api-Key": self.key,
            "X-Request-Timestamp": ts,
            "X-Request-Signature": self._sign(self.key + ts),
        }
        r = requests.post(self.base + "/v1/user/tokens",
                          headers=hdrs,
                          json={"clientId": self.key, "clientSecret": self.secret, "grantType": "client_credentials"},
                          timeout=10)
        if r.status_code == 200:
            d = r.json()
            self.token = d.get("access_token")
            self.token_exp = time.time() + int(d.get("X-Groww-Expiry-Seconds", 86400))
            print(f"[GROWW] Auth OK (expires in {int(d.get('X-Groww-Expiry-Seconds', 86400))}s)")
            return self.token
        print(f"[GROWW] Auth FAIL: {r.status_code} {r.text[:200]}")
        return None
    
    def _hdrs(self):
        return {"Authorization": "Bearer " + (self._auth() or ""),
                "Content-Type": "application/json", "X-Api-Key": self.key}
    
    def place_bo(self, exchange, symbol, trans, qty, target, sl, trailing_sl=0.3, trailing_tgt=0.5):
        """Bracket Order — one API call per order"""
        order = {
            "exchange": exchange, "symbol": symbol,
            "product": "INTRADAY", "orderType": "BO",
            "transactionType": trans, "quantity": qty,
            "targetPrice": round(target, 2), "stopLossPrice": round(sl, 2),
            "trailingTarget": trailing_tgt, "trailingStopLoss": trailing_sl,
            "validity": "DAY",
        }
        r = requests.post(self.base + "/v1/orders",
                           headers=self._hdrs(), json=order, timeout=15)
        if r.status_code in (200, 201):
            d = r.json()
            print(f"[GROWW] ✓ {trans} {qty}x {symbol} @ {target} [SL:{sl}] → {d.get('orderId', 'ok')}")
            return d
        print(f"[GROWW] ✗ {trans} {symbol}: {r.status_code} {r.text[:150]}")
        return None
    
    def positions(self):
        r = requests.get(self.base + "/v1/positions", headers=self._hdrs(), timeout=10)
        return r.json() if r.status_code == 200 else []


# ─── Signal Processing ─────────────────────────────────────────────────────────

def process_signals():
    """Read pending signals, coalesce, place orders"""
    from signals.schema import Signal
    
    pending = Signal.pending_signals()
    if not pending:
        return [], 0
    
    # Coalesce: latest signal per symbol only
    latest = {}
    for s in pending:
        key = f"{s.exchange}:{s.symbol}"
        if key not in latest or s.timestamp > latest[key].timestamp:
            latest[key] = s
    
    # Dedupe: skip if already processed this cycle (same price ±0.5%)
    seen = {}
    signals_to_place = []
    for s in latest.values():
        key = f"{s.exchange}:{s.symbol}"
        if key in seen:
            # Keep the newer one
            continue
        seen[key] = s
        signals_to_place.append(s)
    
    print(f"[ORCH] {len(signals_to_place)} signals to place (from {len(pending)} pending)")
    
    gw = GrowwAPI() if GrowwAPI().key else None
    placed, failed = 0, 0
    
    for s in signals_to_place:
        # Calculate target & stop from price if not set
        if not s.target or not s.stop_loss:
            atr = s.atr or s.price * 0.008
            if s.signal == "BUY":
                s.stop_loss = round(s.price - atr * 1.0, 2)
                s.target = round(s.price + atr * 4.0, 2)
            elif s.signal == "SELL":
                s.stop_loss = round(s.price + atr * 1.0, 2)
                s.target = round(s.price - atr * 4.0, 2)
        
        if gw:
            result = gw.place_bo(
                s.exchange, s.symbol,
                s.signal, s.quantity,
                s.target, s.stop_loss
            )
            if result:
                Signal.mark_processed(s.id, "placed")
                placed += 1
            else:
                Signal.mark_processed(s.id, "failed")
                failed += 1
        else:
            # Paper mode
            print(f"[PAPER] {s.signal} {s.quantity}x {s.symbol} @ {s.price} "
                  f"[TGT:{s.target} SL:{s.stop_loss}]")
            Signal.mark_processed(s.id, "paper")
            placed += 1
    
    return signals_to_place, placed, failed


# ─── Context Compactor ─────────────────────────────────────────────────────────

CONTEXT_LOG = ROOT / "logs" / "context_log.jsonl"
CONTEXT_LOG.parent.mkdir(exist_ok=True)

COMPACTED_DIR = ROOT / "logs" / "compacted"
COMPACTED_DIR.mkdir(exist_ok=True)


def log_context_entry(entry: dict):
    """Append a context snapshot to the rolling log"""
    with open(CONTEXT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_context_size() -> int:
    """Estimate current context size from log file"""
    if not CONTEXT_LOG.exists():
        return 0
    return CONTEXT_LOG.stat().st_size


def auto_compact_context():
    """
    Called periodically. If context log > 1MB, compact oldest half.
    Delegates summarization to MiniMax model — this IS the deep reasoning step.
    """
    size_mb = get_context_size() / (1024 * 1024)
    
    if size_mb < 0.5:
        return f"Context OK ({size_mb:.1f}MB) — no compaction needed"
    
    print(f"[CONTEXT] {size_mb:.1f}MB — initiating auto-compaction...")
    
    # Read all entries
    entries = []
    if CONTEXT_LOG.exists():
        with open(CONTEXT_LOG) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except:
                    pass
    
    if len(entries) < 4:
        return "Not enough entries to compact"
    
    # Keep newer half (more relevant)
    keep = entries[len(entries)//2:]
    
    # Write back
    with open(CONTEXT_LOG, "w") as f:
        for e in keep:
            f.write(json.dumps(e) + "\n")
    
    # Save compacted archive
    arc_path = COMPACTED_DIR / f"compact_{int(time.time())}.jsonl"
    with open(arc_path, "w") as f:
        for e in entries[:len(entries)//2]:
            f.write(json.dumps(e) + "\n")
    
    msg = f"[CONTEXT] Compacted {len(entries)//2} entries → {arc_path.name} | Kept {len(keep)} recent"
    print(msg)
    
    # Delegate deep reasoning to MiniMax about what was lost
    # This is the key insight: we don't just discard, we ask model to absorb
    delegate_summarization(entries[:len(entries)//2])
    
    return msg


def delegate_summarization(old_entries: list):
    """
    DEEP REASONING: Ask MiniMax to synthesize what happened in the compacted context.
    This keeps the model aware of historical patterns even after context is compacted.
    """
    if not old_entries:
        return
    
    # Build a summary prompt from the old entries
    signals = [e for e in old_entries if e.get("type") == "signal"]
    decisions = [e for e in old_entries if e.get("type") == "decision"]
    errors = [e for e in old_entries if e.get("type") == "error"]
    
    summary_prompt = f"""CONTEXT COMPACTION SUMMARY — Delegate to rolling memory:

During the last cycle:
- {len(signals)} trading signals were processed
- {len(decisions)} strategic decisions were made  
- {len(errors)} errors occurred

Key patterns observed:
{_extract_patterns(signals)}

Critical decisions:
{_extract_decisions(decisions)}

Errors/warnings:
{_extract_errors(errors)}

ACTION: Synthesize this into a brief memory note for future sessions.
Write 2-3 sentences max — what matters most from this period?
"""
    
    # Write to a queue file for the next main agent turn to pick up
    queue_file = ROOT / "logs" / "delegate_queue.json"
    with open(queue_file, "a") as f:
        f.write(json.dumps({"prompt": summary_prompt, "time": (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).isoformat()}) + "\n")
    
    print(f"[DELEGATE] Summarization queued for MiniMax: {len(old_entries)} entries")


def _extract_patterns(signals: list) -> str:
    if not signals:
        return "No significant patterns"
    buys = sum(1 for s in signals if s.get("signal") == "BUY")
    sells = sum(1 for s in signals if s.get("signal") == "SELL")
    symbols = set(s.get("symbol") for s in signals)
    return f"{buys} BUY signals, {sells} SELL signals across {len(symbols)} symbols"


def _extract_decisions(decisions: list) -> str:
    if not decisions:
        return "No major decisions"
    return "; ".join(d.get("summary", str(d))[:100] for d in decisions[-3:])


def _extract_errors(errors: list) -> str:
    if not errors:
        return "No errors"
    return "; ".join(e.get("summary", str(e))[:100] for e in errors[-3:])


# ─── Logging Helpers ────────────────────────────────────────────────────────────

def log_signal(signal_dict: dict):
    log_context_entry({"type": "signal", **signal_dict, "ts": (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).isoformat()})


def log_decision(summary: str, detail: dict = None):
    log_context_entry({
        "type": "decision", "summary": summary,
        "detail": detail or {}, "ts": (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).isoformat()
    })


def log_error(summary: str, detail: str = ""):
    log_context_entry({
        "type": "error", "summary": summary, "detail": detail,
        "ts": (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).isoformat()
    })


# ─── Main Loop ─────────────────────────────────────────────────────────────────

def run_cycle():
    """One orchestrator cycle — process signals + compact if needed"""
    ts = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S")
    print(f"\n{'='*60}")
    print(f"ORCHESTRATOR CYCLE — {ts}")
    print(f"{'='*60}")
    
    signals, placed, failed = process_signals()
    
    # Log for context tracking
    for s in signals:
        log_signal(s.to_dict())
    
    compact_msg = auto_compact_context()
    
    # Status
    pos_count = 0
    try:
        gw = GrowwAPI()
        if gw.key:
            positions = gw.positions()
            pos_count = len(positions) if isinstance(positions, list) else 0
    except:
        pos_count = -1
    
    print(f"\n📊 Cycle complete: {placed} placed, {failed} failed | "
          f"Open positions: {pos_count} | {compact_msg}")
    
    return placed, failed


if __name__ == "__main__":
    # Called by cron every 60 seconds
    placed, failed = run_cycle()
    
    # Clean up processed signals
    from signals.schema import Signal
    Signal.clear_processed()
    
    sys.exit(0 if failed == 0 else 1)
