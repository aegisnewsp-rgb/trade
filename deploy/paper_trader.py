#!/usr/bin/env python3
"""Paper Trading Engine - Non-stop, minimizes loss, maximizes profit."""
import os, sys, json, time, random
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
sys.path.insert(0, str(WORKSPACE))

INITIAL_CAPITAL = 100000
POSITION_SIZE = 10000
MAX_DAILY_LOSS = 3000
MAX_POSITIONS = 10
ATR_SL = 1.0
ATR_TGT = 4.0
ATR_TSL = 0.3

LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(exist_ok=True)
_cache_dir = WORKSPACE / "signals" / "cache"
_cache_dir.mkdir(parents=True, exist_ok=True)

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")
    with open(LOG_DIR / "paper_trades.log", "a") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")

def log_trade(trade):
    with open(LOG_DIR / "trade_history.jsonl", "a") as f:
        f.write(json.dumps(trade) + "\n")

def cg(sym, kind, ttl):
    path = _cache_dir / f"{kind}_{sym}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if time.time() - data.get("_t", 0) > ttl:
            return None
        return data
    except:
        return None

def cs(sym, kind, data):
    data["_t"] = time.time()
    path = _cache_dir / f"{kind}_{sym}.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return data

def calc_vwap(ohlcv):
    if not ohlcv:
        return 0
    ct, cv = 0.0, 0.0
    for row in ohlcv:
        o, h, l, c, v = row[0], row[1], row[2], row[3], row[4]
        ct += (o + h + l + c) / 4.0 * v
        cv += v
    return ct / cv if cv > 0.0 else 0.0

def calc_rsi(closes, p=14):
    if len(closes) < p + 1:
        return 50.0
    ds = []
    for i in range(1, len(closes)):
        ds.append(closes[i] - closes[i-1])
    g = [d if d > 0.0 else 0.0 for d in ds[-p:]]
    l = [-d if d < 0.0 else 0.0 for d in ds[-p:]]
    ag = sum(g) / float(p)
    al = sum(l) / float(p)
    return 50.0 if al == 0.0 else 100.0 - (100.0 / (1.0 + ag / al))

def calc_atr(ohlcv, p=14):
    if len(ohlcv) < p + 1:
        return 0.0
    trs = []
    for i in range(1, min(p + 1, len(ohlcv))):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / float(len(trs)) if trs else 0.0

def vol_ratio(ohlcv):
    if len(ohlcv) < 21:
        return 1.0
    vols = [row[4] for row in ohlcv]
    avg = sum(vols[-20:]) / 20.0
    return vols[-1] / avg if avg > 0.0 else 1.0

def market_regime():
    d = cg("NIFTY50", "regime", 60)
    if d:
        return d.get("regime", "UNKNOWN")
    try:
        import yfinance as yf
        n = yf.Ticker("^NSEI").history(period="1mo")
        if len(n) < 20:
            r = "UNKNOWN"
        else:
            c = n['Close'].tolist()
            sma = sum(c[-20:]) / 20.0
            ratio = c[-1] / sma if sma > 0.0 else 1.0
            r = "UPTREND" if ratio > 1.02 else "DOWNTREND" if ratio < 0.98 else "RANGE"
        cs("NIFTY50", "regime", {"regime": r})
        return r
    except:
        return "UNKNOWN"

def get_ohlcv(sym):
    d = cg(sym, "ohlcv", 300)
    if d and d.get("ohlcv"):
        return d["ohlcv"]
    try:
        import yfinance as yf
        t = yf.Ticker(sym + ".NS").history(period="3mo")
        data = []
        for _, r in t.iterrows():
            data.append([float(r['Open']), float(r['High']), float(r['Low']),
                         float(r['Close']), float(r['Volume'])])
        cs(sym, "ohlcv", {"ohlcv": data})
        return data
    except:
        return []

def get_signal(sym):
    ohlcv = get_ohlcv(sym)
    if not ohlcv or len(ohlcv) < 25:
        return None, None, None
    closes = [row[3] for row in ohlcv]
    vwap = calc_vwap(ohlcv)
    rsi = calc_rsi(closes)
    atr = calc_atr(ohlcv)
    price = closes[-1]
    reg = market_regime()
    if reg == "DOWNTREND":
        return None, None, None
    now = datetime.now() + timedelta(hours=5, minutes=30)
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return None, None, None
    if now.hour >= 14 and now.minute >= 30:
        return None, None, None
    vr_thresh = 1.5 if reg == "RANGE" else 1.2
    if price > vwap * 1.005 and rsi > 55.0 and vol_ratio(ohlcv) > vr_thresh:
        return "BUY", price, atr
    if price < vwap * 0.995 and rsi < 45.0 and vol_ratio(ohlcv) > vr_thresh:
        return "SELL", price, atr
    return None, None, None

