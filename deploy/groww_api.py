#!/usr/bin/env python3
"""
Groww Trading API Client - Full Integration
Supports: Authentication, Bracket Orders, Market/Limit Orders, Position Tracking
Docs: https://groww.in/trade-api
"""

import os, time, json, hmac, hashlib, base64, requests
from typing import Optional, Dict, Any, List

API_BASE = "https://api.groww.in"
TOKEN_URL = "/v1/user/tokens"
ORDER_URL = "/v1/orders"
POSITIONS_URL = "/v1/positions"
HOLDINGS_URL = "/v1/holdings"
QUOTE_URL = "/v1/quote"

_access_token = None
_token_expiry = None


def is_configured():
    api_key = os.getenv("GROWW_API_KEY", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")
    return bool(api_key and api_secret)


def get_access_token():
    global _access_token, _token_expiry
    if _access_token and _token_expiry and time.time() < _token_expiry - 300:
        return _access_token
    api_key = os.getenv("GROWW_API_KEY", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")
    if not api_key or not api_secret:
        print("Groww API not configured")
        return None
    timestamp = str(int(time.time() * 1000))
    payload = api_key + timestamp
    sig = hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(sig).decode()
    headers = {
        "Content-Type": "application/json",
        "X-Groww-Auth-Type": "signature",
        "X-Api-Key": api_key,
        "X-Request-Timestamp": timestamp,
        "X-Request-Signature": signature,
    }
    data = {"clientId": api_key, "clientSecret": api_secret, "grantType": "client_credentials"}
    try:
        resp = requests.post(API_BASE + TOKEN_URL, headers=headers, json=data, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            _access_token = result.get("access_token")
            expiry = int(result.get("X-Groww-Expiry-Seconds", 86400))
            _token_expiry = time.time() + expiry
            print("Groww auth OK (token valid {}s)".format(expiry))
            return _access_token
        print("Auth failed: {} {}".format(resp.status_code, resp.text[:200]))
        return None
    except Exception as e:
        print("Auth error: {}".format(e))
        return None


def _hdrs():
    token = get_access_token()
    api_key = os.getenv("GROWW_API_KEY", "")
    return {"Authorization": "Bearer " + token if token else "", "Content-Type": "application/json", "X-Api-Key": api_key}


def get_quote(exchange, symbol):
    try:
        resp = requests.get(API_BASE + QUOTE_URL + "/" + exchange, headers=_hdrs(), params={"symbol": symbol}, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print("Quote error: {}".format(e))
        return None


def get_positions():
    try:
        resp = requests.get(API_BASE + POSITIONS_URL, headers=_hdrs(), timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print("Positions error: {}".format(e))
        return []


def get_holdings():
    try:
        resp = requests.get(API_BASE + HOLDINGS_URL, headers=_hdrs(), timeout=10)
        return resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print("Holdings error: {}".format(e))
        return []


def place_order(order):
    """
    Place a trading order.
    order = {
        "exchange": "NSE", "symbol": "RELIANCE",
        "product": "INTRADAY", "orderType": "BO",
        "transactionType": "BUY", "quantity": 10,
        "targetPrice": 2550.00, "stopLossPrice": 2480.00,
        "trailingTarget": 0.5, "trailingStopLoss": 0.3,
        "validity": "DAY",
    }
    """
    try:
        resp = requests.post(API_BASE + ORDER_URL, headers=_hdrs(), json=order, timeout=10)
        if resp.status_code in (200, 201):
            return resp.json()
        print("Order failed: {} {}".format(resp.status_code, resp.text[:200]))
        return None
    except Exception as e:
        print("Order error: {}".format(e))
        return None


def place_bo(exchange, symbol, transaction, quantity, target_price, stop_loss_price, trailing_sl=0.3, trailing_target=0.5, product="INTRADAY"):
    """Bracket Order: target + stop loss in one order"""
    return place_order({
        "exchange": exchange, "symbol": symbol,
        "product": product, "orderType": "BO",
        "transactionType": transaction, "quantity": quantity,
        "targetPrice": target_price, "stopLossPrice": stop_loss_price,
        "trailingTarget": trailing_target, "trailingStopLoss": trailing_sl,
        "validity": "DAY",
    })


def place_market(exchange, symbol, transaction, quantity, product="INTRADAY"):
    """Market Order"""
    return place_order({
        "exchange": exchange, "symbol": symbol,
        "product": product, "orderType": "MARKET",
        "transactionType": transaction, "quantity": quantity,
        "validity": "DAY",
    })


def place_limit(exchange, symbol, transaction, quantity, price, product="INTRADAY"):
    """Limit Order"""
    return place_order({
        "exchange": exchange, "symbol": symbol,
        "product": product, "orderType": "LIMIT",
        "transactionType": transaction, "quantity": quantity,
        "price": price, "validity": "DAY",
    })


def paper_trade(signal, symbol, price, quantity):
    """Paper trade - emit to signal queue for orchestrator, also print"""
    # Emit to signal queue
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from signals.schema import emit_signal
        emit_signal(
            symbol=symbol, signal=signal, price=price,
            quantity=quantity, strategy="PAPER_MODE",
            atr=price * 0.008,
            metadata={"mode": "paper_trade"}
        )
    except ImportError:
        pass  # signals.schema not available yet
    
    print("[PAPER] {} {}x {} @ Rs{:.2f}".format(signal, quantity, symbol, price))
    return {"orderId": "PAPER_{}".format(int(time.time())), "status": "PAPER_MODE"}


if __name__ == "__main__":
    print("Groww API Client ready")
    if is_configured():
        t = get_access_token()
        if t:
            print("Auth: OK | Positions:", len(get_positions()))
    else:
        print("Mode: PAPER (set GROWW_API_KEY + GROWW_API_SECRET for live)")
