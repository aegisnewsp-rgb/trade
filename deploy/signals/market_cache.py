#!/usr/bin/env python3
"""
Groww Market Data Cache — Avoid rate limits, speed up agents.
Cache OHLCV, quotes, and signals locally.
TTL: 1 minute for quotes, 5 minutes for OHLCV.
"""
import os, json, time
from pathlib import Path
from datetime import datetime, timedelta
from functools import lru_cache

CACHE_DIR = Path("/home/node/workspace/trade-project/deploy/signals/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# TTL in seconds
QUOTE_TTL = 60      # 1 minute for live quotes
OHLCV_TTL = 300     # 5 minutes for OHLCV data
SIGNAL_TTL = 30      # 30 seconds for signals


def _cache_path(key: str, kind: str) -> Path:
    return CACHE_DIR / f"{kind}_{key}.json"


def _now():
    return time.time()


def cache_get(key: str, kind: str, ttl: int) -> dict | None:
    """Get cached data if fresh."""
    path = _cache_path(key, kind)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        age = _now() - data.get("_cached_at", 0)
        if age > ttl:
            return None
        return data
    except:
        return None


def cache_set(key: str, kind: str, data: dict):
    """Write to cache."""
    data["_cached_at"] = _now()
    data["_cached_key"] = key
    path = _cache_path(key, kind)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data


def cache_invalidate(key: str, kind: str):
    """Clear specific cache."""
    path = _cache_path(key, kind)
    if path.exists():
        path.unlink()


def cache_clear(kind: str = None):
    """Clear all or specific kind."""
    if kind:
        for p in CACHE_DIR.glob(f"{kind}_*"):
            p.unlink()
    else:
        for p in CACHE_DIR.glob("*"):
            if p.is_file():
                p.unlink()


def cached_quote(symbol: str, exchange: str = "NSE") -> dict | None:
    """Get cached quote or None."""
    key = f"{exchange}:{symbol}"
    return cache_get(key, "quote", QUOTE_TTL)


def fetch_and_cache_quote(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch fresh quote, cache it, return."""
    import requests
    
    key = f"{exchange}:{symbol}"
    # Try Groww quote API
    try:
        r = requests.get(
            f"https://api.groww.in/v1/quote/{exchange}",
            params={"symbol": symbol},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            return cache_set(key, "quote", data)
    except:
        pass
    
    # Fallback: yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.replace(".NS", "").replace(".BO", "") + ".NS")
        hist = ticker.history(period="1d")
        if not hist.empty:
            row = hist.iloc[-1]
            data = {
                "symbol": symbol,
                "exchange": exchange,
                "lastPrice": float(row["Close"]),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "volume": int(row["Volume"]),
                "source": "yfinance"
            }
            return cache_set(key, "quote", data)
    except:
        pass
    
    return {"error": "fetch_failed", "symbol": symbol}


def cached_ohlcv(symbol: str, period: str = "3mo", exchange: str = "NSE") -> dict | None:
    """Get cached OHLCV or None."""
    key = f"{exchange}:{symbol}:{period}"
    return cache_get(key, "ohlcv", OHLCV_TTL)


def fetch_and_cache_ohlcv(symbol: str, period: str = "3mo", exchange: str = "NSE") -> dict:
    """Fetch fresh OHLCV, cache it, return."""
    key = f"{exchange}:{symbol}:{period}"
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.replace(".NS", "").replace(".BO", "") + ".NS")
        data = ticker.history(period=period)
        
        ohlcv_list = []
        for idx, row in data.iterrows():
            ohlcv_list.append({
                "date": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        
        result = {
            "symbol": symbol,
            "exchange": exchange,
            "period": period,
            "ohlcv": ohlcv_list,
            "count": len(ohlcv_list)
        }
        return cache_set(key, "ohlcv", result)
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def get_cached_signals() -> list:
    """Get all recent signals from cache."""
    signals = []
    for p in CACHE_DIR.glob("signal_*"):
        try:
            with open(p) as f:
                signals.append(json.load(f))
        except:
            pass
    signals.sort(key=lambda x: x.get("_cached_at", 0), reverse=True)
    return signals


def market_summary() -> dict:
    """Get market summary from cache."""
    summary_file = CACHE_DIR / "market_summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            data = json.load(f)
        age = _now() - data.get("_cached_at", 0)
        if age < QUOTE_TTL:
            return data
    
    # Build fresh summary
    nifty_quote = fetch_and_cache_quote("NIFTY 50", "^NSEI")
    
    summary = {
        "time": datetime.now().isoformat(),
        "nifty": nifty_quote,
        "cache_size": len(list(CACHE_DIR.glob("*"))),
    }
    summary["_cached_at"] = _now()
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--symbol", default="RELIANCE")
    args = parser.parse_args()
    
    if args.clear:
        cache_clear()
        print("Cache cleared")
    elif args.stats:
        files = list(CACHE_DIR.glob("*"))
        print(f"Cache: {len(files)} files")
        for f in sorted(files)[:10]:
            age = _now() - f.stat().st_mtime
            print(f"  {f.name}: {age:.0f}s old")
    else:
        # Test fetch
        print(f"Fetching {args.symbol}...")
        q = fetch_and_cache_quote(args.symbol)
        print(json.dumps(q, indent=2)[:300])
