#!/usr/bin/env python3
"""Live Trading Script - KESYC.BO
Strategy: VWAP | Position: ₹7000 | Stop: 0.8%% ATR | Target: 4.0x ATR"""
import os,sys,json,time,logging,requests

import sys
from pathlib import Path
import groww_api
from datetime import datetime,time as dtime
from pathlib import Path
import yfinance as yf

LOG_DIR=Path(__file__).parent/"logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,format="%%(asctime)s [%%(levelname)s] %%(message)s",
    handlers=[logging.FileHandler(LOG_DIR/"live_KESYC.BO.log"),logging.StreamHandler(sys.stdout)])
log=logging.getLogger("live_KESYC.BO")
SYMBOL="KESYC.BO"; STRATEGY="VWAP"; POSITION=7000; STOP_LOSS_PCT=0.008; TARGET_MULT=4.0; DAILY_LOSS_CAP=0.003
PARAMS={"vwap_period":14,"atr_multiplier":1.5}
GROWW_API_KEY=os.getenv("GROWW_API_KEY"); GROWW_API_SECRET=os.getenv("GROWW_API_SECRET")
GROWW_API_BASE="https://api.groww.in/v1"; IST_TZ_OFFSET=5.5

def ist_now(): return datetime.utcnow()+__import__("datetime").timedelta(hours=IST_TZ_OFFSET)
def is_market_open():
    now=ist_now()
    if now.weekday()>=5: return False
    return dtime(9,15)<=now.time()<=dtime(15,30)
def is_pre_market():
    now=ist_now()
    if now.weekday()>=5: return False
    return dtime(9,0)<=now.time()<dtime(9,15)

def fetch_recent_data(days=60,retries=3):
    for attempt in range(retries):
        try:
            df=yf.Ticker(SYMBOL).history(period=f"{days}d")
            if df.empty: raise ValueError("Empty")
            ohlcv=[{"date":str(idx.date()),"open":float(row["Open"]),"high":float(row["High"]),
                    "low":float(row["Low"]),"close":float(row["Close"]),"volume":int(row["Volume"])}
                   for idx,row in df.iterrows()]
            log.info("Fetched %%d candles",len(ohlcv)); return ohlcv
        except Exception as e:
            log.warning("Attempt %%d/%%d: %%s",attempt+1,retries,e); time.sleep(2**attempt)
    log.error("Failed"); return None

def calculate_atr(ohlcv,period=14):
    atr=[]; prev_close=None
    for i,bar in enumerate(ohlcv):
        tr=bar["high"]-bar["low"] if prev_close is None else max(bar["high"]-bar["low"],abs(bar["high"]-prev_close),abs(bar["low"]-prev_close))
        if i<period-1: atr.append(None)
        elif i==period-1: atr.append(tr)
        else: atr.append((atr[-1]*(period-1)+tr)/period)
        prev_close=bar["close"]
    return atr

def calculate_vwap(ohlcv,period=14):
    vwap=[]
    for i in range(len(ohlcv)):
        if i<period-1: vwap.append(None)
        else:
            tp_sum=sum((ohlcv[j]["high"]+ohlcv[j]["low"]+ohlcv[j]["close"])/3 for j in range(i-period+1,i+1))
            vol_sum=sum(ohlcv[j]["volume"] for j in range(i-period+1,i+1))
            vwap.append(tp_sum/vol_sum if vol_sum>0 else 0.0)
    return vwap

def vwap_signal(ohlcv,params):
    period=params["vwap_period"]; atr_mult=params["atr_multiplier"]
    vwap_vals=calculate_vwap(ohlcv,period); atr_vals=calculate_atr(ohlcv,period)
    signals=["HOLD"]*len(ohlcv)
    for i in range(period,len(ohlcv)):
        if vwap_vals[i] is None or atr_vals[i] is None: continue
        price=ohlcv[i]["close"]; v=vwap_vals[i]; a=atr_vals[i]
        if price>v+a*atr_mult: signals[i]="BUY"
        elif price<v-a*atr_mult: signals[i]="SELL"
    return signals[-1] if signals else "HOLD", ohlcv[-1]["close"], atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
