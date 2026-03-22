#!/usr/bin/env python3
"""
Groww Trading API Client
Supports: Authentication, Strategy Creation, Order Placement, Bracket Orders
Docs: https://groww.in/trade-api
"""

import os
import time
import json
import hmac
import hashlib
import base64
import requests
from typing import Optional, Dict, Any, List

API_BASE = "https://api.groww.in"
TOKEN_URL = "/v1/user/tokens"
STRATEGY_URL = "/v1/strategies"
ORDER_URL = "/v1/orders"
POSITIONS_URL = "/v1/positions"
HOLDINGS_URL = "/v1/holdings"
QUOTE_URL = "/v1/quote"

# Token storage
_access_token = None
_token_expiry = None


def is_configured() -> bool:
    api_key = os.getenv("GROWW_API_KEY", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")
    return bool(api_key and api_secret)


def _sign_payload(payload: str) -> str:
    api_secret = os.getenv("GROWW_API_SECRET", "")
    signature = hmac.new(
        api_secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode()


def get_access_token() -> Optional[str]:
    global _access_token, _token_expiry
    
    if _access_token and _token_expiry and time.time() < _token_expiry - 300:
        return _access_token
    
    api_key = os.getenv("GROWW_API_KEY", "")
    api_secret = os.getenv("GROWW_API_SECRET", "")
    
    if not api_key or not api_secret:
        print("Groww API not configured (set GROWW_API_KEY and GROWW_API_SECRET)")
        return None
    
    timestamp = str(int(time.time() * 1000))
    payload_str = api_key + timestamp
    signature = _sign_payload(payload_str)
    
    headers = {
        "Content-Type": "application/json",
        "X-Groww-Auth-Type": "signature",
        "X-Api-Key": api_key,
        "X-Request-Timestamp": timestamp,
        "X-Request-Signature": signature,
    }
    
    data = {
        "clientId": api_key,
        "clientSecret": api_secret,
        "grantType": "client_credentials",
    }
    
    try:
        resp = requests.post(
            API_BASE + TOKEN_URL,
            headers=headers,
            json=data,
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            global _access_token, _token_expiry
            _access_token = result.get("access_token")
            expiry = int(result.get("X-Groww-Expiry-Seconds", 86400))
            _token_expiry = time.time() + expiry
            print(f"Groww auth success (token expires in {expiry}s)")
            return _access_token
        else:
            print(f"Groww auth failed: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"Groww auth error: {e}")
        return None


def _headers() -> Dict[str, str]:
    token = get_access_token()
    api_key = os.getenv("GROWW_API_KEY", "")
    return {
        "Authorization": "Bearer " + token if token else "",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }


def get_quote(exchange: str, symbol: str) -> Optional[Dict]:
    try:
        resp = requests.get(
            API_BASE + QUOTE_URL + "/" + exchange,
            headers=_headers(),
            params={"symbol": symbol},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"Quote error: {e}")
        return None


def get_positions() -> List[Dict]:
    try:
        resp = requests.get(
            API_BASE + POSITIONS_URL,
            headers=_headers(),
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"Positions error: {e}")
        return []


def get_holdings() -> List[Dict]:
    try:
        resp = requests.get(
            API_BASE + HOLDINGS_URL,
            headers=_headers(),
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"Holdings error: {e}")
        return []


def place_order(order: Dict) -> Optional[Dict]:
    """
    Place a trading order.
    
    order = {
        "exchange": "NSE",
        "symbol": "RELIANCE",
        "product": "INTRADAY",  # INTRADAY, DELIVERY, MARGIN
        "orderType": "MARKET",  # MARKET, LIMIT, BO (Bracket Order)
        "transactionType": "BUY",  # BUY, SELL
        "quantity": 10,
        "price": 2500.00,        # For LIMIT orders
        "triggerPrice": 2490.00,  # For BO trigger
        "targetPrice": 2550.00,  # For BO target
        "stopLossPrice": 2480.00, # For BO stop loss
        "trailingTarget": 0.5,   # % trailing target
        "trailingStopLoss": 0.3, # % trailing stop loss
        "validity": "DAY",       # DAY, IOC
    }
    """
    try:
        resp = requests.post(
            API_BASE + ORDER_URL,
            headers=_headers(),
            json=order,
            timeout=10
        )
        if resp.status_code in (200, 201):
            return resp.json()
        print(f"Order failed: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"Order error: {e}")
        return None


def place_bracket_order(
    exchange: str,
    symbol: str,
    transaction: str,  # BUY or SELL
    quantity: int,
    target_price: float,
    stop_loss_price: float,
    trailing_sl: float = 0.3,
    trailing_target: float = 0.5,
    product: str = "INTRADAY"
) -> Optional[Dict]:
    """Convenience method for Bracket Orders (BO) with target + stop loss"""
    order = {
        "exchange": exchange,
        "symbol": symbol,
        "product": product,
        "orderType": "BO",
        "transactionType": transaction,
        "quantity": quantity,
        "targetPrice": target_price,
        "stopLossPrice": stop_loss_price,
        "trailingTarget": trailing_target,
        "trailingStopLoss": trailing_sl,
        "validity": "DAY",
    }
    return place_order(order)


def place_market_order(
    exchange: str,
    symbol: str,
    transaction: str,
    quantity: int,
    product: str = "INTRADAY"
) -> Optional[Dict]:
    """Convenience method for Market Orders"""
    order = {
        "exchange": exchange,
        "symbol": symbol,
        "product": product,
        "orderType": "MARKET",
        "transactionType": transaction,
        "quantity": quantity,
        "validity": "DAY",
    }
    return place_order(order)


def place_limit_order(
    exchange: str,
    symbol: str,
    transaction: str,
    quantity: int,
    price: float,
    product: str = "INTRADAY"
) -> Optional[Dict]:
    """Convenience method for Limit Orders"""
    order = {
        "exchange": exchange,
        "symbol": symbol,
        "product": product,
        "orderType": "LIMIT",
        "transactionType": transaction,
        "quantity": quantity,
        "price": price,
        "validity": "DAY",
    }
    return place_order(order)


def create_strategy(strategy: Dict) -> Optional[Dict]:
    """Create a trading strategy"""
    try:
        resp = requests.post(
            API_BASE + STRATEGY_URL,
            headers=_headers(),
            json=strategy,
            timeout=10
        )
        if resp.status_code in (200, 201):
            return resp.json()
        print(f"Strategy creation failed: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"Strategy error: {e}")
        return None


def list_strategies() -> List[Dict]:
    try:
        resp = requests.get(
            API_BASE + STRATEGY_URL,
            headers=_headers(),
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"List strategies error: {e}")
        return []


def paper_trade(signal: str, symbol: str, price: float, quantity: int):
    """Paper trade mode - print signal instead of placing order"""
    print(f"[PAPER] {signal} {quantity} {symbol} @ Rs{price:.2f}")
    return {"orderId": f"PAPER_{int(time.time())}", "status": "PAPER_MODE"}


if __name__ == "__main__":
    print("=" * 60)
    print("Groww Trading API Client")
    print("=" * 60)
    
    if is_configured():
        token = get_access_token()
        if token:
            print("Authenticated:", token[:20] + "...")
            positions = get_positions()
            print("Open positions:", len(positions))
    else:
        print("Paper mode (set GROWW_API_KEY and GROWW_API_SECRET for live)")
    
    print("=" * 60)
