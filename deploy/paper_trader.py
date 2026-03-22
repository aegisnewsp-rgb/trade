#!/usr/bin/env python3
"""
Paper Trading Engine — Non-stop, minimizes loss, maximizes profit.
Uses cached market data, runs 24/7.
"""
import os, sys, json, time, random
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path("/home/node/workspace/trade-project/deploy")
sys.path.insert(0, str(WORKSPACE))

INITIAL_CAPITAL = 100000
POSITION_SIZE = 10000
MAX_DAILY_LOSS = 3000
MAX_POSITIONS = 10
STOP_LOSS_ATR = 1.0
TARGET_ATR = 4.0
TRAILING_ATR = 0.3

LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(LOG_DIR / "paper_trades.log", "a") as f:
        f.write(line + "\n")


def log_trade(trade):
    with open(LOG_DIR / "trade_history.jsonl", "a") as f:
        f.write(json.dumps(trade) + "\n")


_cache_dir = WORKSPACE / "signals" / "cache"
_cache_dir.mkdir(parents=True, exist_ok=True)


def cache_get(symbol, kind, ttl):
    path = _cache_dir / f"{kind}_{symbol}.json"
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


def cache_set(symbol, kind, data):
    data["_t"] = time.time()
    path = _cache_dir / f"{kind}_{symbol}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data


def calc_vwap(ohlcv):
    if not ohlcv:
        return 0
    cum_tp_vol, cum_vol = 0, 0
    for row in ohlcv:
        o, h, l, c, v = row[0], row[1], row[2], row[3], row[4]
        tp = (o + h + l + c) / 4 * v
        cum_tp_vol += tp
        cum_vol += v
    return cum_tp_vol / cum_vol if cum_vol > 0 else 0


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = []
    for i in range(1, len(closes)):
        deltas.append(closes[i] - closes[i-1])
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    return 50 if al == 0 else 100 - (100 / (1 + ag / al))


def calc_atr(ohlcv, period=14):
    if len(ohlcv) < period + 1:
        return 0
    trs = []
    for i in range(1, min(period + 1, len(ohlcv))):
        h, l = ohlcv[i][1], ohlcv[i][2]
        pc = ohlcv[i-1][3]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0


def vol_ratio(ohlcv):
    if len(ohlcv) < 21:
        return 1
    vols = [row[4] for row in ohlcv]
    avg = sum(vols[-20:]) / 20
    return vols[-1] / avg if avg > 0 else 1


def get_market_regime():
    data = cache_get("NIFTY50", "regime", 60)
    if data:
        return data.get("regime", "UNKNOWN")
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI")
        d = nifty.history(period="1mo")
        if len(d) < 20:
            regime = "UNKNOWN"
        else:
            closes = d['Close'].tolist()
            sma20 = sum(closes[-20:]) / 20
            r = closes[-1] / sma20
            regime = "UPTREND" if r > 1.02 else "DOWNTREND" if r < 0.98 else "RANGE"
        cache_set("NIFTY50", "regime", {"regime": regime})
        return regime
    except:
        return "UNKNOWN"


def get_ohlcv(symbol):
    data = cache_get(symbol, "ohlcv", 300)
    if data and data.get("ohlcv"):
        return data["ohlcv"]
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol + ".NS")
        d = ticker.history(period="3mo")
        ohlcv = []
        for _, row in d.iterrows():
            ohlcv.append([float(row['Open']), float(row['High']),
                           float(row['Low']), float(row['Close']), float(row['Volume'])])
        cache_set(symbol, "ohlcv", {"ohlcv": ohlcv})
        return ohlcv
    except:
        return []


def generate_signal(symbol):
    ohlcv = get_ohlcv(symbol)
    if not ohlcv or len(ohlcv) < 25:
        return None, None, None

    closes = [row[3] for row in ohlcv]
    vwap = calc_vwap(ohlcv)
    rsi = calc_rsi(closes)
    atr = calc_atr(ohlcv)
    vr = vol_ratio(ohlcv)
    price = closes[-1]

    regime = get_market_regime()
    if regime == "DOWNTREND":
        return None, None, None

    # Time filter: 9:30 AM - 2:30 PM IST
    now = datetime.now()
    ist = now + timedelta(hours=5, minutes=30)
    if ist.hour < 9 or (ist.hour == 9 and ist.minute < 30):
        return None, None, None
    if ist.hour >= 14 and ist.minute >= 30:
        return None, None, None

    if regime == "RANGE":
        vr_threshold = 1.5
    else:
        vr_threshold = 1.2

    # BUY
    if (price > vwap * 1.005 and rsi > 55 and vr > vr_threshold):
        return "BUY", price, atr
    # SELL
    if (price < vwap * 0.995 and rsi < 45 and vr > vr_threshold):
        return "SELL", price, atr

    return None, None, None


