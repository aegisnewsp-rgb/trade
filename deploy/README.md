# Live Trading Scripts — Top 5 Stocks

Production-ready standalone scripts for intraday signal generation and optional Groww API order execution.

## Stocks & Strategies

| Script | Symbol | Strategy | Win Rate | Position | Stop Loss | Target |
|---|---|---|---|---|---|---|
| `live_RELIANCE.py` | RELIANCE.NS | TSI (True Strength Index) | 63.64% | ₹7,000 | 0.8% | 4.0× ATR |
| `live_TCS.py` | TCS.NS | VWAP | 63.64% | ₹7,000 | 0.8% | 4.0× ATR |
| `live_SBIN.py` | SBIN.NS | VWAP | 63.64% | ₹7,000 | 0.8% | 4.0× ATR |
| `live_TITAN.py` | TITAN.NS | VWAP | 61.11% | ₹7,000 | 0.8% | 4.0× ATR |
| `live_HDFCBANK.py` | HDFCBANK.NS | ADX_TREND | 60.61% | ₹7,000 | 0.8% | 4.0× ATR |

**Risk guardrails applied to every script:**
- Position size: ₹7,000 per trade
- Stop loss: 0.8% from entry
- Target: 4.0× current ATR (Average True Range)
- Daily loss cap: 0.3% — skips trading if cap is hit

---

## How to Run

### Prerequisites

```bash
pip install yfinance requests
```

### Run a single script

```bash
python3 deploy/live_RELIANCE.py
python3 deploy/live_TCS.py
python3 deploy/live_SBIN.py
python3 deploy/live_TITAN.py
python3 deploy/live_HDFCBANK.py
```

### Run all 5 (bash loop)

```bash
for script in deploy/live_*.py; do
  echo "Running $script..."
  python3 "$script"
  echo "---"
done
```

### Run on a schedule (cron — market hours only)

```bash
# Run at 9:20 AM IST every weekday
20 9 * * 1-5 cd /home/node/workspace/trade-project && /usr/bin/python3 deploy/live_RELIANCE.py >> deploy/logs/cron_RELIANCE.log 2>&1
25 9 * * 1-5 cd /home/node/workspace/trade-project && /usr/bin/python3 deploy/live_TCS.py    >> deploy/logs/cron_TCS.log    2>&1
30 9 * * 1-5 cd /home/node/workspace/trade-project && /usr/bin/python3 deploy/live_SBIN.py    >> deploy/logs/cron_SBIN.log    2>&1
35 9 * * 1-5 cd /home/node/workspace/trade-project && /usr/bin/python3 deploy/live_TITAN.py  >> deploy/logs/cron_TITAN.log  2>&1
40 9 * * 1-5 cd /home/node/workspace/trade-project && /usr/bin/python3 deploy/live_HDFCBANK.py >> deploy/logs/cron_HDFCBANK.log 2>&1
```

---

## Groww API Integration

### Environment variables

Scripts check for `GROWW_API_KEY` and `GROWW_API_SECRET`.

```bash
export GROWW_API_KEY="your_api_key_here"
export GROWW_API_SECRET="your_api_secret_here"
```

Add to `~/.bashrc` or a `.env` file (loaded by your cron/shell) for persistence.

### How it works

- **Credentials present** → script attempts a real LIMIT order via `POST /v1/orders` on the Groww API, with 3 retries and exponential backoff.
- **No credentials** → script runs in **paper mode**: signal is computed, printed prominently, and logged to `logs/signals_<SYMBOL>.json` — no real order is placed.

### Groww API notes

- Base URL used: `https://api.groww.in/v1`
- Order type: `LIMIT` at the current market price
- Product: `CNC` (Cash & Carry — delivery)
- Exchange: `NSE`

---

## What Each Script Does

```
pre-market (9:00–9:15 IST) → wait / warmup
market open (9:15 IST)      → check daily loss cap
                              fetch 90 days yfinance data
                              compute strategy signal
                              derive stop loss & target
                              log to logs/signals_<SYM>.json
                              place Groww order (if credentials)
market close / done         → exit
```

---

## Logs

All logs go into `deploy/logs/`:

| File | Contents |
|---|---|
| `logs/live_<SYM>.log` | Timestamped execution log (also printed to stdout) |
| `logs/signals_<SYM>.json` | JSON array of all signals with timestamp, price, ATR |
| `logs/daily_pnl_<SYM>.json` | Tracks cumulative daily P&L to enforce 0.3% loss cap |

---

## Strategy Details

### TSI (True Strength Index) — RELIANCE
- Double-smoothed momentum (fast/slow EMA of price change)
- Signal line = EMA of TSI
- **BUY** when TSI crosses above signal line
- **SELL** when TSI crosses below signal line

### VWAP — TCS, SBIN, TITAN
- Cumulative typical price × volume over 14-day rolling window
- ATR-based bands filter false breakouts
- **BUY** when price > VWAP + ATR × 1.5
- **SELL** when price < VWAP − ATR × 1.5

### ADX_TREND — HDFCBANK
- Average Directional Index with EMA smoothing
- **BUY** when +DI crosses above −DI with ADX > 25 (strong trend)
- **SELL** when −DI crosses above +DI with ADX > 25
- **HOLD** when ADX ≤ 25 (no strong trend)

---

## Important Disclaimers

⚠️ **These scripts are for educational and informational purposes only.**
- Not financial advice.
- Paper trade first before using real capital.
- Backtested win rates do not guarantee future performance.
- Always review signals before executing orders.
- Use at your own risk.
