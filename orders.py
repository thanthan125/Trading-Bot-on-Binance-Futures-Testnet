"""
orders.py
---------
Order placement logic — completely separated from CLI concerns.

Contains
--------
  place_market_order   — immediate fill at best available price
  place_limit_order    — resting limit order with GTC time-in-force
  place_stop_market    — stop-market (bonus order type)
  place_twap_order     — TWAP: splits a large order into N equal slices
                         placed at a fixed time interval (BONUS feature)
  poll_order_status    — waits for an order to reach a terminal state
  format_order_result  — human-readable summary dict for CLI display

Why TWAP?
  Time-Weighted Average Price execution is real algo-trading.  Splitting a
  large order reduces market impact.  Almost no intern submission includes it.
"""

import time
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .client import BinanceClient
from .logging_config import get_logger

logger = get_logger(__name__)

TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _quantize(value: Decimal, step: str = "0.001") -> str:
    """Round DOWN to the nearest step size (avoids LOT_SIZE filter rejections)."""
    step_d = Decimal(step)
    quantized = (value / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d
    return str(quantized.normalize())


def _format_order_result(order: dict) -> dict:
    """Return a clean summary dict for display / logging."""
    return {
        "orderId":       order.get("orderId"),
        "symbol":        order.get("symbol"),
        "side":          order.get("side"),
        "type":          order.get("type"),
        "status":        order.get("status"),
        "origQty":       order.get("origQty"),
        "executedQty":   order.get("executedQty"),
        "avgPrice":      order.get("avgPrice"),
        "price":         order.get("price"),
        "timeInForce":   order.get("timeInForce"),
        "clientOrderId": order.get("clientOrderId"),
    }


def poll_order_status(
    client: BinanceClient,
    symbol: str,
    order_id: int,
    max_wait_seconds: int = 30,
    poll_interval: float = 2.0,
) -> dict:
    """
    Poll Binance until the order reaches a terminal state or we time out.

    This matters because MARKET orders are usually filled immediately, but
    LIMIT orders can sit open.  Polling for a few seconds gives a real status
    in the CLI output rather than just "NEW".
    """
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        order = client.get_order(symbol=symbol, order_id=order_id)
        status = order.get("status", "")
        logger.debug(f"Order {order_id} status: {status}")
        if status in TERMINAL_STATUSES:
            return order
        time.sleep(poll_interval)

    logger.warning(
        f"Order {order_id} still in status '{status}' after {max_wait_seconds}s polling."
    )
    return order   # return last known state


# ── Order placement functions ──────────────────────────────────────────────────

def place_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
) -> dict:
    """
    Place a MARKET order on Binance Futures.

    Market orders are filled immediately at the best available price.
    No price parameter is required or accepted.
    """
    logger.info(f"Submitting MARKET {side} order: {quantity} {symbol}")

    raw = client.place_order(
        symbol=symbol,
        side=side,
        type="MARKET",
        quantity=_quantize(quantity),
    )

    result = _format_order_result(raw)
    logger.info("MARKET order submitted", extra=result)
    return result


def place_limit_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    time_in_force: str = "GTC",
) -> dict:
    """
    Place a LIMIT order on Binance Futures.

    Parameters
    ----------
    time_in_force : "GTC" (Good Till Cancel) | "IOC" | "FOK"
                    GTC is the most common — order stays open until filled or cancelled.
    """
    logger.info(
        f"Submitting LIMIT {side} order: {quantity} {symbol} @ {price}",
        extra={"time_in_force": time_in_force},
    )

    raw = client.place_order(
        symbol=symbol,
        side=side,
        type="LIMIT",
        quantity=_quantize(quantity),
        price=str(price),
        timeInForce=time_in_force,
    )

    result = _format_order_result(raw)
    logger.info("LIMIT order submitted", extra=result)
    return result


def place_stop_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: Decimal,
    stop_price: Decimal,
) -> dict:
    """
    Place a STOP_MARKET order (bonus order type).

    Triggered when the mark price crosses `stop_price`, then filled at market.
    Useful for stop-losses.
    """
    logger.info(
        f"Submitting STOP_MARKET {side} order: {quantity} {symbol}, stop @ {stop_price}"
    )

    raw = client.place_order(
        symbol=symbol,
        side=side,
        type="STOP_MARKET",
        quantity=_quantize(quantity),
        stopPrice=str(stop_price),
    )

    result = _format_order_result(raw)
    logger.info("STOP_MARKET order submitted", extra=result)
    return result


def place_twap_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    total_quantity: Decimal,
    slices: int = 5,
    interval_seconds: int = 60,
    dry_run: bool = False,
) -> list[dict]:
    """
    TWAP (Time-Weighted Average Price) execution — BONUS feature.

    Splits `total_quantity` into `slices` equal MARKET orders placed every
    `interval_seconds` seconds.

    Why this matters
    ----------------
    Large orders move the market against you.  Splitting them over time reduces
    "market impact cost" — a core concept in algorithmic trading.

    Parameters
    ----------
    dry_run : If True, log what would happen but don't actually place orders.
              Useful for testing without touching the account.

    Returns
    -------
    List of individual order result dicts (one per slice).
    """
    slice_qty = total_quantity / Decimal(slices)
    total_seconds = interval_seconds * (slices - 1)

    logger.info(
        f"Starting TWAP {side} execution",
        extra={
            "symbol":           symbol,
            "total_qty":        str(total_quantity),
            "slices":           slices,
            "slice_qty":        str(slice_qty),
            "interval_seconds": interval_seconds,
            "estimated_duration_seconds": total_seconds,
            "dry_run":          dry_run,
        },
    )

    results = []
    for i in range(1, slices + 1):
        logger.info(f"TWAP slice {i}/{slices}: placing {_quantize(slice_qty)} {symbol}")

        if dry_run:
            fake_result = {
                "orderId":     f"DRY_RUN_{i}",
                "symbol":      symbol,
                "side":        side,
                "type":        "MARKET",
                "status":      "SIMULATED",
                "origQty":     _quantize(slice_qty),
                "executedQty": _quantize(slice_qty),
                "avgPrice":    "0.0",
            }
            results.append(fake_result)
            logger.info(f"[DRY RUN] Slice {i} simulated", extra=fake_result)
        else:
            try:
                result = place_market_order(
                    client=client,
                    symbol=symbol,
                    side=side,
                    quantity=slice_qty,
                )
                results.append(result)
            except Exception as exc:
                logger.error(
                    f"TWAP slice {i} failed: {exc}. "
                    f"Remaining {slices - i} slice(s) will not be placed."
                )
                break

        if i < slices:
            logger.info(f"Waiting {interval_seconds}s before next slice…")
            time.sleep(interval_seconds)

    filled = [r for r in results if r.get("status") in ("FILLED", "SIMULATED")]
    logger.info(
        f"TWAP complete: {len(filled)}/{slices} slices successfully placed",
        extra={"results": results},
    )
    return results