class Portfolio:
    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.positions = {}
        self.daily_pnl = 0
        self.trades_today = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0

    def can_trade(self):
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False
        if len(self.positions) >= MAX_POSITIONS:
            return False
        if self.trades_today >= 5:
            return False
        return True

    def entry(self, symbol, side, price, atr):
        qty = max(1, int(POSITION_SIZE / price))
        cost = qty * price
        if cost > self.cash:
            qty = int(self.cash / price)
            cost = qty * price
        if qty < 1:
            return False

        if side == "BUY":
            sl = round(price - atr * STOP_LOSS_ATR, 2)
            tgt = round(price + atr * TARGET_ATR, 2)
        else:
            sl = round(price + atr * STOP_LOSS_ATR, 2)
            tgt = round(price - atr * TARGET_ATR, 2)

        self.positions[symbol] = {
            "qty": qty, "entry": price, "sl": sl, "tgt": tgt,
            "atr": atr, "side": side, "peak": price
        }
        self.cash -= cost
        self.trades_today += 1
        log(f"ENTRY {side} {qty}x {symbol} @ Rs{price:.2f} | SL:Rs{sl:.2f} TGT:Rs{tgt:.2f}")
        return True

    def check_exit(self, symbol, price):
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        qty = pos["qty"]
        entry = pos["entry"]
        atr = pos["atr"]
        side = pos["side"]

        # Update peak
        if side == "BUY":
            pos["peak"] = max(pos["peak"], price)
        else:
            pos["peak"] = min(pos["peak"], price)

        pnl = (price - entry) * qty if side == "BUY" else (entry - price) * qty
        exited = False
        reason = ""

        if side == "BUY" and price <= pos["sl"]:
            exited, reason = True, "SL"
        elif side == "SELL" and price >= pos["sl"]:
            exited, reason = True, "SL"
        elif side == "BUY" and price >= pos["tgt"]:
            exited, reason = True, "TGT"
        elif side == "SELL" and price <= pos["tgt"]:
            exited, reason = True, "TGT"
        elif pnl > 0:
            trail = pos["peak"] - atr * TRAILING_ATR if side == "BUY" else pos["peak"] + atr * TRAILING_ATR
            if (side == "BUY" and price <= trail) or (side == "SELL" and price >= trail):
                exited, reason = True, "TSL"
        elif self.daily_pnl + pnl <= -MAX_DAILY_LOSS:
            exited, reason = True, "DL"

        if exited:
            self.cash += entry * qty + pnl
            self.daily_pnl += pnl
            self.total_pnl += pnl
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            log(f"EXIT {reason} {symbol} @ Rs{price:.2f} | PnL: Rs{pnl:.2f}")
            log_trade({
                "symbol": symbol, "side": side, "entry": entry, "exit": price,
                "qty": qty, "pnl": pnl, "reason": reason,
                "time": datetime.now().isoformat()
            })
            del self.positions[symbol]

    def status(self):
        pos_value = sum(p["entry"] * p["qty"] for p in self.positions.values())
        total = self.cash + pos_value
        return {
            "cash": self.cash, "total": total,
            "pnl": total - INITIAL_CAPITAL,
            "pnl_pct": (total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100,
            "positions": len(self.positions),
            "daily_pnl": self.daily_pnl,
            "trades": self.trades_today,
            "win_rate": self.wins / (self.wins + self.losses) if (self.wins + self.losses) > 0 else 0,
        }


STOCK_POOL = [
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
iteration = 0
last_status = 0

log("=" * 60)
log(f"PAPER TRADING START | Capital: Rs{INITIAL_CAPITAL:,} | Pool: {len(STOCK_POOL)} stocks")
log("=" * 60)

while True:
    iteration += 1
    now = datetime.now()
    ist = now + timedelta(hours=5, minutes=30)

    # Reset at midnight IST
    if ist.hour == 0 and ist.minute < 5:
        portfolio.daily_pnl = 0
        portfolio.trades_today = 0
        log("NEW DAY reset")

    # Status every minute
    if iteration - last_status >= 6:
        s = portfolio.status()
        log(f"[STATUS] Cash: Rs{s['cash']:.0f} | Total: Rs{s['total']:.0f} | "
            f"PnL: Rs{s['pnl']:.0f} ({s['pnl_pct']:.2f}%) | "
            f"Pos: {s['positions']} | Trades: {s['trades']} | WR: {s['win_rate']*100:.0f}%")
        last_status = iteration

    # Market hours: 9:30 AM - 3:30 PM IST
    market_open = (9 < ist.hour < 15) or (ist.hour == 9 and ist.minute >= 30) or (ist.hour == 15 and ist.minute < 30)

    if market_open:
        # Check exits
        for symbol in list(portfolio.positions.keys()):
            ohlcv = get_ohlcv(symbol)
            if ohlcv:
                portfolio.check_exit(symbol, ohlcv[-1][3])

        # Generate entries
        if portfolio.can_trade():
            for symbol in random.sample(STOCK_POOL, min(5, len(STOCK_POOL))):
                if symbol in portfolio.positions:
                    continue
                sig, price, atr = generate_signal(symbol)
                if sig and atr and atr > 0:
                    portfolio.entry(symbol, sig, price, atr)
                    break

    time.sleep(10)

    # Save state every 5 min
    if iteration % 30 == 0:
        with open(LOG_DIR / "portfolio_state.json", "w") as f:
            json.dump(portfolio.status(), f, indent=2)