def log_signal(signal,price,atr):
    log_file=LOG_DIR/"signals_KESYC.BO.json"; entries=[]
    if log_file.exists():
        try: entries=json.loads(log_file.read_text())
        except: pass
    entries.append({"timestamp":ist_now().isoformat(),"symbol":SYMBOL,"strategy":STRATEGY,"signal":signal,"price":round(price,4),"atr":round(atr,4)})
    entries[-500:]; log_file.write_text(json.dumps(entries[-500:],indent=2))
    log.info("Signal: %%s @ ₹%%.2f (ATR=%%.4f)",signal,price,atr)

def daily_loss_limit_hit():
    cap_file=LOG_DIR/"daily_pnl_KESYC.BO.json"; today_str=ist_now().strftime("%%Y-%%m-%%d")
    if cap_file.exists():
        try:
            data=json.loads(cap_file.read_text())
            if data.get("date")==today_str and data.get("loss_pct",0)>=DAILY_LOSS_CAP: return True
        except: pass
    return False

def main():
    log.info("=== %%s | %%s | Win Rate: 63.64%% ===",SYMBOL,STRATEGY)
    while is_pre_market(): log.info("Pre-market..."); time.sleep(30)
    if not is_market_open(): log.info("Market closed"); return
    if daily_loss_limit_hit(): log.warning("Daily loss cap hit"); return
    ohlcv=fetch_recent_data(days=90)
    if not ohlcv or len(ohlcv)<30: log.error("Insufficient data"); return
    signal,price,atr=vwap_signal(ohlcv,PARAMS)
    if signal=="BUY": stop_loss=round(price*(1-STOP_LOSS_PCT),2); target_prc=round(price+TARGET_MULT*atr,2)
    elif signal=="SELL": stop_loss=round(price*(1+STOP_LOSS_PCT),2); target_prc=round(price-TARGET_MULT*atr,2)
    else: stop_loss=0.0; target_prc=0.0
    quantity=max(1,int(POSITION/price))
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  SYMBOL: %%s  STRATEGY: %%s  SIGNAL: ★ %%s ★",SYMBOL,STRATEGY,signal)
    log.info("  PRICE: ₹%%.2f  QTY: %%d shares (₹%%d)",price,quantity,POSITION)
    if atr>0: log.info("  ATR: %%.4f  STOP: ₹%%.2f  TARGET: ₹%%.2f (%%.1fx)",atr,stop_loss,target_prc,TARGET_MULT)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log_signal(signal,price,atr)
    if signal!="HOLD" and GROWW_API_KEY and GROWW_API_SECRET:
        result=place_groww_order(SYMBOL,signal,quantity,price)
        if result: log.info("✓ Executed: %%s",result)
        else: log.warning("⚠ Order failed")
    elif signal!="HOLD": log.info("📋 Paper mode")

def place_groww_order(symbol, signal, quantity, price):
    """
    Emit trading signal to queue for Master Orchestrator.
    Orchestrator coalesces all signals and places orders via Groww API
    (single connection = no rate limiting across 468 scripts).
    Paper mode: orchestrator prints signals instead of placing.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from signals.schema import emit_signal
        # Get ATR from script's atr variable if available
        _atr = price * 0.008
        try:
            if 'atr' in globals() and isinstance(globals().get('atr'), (int, float)):
                _atr = float(globals()['atr'])
        except:
            _atr = price * 0.008
        _strategy = str(globals().get('STRATEGY_NAME', 'VWAP'))
        emit_signal(
            symbol=symbol, signal=signal, price=price,
            quantity=quantity, strategy=_strategy, atr=_atr,
            metadata={"source": Path(__file__).name}
        )
        return {"status": "queued", "symbol": symbol, "signal": signal}
    except ImportError:
        print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
        return {"status": "paper", "symbol": symbol, "signal": signal}


def place_order(symbol, signal, quantity, price):
    return place_groww_order(symbol, signal, quantity, price)

if __name__=="__main__": main()
