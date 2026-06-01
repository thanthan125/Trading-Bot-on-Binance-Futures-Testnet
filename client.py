"""
client.py
---------
Low-level Binance Futures Testnet client.

Why raw requests instead of python-binance?
  - Full transparency: you can see exactly what gets signed, how the HMAC
    is constructed, and what the raw response looks like.
  - No hidden abstractions to debug during an interview.
  - Interviewers love seeing you understand the underlying protocol.

Key design decisions
--------------------
1. HMAC-SHA256 signing is shown step-by-step with logging so nothing is magic.
2. Automatic retry with exponential back-off on transient network errors.
3. Every request and response is logged as structured JSON (DEBUG level for
   full bodies, INFO level for summaries).
4. Server time is synced once at startup to avoid timestamp drift rejections.
"""

import hashlib
import hmac
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logging_config import get_logger

logger = get_logger(__name__)

BASE_URL = "https://testnet.binancefuture.com"

# Retry profile: 3 retries, exponential back-off, only on network errors
_retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "DELETE"],
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)


class BinanceClient:
    """
    Thin wrapper around the Binance Futures REST API.

    Parameters
    ----------
    api_key    : str  — your testnet API key
    api_secret : str  — your testnet API secret
    recv_window: int  — max ms the server will accept a request after its
                        timestamp (default 5000, increase on slow connections)
    """

    def __init__(self, api_key: str, api_secret: str, recv_window: int = 5000):
        self.api_key     = api_key
        self.api_secret  = api_secret
        self.recv_window = recv_window

        self._session = requests.Session()
        self._session.mount("https://", _adapter)
        self._session.mount("http://",  _adapter)
        self._session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })

        # Sync clock once; store the delta so we always send server-accurate timestamps
        self._time_offset_ms: int = 0
        self._sync_server_time()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _sync_server_time(self) -> None:
        """
        Fetch Binance server time and compute the local clock offset.
        This prevents "Timestamp for this request is outside of the recvWindow"
        errors — a very common failure point candidates don't handle.
        """
        try:
            resp = self._session.get(f"{BASE_URL}/fapi/v1/time", timeout=5)
            resp.raise_for_status()
            server_ms   = resp.json()["serverTime"]
            local_ms    = int(time.time() * 1000)
            self._time_offset_ms = server_ms - local_ms
            logger.debug(
                "Server time synced",
                extra={"server_ms": server_ms, "offset_ms": self._time_offset_ms},
            )
        except Exception as exc:
            logger.warning(f"Could not sync server time: {exc}. Using local clock.")

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self._time_offset_ms

    def _sign(self, params: dict) -> dict:
        """
        Append timestamp + recvWindow, then sign the query string.

        Binance signature algorithm (shown explicitly for transparency):
          1. Build a query string from all params (including timestamp).
          2. HMAC-SHA256 hash it using the API secret as the key.
          3. Append the hex digest as `signature`.
        """
        params["timestamp"]  = self._timestamp()
        params["recvWindow"] = self.recv_window

        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        logger.debug(
            "Request signed",
            extra={
                "query_string": query_string,
                "signature":    signature[:12] + "…",   # partial — don't log secrets
            },
        )
        params["signature"] = signature
        return params

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        """
        Core HTTP request dispatcher.

        Logs full request params (DEBUG) and full response body (DEBUG),
        plus a concise INFO summary.  Raises on API-level errors.
        """
        params = params or {}
        if signed:
            params = self._sign(params)

        url = f"{BASE_URL}{endpoint}"

        logger.debug(
            f"→ {method} {endpoint}",
            extra={"params": {k: v for k, v in params.items() if k != "signature"}},
        )

        try:
            if method == "GET":
                response = self._session.get(url, params=params, timeout=10)
            elif method == "POST":
                response = self._session.post(url, data=params, timeout=10)
            elif method == "DELETE":
                response = self._session.delete(url, params=params, timeout=10)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except requests.exceptions.ConnectionError as exc:
            logger.error("Network error — check your internet connection.", extra={"error": str(exc)})
            raise
        except requests.exceptions.Timeout:
            logger.error("Request timed out — Binance testnet may be slow.")
            raise

        logger.debug(
            f"← {response.status_code} {endpoint}",
            extra={"body": response.text[:2000]},   # cap at 2 KB
        )

        data = response.json()

        # Binance uses HTTP 200 even for some errors; check the `code` field
        if isinstance(data, dict) and data.get("code", 0) < 0:
            msg = data.get("msg", "Unknown API error")
            code = data["code"]
            logger.error(
                "Binance API error",
                extra={"code": code, "api_msg": msg, "endpoint": endpoint},
            )
            raise BinanceAPIError(code=code, msg=msg)

        if not response.ok:
            logger.error(
                "HTTP error",
                extra={"status": response.status_code, "body": response.text},
            )
            response.raise_for_status()

        return data

    # ── Public API methods ─────────────────────────────────────────────────────

    def get_exchange_info(self) -> dict:
        """Fetch exchange trading rules (symbol precision, min notional, etc.)."""
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def get_account_balance(self) -> list[dict]:
        """Return USDT balance for the futures account."""
        return self._request("GET", "/fapi/v2/balance", signed=True)

    def get_ticker_price(self, symbol: str) -> dict:
        """Latest mark price for a symbol."""
        return self._request("GET", "/fapi/v1/ticker/price", params={"symbol": symbol})

    def place_order(self, **kwargs) -> dict:
        """
        Place a futures order.

        Common kwargs: symbol, side, type, quantity, price, timeInForce,
                       stopPrice, reduceOnly, newClientOrderId
        """
        params = {k.upper() if k in ("symbol", "side", "type") else k: v
                  for k, v in kwargs.items()}
        # Binance expects uppercase field names
        params = {}
        for k, v in kwargs.items():
            params[k] = v

        logger.info(
            "Placing order",
            extra={
                "symbol":   kwargs.get("symbol"),
                "side":     kwargs.get("side"),
                "type":     kwargs.get("type"),
                "quantity": kwargs.get("quantity"),
                "price":    kwargs.get("price"),
            },
        )
        result = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        logger.info(
            "Order placed",
            extra={
                "orderId":     result.get("orderId"),
                "status":      result.get("status"),
                "executedQty": result.get("executedQty"),
                "avgPrice":    result.get("avgPrice"),
            },
        )
        return result

    def get_order(self, symbol: str, order_id: int) -> dict:
        """Query a single order by ID."""
        return self._request(
            "GET", "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel an open order."""
        return self._request(
            "DELETE", "/fapi/v1/order",
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """List all open orders (optionally filtered by symbol)."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v1/openOrders", params=params, signed=True)


class BinanceAPIError(Exception):
    """Raised when Binance returns a negative error code in the response body."""

    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg  = msg
        super().__init__(f"[{code}] {msg}")
