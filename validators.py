"""
validators.py
-------------
All user-input validation lives here — completely decoupled from the CLI
and the API client.  Each function either returns a clean value or raises
ValueError with an actionable message.

Design choice: pure functions (no side effects) make these trivially testable.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional


# ── Constants ──────────────────────────────────────────────────────────────────
VALID_SIDES       = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_MARKET", "TWAP"}

# Binance Futures symbol format: base + USDT (or BUSD, but testnet uses USDT)
def validate_symbol(symbol: str) -> str:
    """
    Normalise and sanity-check a trading symbol.

    Rules
    -----
    - Must be non-empty
    - Uppercase only
    - Must end with a recognised quote currency
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    quote_currencies = ("USDT", "BUSD", "BTC", "ETH", "BNB")
    if not any(symbol.endswith(q) for q in quote_currencies):
        raise ValueError(
            f"Symbol '{symbol}' doesn't end with a recognised quote currency "
            f"({', '.join(quote_currencies)}).  Example: BTCUSDT"
        )
    if len(symbol) < 5:
        raise ValueError(f"Symbol '{symbol}' looks too short.  Example: BTCUSDT")
    return symbol


def validate_side(side: str) -> str:
    side = side.strip().upper()
    if side not in VALID_SIDES:
        raise ValueError(
            f"Side must be one of {VALID_SIDES}.  Got: '{side}'"
        )
    return side


def validate_order_type(order_type: str) -> str:
    order_type = order_type.strip().upper()
    if order_type not in VALID_ORDER_TYPES:
        raise ValueError(
            f"Order type must be one of {VALID_ORDER_TYPES}.  Got: '{order_type}'"
        )
    return order_type


def validate_quantity(quantity: str) -> Decimal:
    """
    Parse and validate order quantity.

    - Must be a positive number
    - Uses Decimal to avoid float precision issues (important for trading)
    """
    try:
        qty = Decimal(str(quantity).strip())
    except InvalidOperation:
        raise ValueError(f"Quantity '{quantity}' is not a valid number.")
    if qty <= 0:
        raise ValueError(f"Quantity must be greater than 0.  Got: {qty}")
    return qty


def validate_price(price: Optional[str], order_type: str) -> Optional[Decimal]:
    """
    Validate price field.

    - Required for LIMIT and STOP_MARKET orders
    - Ignored (and warned about) for MARKET orders
    - Must be positive
    """
    if order_type in ("LIMIT", "STOP_MARKET"):
        if price is None or str(price).strip() == "":
            raise ValueError(
                f"Price is required for {order_type} orders."
            )
        try:
            p = Decimal(str(price).strip())
        except InvalidOperation:
            raise ValueError(f"Price '{price}' is not a valid number.")
        if p <= 0:
            raise ValueError(f"Price must be greater than 0.  Got: {p}")
        return p

    # MARKET / TWAP — price is ignored
    if price is not None and str(price).strip() != "":
        # Don't raise; just let caller warn the user
        pass
    return None


def validate_twap_params(slices: Optional[int], interval_seconds: Optional[int]) -> tuple[int, int]:
    """Validate TWAP-specific parameters."""
    slices = slices or 5
    interval_seconds = interval_seconds or 60

    if not (2 <= slices <= 20):
        raise ValueError("TWAP slices must be between 2 and 20.")
    if not (10 <= interval_seconds <= 3600):
        raise ValueError("TWAP interval must be between 10 and 3600 seconds.")
    return slices, interval_seconds


def validate_all(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: Optional[str] = None,
    twap_slices: Optional[int] = None,
    twap_interval: Optional[int] = None,
) -> dict:
    """
    Run all validations and return a clean params dict, or raise ValueError.
    Single entry point used by both the CLI and any future API/UI layers.
    """
    params = {
        "symbol":     validate_symbol(symbol),
        "side":       validate_side(side),
        "order_type": validate_order_type(order_type),
        "quantity":   validate_quantity(quantity),
        "price":      validate_price(price, order_type.strip().upper()),
    }
    if params["order_type"] == "TWAP":
        slices, interval = validate_twap_params(twap_slices, twap_interval)
        params["twap_slices"]   = slices
        params["twap_interval"] = interval
    return params
