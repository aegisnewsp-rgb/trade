#!/usr/bin/env python3
"""
Signal Schema —统一信号格式
All worker scripts write signals here, master orchestrator reads from here.
"""
import os, json, time
from datetime import datetime

SIGNAL_DIR = os.path.join(os.path.dirname(__file__), "pending")
os.makedirs(SIGNAL_DIR, exist_ok=True)


class Signal:
    """Standardized trading signal format"""
    
    def __init__(
        self,
        symbol: str,
        signal: str,       # BUY | SELL | CLOSE
        price: float,
        quantity: int,
        strategy: str,     # VWAP | ADX_TREND | etc
        exchange: str = "NSE",
        target: float = None,
        stop_loss: float = None,
        atr: float = None,
        confidence: float = None,  # 0.0-1.0
        metadata: dict = None,
    ):
        self.id = f"{symbol}_{int(time.time() * 1000)}"
        self.symbol = symbol
        self.exchange = exchange
        self.signal = signal
        self.price = round(price, 4)
        self.quantity = quantity
        self.strategy = strategy
        self.target = round(target, 4) if target else None
        self.stop_loss = round(stop_loss, 4) if stop_loss else None
        self.atr = round(atr, 4) if atr else None
        self.confidence = round(confidence, 4) if confidence else None
        self.metadata = metadata or {}
        self.timestamp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30).isoformat() + "Z"
        self.status = "pending"
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "signal": self.signal,
            "price": self.price,
            "quantity": self.quantity,
            "strategy": self.strategy,
            "target": self.target,
            "stop_loss": self.stop_loss,
            "atr": self.atr,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "status": self.status,
            **self.metadata,
        }
    
    def save(self):
        """Write signal to pending queue"""
        path = os.path.join(SIGNAL_DIR, f"{self.symbol}_{self.id}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path
    
    @classmethod
    def load(cls, path: str) -> "Signal":
        with open(path) as f:
            data = json.load(f)
        s = cls.__new__(cls)
        for k, v in data.items():
            setattr(s, k, v)
        return s
    
    @classmethod
    def pending_signals(cls) -> list:
        """Load all pending signals"""
        signals = []
        for fname in os.listdir(SIGNAL_DIR):
            if fname.endswith(".json"):
                try:
                    signals.append(cls.load(os.path.join(SIGNAL_DIR, fname)))
                except:
                    pass
        return sorted(signals, key=lambda s: s.timestamp)
    
    @classmethod
    def clear_processed(cls):
        """Remove processed signals"""
        for fname in os.listdir(SIGNAL_DIR):
            if fname.endswith(".json"):
                path = os.path.join(SIGNAL_DIR, fname)
                try:
                    s = cls.load(path)
                    if s.status != "pending":
                        os.remove(path)
                except:
                    pass
    
    @classmethod
    def mark_processed(cls, signal_id: str, status: str = "placed"):
        """Mark a signal as processed"""
        for fname in os.listdir(SIGNAL_DIR):
            if signal_id in fname:
                path = os.path.join(SIGNAL_DIR, fname)
                try:
                    s = cls.load(path)
                    s.status = status
                    with open(path, "w") as f:
                        json.dump(s.to_dict(), f, indent=2)
                except:
                    pass


def emit_signal(symbol, signal, price, quantity, strategy, **kwargs):
    """Quick helper for workers — create and save signal in one call"""
    s = Signal(symbol=symbol, signal=signal, price=price,
               quantity=quantity, strategy=strategy, **kwargs)
    path = s.save()
    print(f"[SIGNAL QUEUED] {signal} {quantity}x {symbol} @ {price} → {path}")
    return s