class Portfolio:
    def __init__(self):
        self.cash = float(INITIAL_CAPITAL)
        self.positions = {}
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.wins = 0
        self.losses = 0

    def can_trade(self):
        if self.daily_pnl <= -float(MAX_DAILY_LOSS):
            return False
        if len(self.positions) >= MAX_POSITIONS:
            return False
        if self.trades_today >= 5:
            return False
        return True

    def entry(self, sym, side, price, atr):
        qty = max(1, int(POSITION_SIZE / price))
        cost = float(qty) * float(price)
        if cost > self.cash:
            qty = int(self.cash / price)
            cost = float(qty) * float(price)
        if qty < 1:
            return False
        if side == "BUY":
            sl = round(price - atr * ATR_SL, 2)
            tgt = round(price + atr * ATR_TGT, 2)
        else:
            sl = round(price + atr * ATR_SL, 2)
            tgt = round(price - atr * ATR_TGT, 2)
        self.positions[sym] = {
            "qty": qty, "entry": float(price), "sl": sl, "tgt": tgt,
            "atr": float(atr), "side": side, "peak": float(price)
        }
        self.cash -= cost
        self.trades_today += 1
        log(f"ENTRY {side} {qty}x {sym} @ Rs{price:.2f} SL:Rs{sl:.2f} TGT:Rs{tgt:.2f}")
        return True

    def check_exit(self, sym, price):
        if sym not in self.positions:
            return
        p = self.positions[sym]
        qty = p["qty"]
        entry = p["entry"]
        atr = p["atr"]
        side = p["side"]
        if side == "BUY":
            p["peak"] = max(p["peak"], price)
        else:
            p["peak"] = min(p["peak"], price)
        pnl = (float(price) - entry) * float(qty) if side == "BUY" else (entry - float(price)) * float(qty)
        exited = False
        reason = ""
        if side == "BUY" and float(price) <= p["sl"]:
            exited, reason = True, "SL"
        elif side == "SELL" and float(price) >= p["sl"]:
            exited, reason = True, "SL"
        elif side == "BUY" and float(price) >= p["tgt"]:
            exited, reason = True, "TGT"
        elif side == "SELL" and float(price) <= p["tgt"]:
            exited, reason = True, "TGT"
        elif pnl > 0.0:
            trail = p["peak"] - atr * ATR_TSL if side == "BUY" else p["peak"] + atr * ATR_TSL
            if (side == "BUY" and float(price) <= trail) or (side == "SELL" and float(price) >= trail):
                exited, reason = True, "TSL"
        if self.daily_pnl + pnl <= -float(MAX_DAILY_LOSS):
            exited, reason = True, "DL"
        if exited:
            self.cash += entry * float(qty) + pnl
            self.daily_pnl += pnl
            if pnl > 0.0:
                self.wins += 1
            else:
                self.losses += 1
            log(f"EXIT {reason} {sym} @ Rs{price:.2f} PnL: Rs{pnl:.2f}")
            log_trade({"symbol": sym, "side": side, "entry": entry, "exit": float(price),
                       "qty": qty, "pnl": pnl, "reason": reason,
                       "time": datetime.now().isoformat()})
            del self.positions[sym]

    def status(self):
        pv = sum(p["entry"] * float(p["qty"]) for p in self.positions.values())
        total = self.cash + pv
        wr = float(self.wins) / float(self.wins + self.losses) if (self.wins + self.losses) > 0 else 0.0
        return {
            "cash": self.cash, "total": total,
            "pnl": total - float(INITIAL_CAPITAL),
            "pnl_pct": (total - float(INITIAL_CAPITAL)) / float(INITIAL_CAPITAL) * 100.0,
            "positions": len(self.positions),
            "daily_pnl": self.daily_pnl,
            "trades": self.trades_today,
            "win_rate": wr,
        }

POOL = [
    "ADANIPOWER", "ADANIGREEN", "ADANIPORTS", "RELIANCE", "TCS",
    "SBIN", "HDFCBANK", "TITAN", "TATASTEEL", "COALINDIA",
    "CIPLA", "SRF", "IGL", "BANKINDIA", "NESTLEIND",
    "MARUTI", "HINDALCO", "HCLTECH", "HEROMOTOCO", "M&M",
    "KOTAKBANK", "AXISBANK", "ICICIBANK", "BAJFINANCE", "SBILIFE",
    "NTPC", "POWERGRID", "ONGC", "GAIL", "BPCL",
    "ITC", "HINDUNILVR", "BRITANNIA", "DMART", "VEDL",
    "INFY", "WIPRO", "TECHM", "SUNPHARMA", "DRREDDY",
]

portfolio = Portfolio()
iter_count = 0
last_status = 0

log(f"PAPER TRADING START | Capital: Rs{INITIAL_CAPITAL:,} | Pool: {len(POOL)} stocks")

while True:
    iter_count += 1
    now = datetime.now() + timedelta(hours=5, minutes=30)
    if now.hour == 0 and now.minute < 5:
        portfolio.daily_pnl = 0.0
        portfolio.trades_today = 0
        log("NEW DAY reset")
    if iter_count - last_status >= 6:
        s = portfolio.status()
        log(f"[STATUS] Cash: Rs{s['cash']:.0f} Total: Rs{s['total']:.0f} "
            f"PnL: Rs{s['pnl']:.0f} ({s['pnl_pct']:.2f}%) "
            f"Pos: {s['positions']} Trades: {s['trades']} WR: {s['win_rate']*100:.0f}%")
        last_status = iter_count
    market_open = ((9 < now.hour < 15) or
                  (now.hour == 9 and now.minute >= 30) or
                  (now.hour == 15 and now.minute < 30))
    if market_open:
        for sym in list(portfolio.positions.keys()):
            ohlcv = get_ohlcv(sym)
            if ohlcv:
                portfolio.check_exit(sym, ohlcv[-1][3])
        if portfolio.can_trade():
            for sym in random.sample(POOL, min(5, len(POOL))):
                if sym in portfolio.positions:
                    continue
                sig, price, atr = get_signal(sym)
                if sig and atr and atr > 0.0:
                    portfolio.entry(sym, sig, price, atr)
                    break
    time.sleep(10)
    if iter_count % 30 == 0:
        with open(LOG_DIR / "portfolio_state.json", "w") as f:
            json.dump(portfolio.status(), f, indent=2)
