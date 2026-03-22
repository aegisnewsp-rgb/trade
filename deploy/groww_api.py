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
from datetime import datetime, timedelta

# =============================================================================
# CONFIGURATION
# =============================================================================

class GrowwConfig:
    API_BASE = "https://api.groww.in"
    TOKEN_URL = "/v1/user/tokens"
    STRATEGY_URL = "/v1/strategies"
    ORDER_URL = "/v1/orders"
    POSITIONS_URL = "/v1/positions"
    HOLDINGS_URL = "/v1/holdings"
    QUOTE_URL = "/v1/quote"
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or os.getenv("GROWW_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET", "")
        self.access_token = None
        self.token_expiry = None
        
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)
    
    def is_token_valid(self) -> bool:
        if not self.access_token or not self.token_expiry:
            return False
        return time.time() < self.token_expiry - 300  # 5 min buffer


# =============================================================================
# AUTHENTICATION
# =============================================================================

class GrowwAuth:
    """Handle Groww API authentication using HMAC-SHA256 signing"""
    
    def __init__(self, config: GrowwConfig):
        self.config = config
    
    def sign_payload(self, payload: str) -> str:
        """Generate HMAC-SHA256 signature"""
        signature = hmac.new(
            self.config.api_secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode()
    
    def get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token using client credentials"""
        if self.config.is_token_valid():
            return self.config.access_token
        
        if not self.config.is_configured():
            print("⚠️  Groww API not configured (set GROWW_API_KEY and GROWW_API_SECRET)")
            return None
        
        # Prepare signed request
        timestamp = str(int(time.time() * 1000))
        payload = f"{self.config.api_key}{timestamp}"
        signature = self.sign_payload(payload)
        
        headers = {
            "Content-Type": "application/json",
            "X-Groww-Auth-Type": "signature",
            "X-Api-Key": self.config.api_key,
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": signature,
        }
        
        data = {
            "clientId": self.config.api_key,
            "clientSecret": self.config.api_secret,
            "grantType": "client_credentials",
        }
        
        try:
            resp = requests.post(
                f"{self.config.API_BASE}{self.config.TOKEN_URL}",
                headers=headers,
                json=data,
                timeout=10
            )
            
            if resp.status_code == 200:
                result = resp.json()
                self.config.access_token = result.get("access_token")
                expiry = int(result.get("X-Groww-Expiry-Seconds", 86400))
                self.config.token_expiry = time.time() + expiry
                print(f"✅ Groww auth success (token expires in {expiry}s)")
                return self.config.access_token
            else:
                print(f"❌ Groww auth failed: {resp.status_code} {resp.text}")
                return None
                
        except Exception as e:
            print(f"❌ Groww auth error: {e}")
            return None


# =============================================================================
# API CLIENT
# =============================================================================

class GrowwClient:
    """Main Groww Trading API client with full order management"""
    
    def __init__(self, config: GrowwConfig = None):
        self.config = config or GrowwConfig()
        self.auth = GrowwAuth(self.config)
        self.session = requests.Session()
    
    def _headers(self) -> Dict[str, str]:
        """Build request headers with auth"""
        token = self.auth.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Api-Key": self.config.api_key,
        }
    
    def _get(self, url: str, params: dict = None) -> Optional[Dict]:
        try:
            resp = self.session.get(
                f"{self.config.API_BASE}{url}",
                headers=self._headers(),
                params=params,
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                # Token expired, refresh
                self.config.access_token = None
                self.config.token_expiry = None
                return None
            else:
                print(f"GET {url} → {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"GET error: {e}")
            return None
    
    def _post(self, url: str, data: dict) -> Optional[Dict]:
        try:
            resp = self.session.post(
                f"{self.config.API_BASE}{url}",
                headers=self._headers(),
                json=data,
                timeout=10
            )
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 401:
                self.config.access_token = None
                self.config.token_expiry = None
                return None
            else:
                print(f"POST {url} → {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"POST error: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # QUOTES
    # -------------------------------------------------------------------------
    
    def get_quote(self, exchange: str, symbol: str) -> Optional[Dict]:
        """Get current quote for a symbol"""
        return self._get(
            f"{self.config.QUOTE_URL}/{exchange}",
            params={"symbol": symbol}
        )
    
    def get_quotes_batch(self, quotes: List[Dict]) -> Optional[Dict]:
        """Batch quotes: [{"exchange": "NSE", "symbol": "RELIANCE"}]"""
        return self._post(f"{self.config.QUOTE_URL}/batch", {"quotes": quotes})
    
    # -------------------------------------------------------------------------
    # POSITIONS & HOLDINGS
    # -------------------------------------------------------------------------
    
    def get_positions(self) -> Optional[List[Dict]]:
        """Get current open positions"""
        result = self._get(self.config.POSITIONS_URL)
        return result if result else []
    
    def get_holdings(self) -> Optional[List[Dict]]:
        """Get current holdings (delivered positions)"""
        result = self._get(self.config.HOLDINGS_URL)
        return result if result else []
    
    # -------------------------------------------------------------------------
    # STRATEGIES
    # -------------------------------------------------------------------------
    
    def list_strategies(self) -> Optional[List[Dict]]:
        """List all trading strategies"""
        return self._get(self.config.STRATEGY_URL)
    
    def create_strategy(self, strategy: Dict) -> Optional[Dict]:
        """Create a new trading strategy"""
        return self._post(self.config.STRATEGY_URL, strategy)
    
    def activate_strategy(self, strategy_id: str) -> bool:
        """Activate a strategy by ID"""
        result = self._post(f"{self.config.STRATEGY_URL}/{strategy_id}/activate", {})
        return result is not None
    
    def deactivate_strategy(self, strategy_id: str) -> bool:
        """Deactivate a strategy"""
        result = self._post(f"{self.config.STRATEGY_URL}/{strategy_id}/deactivate", {})
        return result is not None
    
    # -------------------------------------------------------------------------
    # ORDERS
    # -------------------------------------------------------------------------
    
    def place_order(self, order: Dict) -> Optional[Dict]:
        """
        Place a trading order.
        
        order = {
            "exchange": "NSE",
            "symbol": "RELIANCE",
            "product": "INTRADAY",  # INTRADAY, DELIVERY, MARGIN
            "orderType": "MARKET",  # MARKET, LIMIT, BO
            "transactionType": "BUY",  # BUY, SELL
            "quantity": 10,
            "price": 2500.00,       # For LIMIT orders
            "triggerPrice": 2490.00,  # For BO trigger
            "targetPrice": 2550.00,   # For BO target
            "stopLossPrice": 2480.00,  # For BO stop loss
            "trailingTarget": 0.5,    # % trailing target
            "trailingStopLoss": 0.3,  # % trailing stop loss
            "validity": "DAY"          # DAY, IOC
        }
        """
        return self._post(self.config.ORDER_URL, order)
    
    def place_bracket_order(
        self,
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
        """Convenience method for Bracket Orders"""
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
        return self.place_order(order)
    
    def place_market_order(
        self,
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
        return self.place_order(order)
    
    def place_limit_order(
        self,
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
        return self.place_order(order)


# =============================================================================
# HIGH-LEVEL TRADING FUNCTIONS
# =============================================================================

def get_client() -> Optional[GrowwClient]:
    """Get configured Groww client"""
    config = GrowwConfig()
    if not config.is_configured():
        print("⚠️  Set GROWW_API_KEY and GROWW_API_SECRET to enable live trading")
        print("    Currently running in PAPER MODE")
        return None
    return GrowwClient(config)


def get_nearest_support_resistance(lookback: int = 20) -> Dict:
    """Get support/resistance from recent data (to be implemented per script)"""
    return {"support": None, "resistance": None}


# =============================================================================
# MAIN / TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Groww Trading API Client")
    print("=" * 60)
    
    client = get_client()
    
    if client:
        # Test authentication
        token = client.auth.get_access_token()
        if token:
            print(f"✅ Authenticated: {token[:20]}...")
            
            # Test positions
            positions = client.get_positions()
            print(f"📊 Open positions: {len(positions) if positions else 0}")
            
            # Test quote
            quote = client.get_quote("NSE", "RELIANCE")
            if quote:
                print(f"📈 RELIANCE quote: {quote}")
        else:
            print("❌ Authentication failed")
    else:
        print("📝 Paper mode (no API credentials)")
        print("   Set env vars: GROWW_API_KEY, GROWW_API_SECRET")
    
    print("=" * 60)
