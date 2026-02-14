"""
WebSocket API endpoint

Handles WebSocket connections for real-time streaming:
- ticker:SYMBOL - Price updates
- candle:SYMBOL:TF - Completed candles
- positions - Position updates
- balance - Balance changes
- execution - Trade confirmations

Symbols: from LIGHTER_SYMBOLS or SYMBOLS env (Lighter: ETH,BTC; gTrade: XAUUSD,EURUSD).

Protocol:
    Client → Server:
        {"type": "subscribe", "channel": "ticker:XAUUSD"}
        {"type": "unsubscribe", "channel": "ticker:XAUUSD"}
        {"type": "resume", "data": {"last_seq": 12345}}

    Server → Client:
        {"type": "ticker", "seq": 100, "channel": "ticker:XAUUSD", "data": {...}}
        {"type": "subscribed", "channel": "ticker:XAUUSD"}
        {"type": "error", "error": "Invalid channel"}
        {"type": "resync_required", "data": {"reason": "buffer_overflow"}}
"""


import os


from typing import Optional
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from foundation.config.constants import SUPPORTED_TIMEFRAME
from foundation.logging import get_logger
from infrastructure.ws import get_hub, WSMessageType, create_error_message


logger = get_logger(__name__)


def _get_valid_ws_symbols() -> set[str]:
    """Symbols que el pipeline pot generar (LIGHTER_SYMBOLS, SYMBOLS o default)."""
    raw = os.getenv("LIGHTER_SYMBOLS") or os.getenv("SYMBOLS") or "ETH,BTC,XAUUSD,EURUSD"
    return {s.strip().upper() for s in raw.split(",") if s.strip()}

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time streaming

    Handles:
    - Connection management
    - Subscription requests
    - Resume requests
    - Message broadcasting
    """
    # Accept connection
    await websocket.accept()

    # Generate client ID
    client_id = str(uuid.uuid4())

    # Get hub instance
    hub = get_hub()

    # Register connection
    await hub.connect(websocket, client_id)

    logger.info(f"WebSocket connected: {client_id}")

    try:
        while True:
            # Receive message from client
            try:
                data = await websocket.receive_json()
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from {client_id}: {e}")
                await websocket.send_json(
                    create_error_message(f"Invalid JSON: {e}").to_dict()
                )
                continue

            # Handle message
            msg_type = data.get("type")

            if msg_type == WSMessageType.SUBSCRIBE:
                # Subscribe to channel
                channel = data.get("channel")
                if not channel:
                    await websocket.send_json(
                        create_error_message("Missing channel").to_dict()
                    )
                    continue

                # Validate channel format
                if not _is_valid_channel(channel):
                    await websocket.send_json(
                        create_error_message(f"Invalid channel: {channel}").to_dict()
                    )
                    continue

                await hub.subscribe(client_id, channel)

            elif msg_type == WSMessageType.UNSUBSCRIBE:
                # Unsubscribe from channel
                channel = data.get("channel")
                if not channel:
                    await websocket.send_json(
                        create_error_message("Missing channel").to_dict()
                    )
                    continue

                await hub.unsubscribe(client_id, channel)

            elif msg_type == WSMessageType.RESUME:
                # Resume from last_seq
                resume_data = data.get("data", {})
                last_seq = resume_data.get("last_seq")

                if last_seq is None:
                    await websocket.send_json(
                        create_error_message("Missing last_seq").to_dict()
                    )
                    continue

                if not isinstance(last_seq, int):
                    await websocket.send_json(
                        create_error_message("Invalid last_seq (must be integer)").to_dict()
                    )
                    continue

                # Attempt resume
                success = await hub.resume(client_id, last_seq)
                if not success:
                    logger.warning(f"Resume failed for {client_id}, resync required")

            else:
                # Unknown message type
                await websocket.send_json(
                    create_error_message(f"Unknown message type: {msg_type}").to_dict()
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
    finally:
        # Cleanup
        await hub.disconnect(client_id)


def _is_valid_channel(channel: str) -> bool:
    """
    Validate channel format

    Valid channels:
    - ticker:XAUUSD
    - ticker:EURUSD
    - candle:XAUUSD:1m
    - candle:EURUSD:1m
    - positions
    - balance
    - execution

    Args:
        channel: Channel name

    Returns:
        True if valid, False otherwise
    """
    parts = channel.split(":")

    if len(parts) == 1:
        # Single-part channels: positions, balance, execution
        return channel in ["positions", "balance", "execution"]

    if len(parts) == 2:
        # Two-part channels: ticker:SYMBOL
        channel_type, symbol = parts
        if channel_type == "ticker":
            return symbol.upper() in _get_valid_ws_symbols()

    if len(parts) == 3:
        # Three-part channels: candle:SYMBOL:TF
        channel_type, symbol, timeframe = parts
        if channel_type == "candle":
            return (
                symbol.upper() in _get_valid_ws_symbols()
                and timeframe == SUPPORTED_TIMEFRAME
            )

    return False
