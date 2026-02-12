"""
WebSocket Hub - Real-time message broadcasting

Features:
- Connection management (connect/disconnect)
- Channel subscriptions (subscribe/unsubscribe)
- Sequence numbers for all messages
- Replay buffer for resume functionality
- Broadcast to subscribed clients

Usage:
    hub = WebSocketHub(buffer_size=1000)
    await hub.connect(websocket, client_id)
    await hub.subscribe(client_id, "ticker:XAUUSD")
    await hub.broadcast("ticker:XAUUSD", data)
    await hub.disconnect(client_id)
"""


from collections import deque
from datetime import datetime
from typing import Dict, Set, Optional, List
import asyncio

from fastapi import WebSocket

from infrastructure.ws.models import (


    WSMessage,
    WSMessageType,
    create_subscribed_message,
    create_unsubscribed_message,
    create_error_message,
    create_resync_required_message,
)
from foundation.logging import get_logger

logger = get_logger(__name__)


class WebSocketHub:
    """
    WebSocket Hub for real-time broadcasting

    Manages:
    - Client connections (WebSocket instances)
    - Channel subscriptions (client → channels mapping)
    - Sequence numbers (monotonic, global)
    - Message buffer (for resume functionality)
    """

    def __init__(self, buffer_size: int = 1000):
        """
        Initialize WebSocket Hub

        Args:
            buffer_size: Maximum number of messages to keep in replay buffer
        """
        self._connections: Dict[str, WebSocket] = {}  # client_id → WebSocket
        self._subscriptions: Dict[str, Set[str]] = {}  # client_id → set of channels
        self._channel_subscribers: Dict[str, Set[str]] = {}  # channel → set of client_ids

        self._seq: int = 0  # Global sequence number
        self._buffer: deque = deque(maxlen=buffer_size)  # Replay buffer
        self._buffer_size = buffer_size

        self._lock = asyncio.Lock()  # For thread-safe operations

        logger.info(f"WebSocketHub initialized (buffer_size={buffer_size})")

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """
        Register new WebSocket connection

        Args:
            websocket: FastAPI WebSocket instance
            client_id: Unique client identifier
        """
        async with self._lock:
            self._connections[client_id] = websocket
            self._subscriptions[client_id] = set()

        logger.info(f"Client connected: {client_id}")

    async def disconnect(self, client_id: str) -> None:
        """
        Unregister WebSocket connection and cleanup subscriptions

        Args:
            client_id: Client to disconnect
        """
        async with self._lock:
            # Remove all subscriptions for this client
            if client_id in self._subscriptions:
                for channel in self._subscriptions[client_id]:
                    if channel in self._channel_subscribers:
                        self._channel_subscribers[channel].discard(client_id)
                        if not self._channel_subscribers[channel]:
                            del self._channel_subscribers[channel]

                del self._subscriptions[client_id]

            # Remove connection
            if client_id in self._connections:
                del self._connections[client_id]

        logger.info(f"Client disconnected: {client_id}")

    async def subscribe(self, client_id: str, channel: str) -> bool:
        """
        Subscribe client to a channel

        Args:
            client_id: Client ID
            channel: Channel name (e.g., "ticker:XAUUSD", "positions")

        Returns:
            True if subscribed successfully, False otherwise
        """
        if client_id not in self._connections:
            logger.warning(f"Subscribe failed: client {client_id} not connected")
            return False

        async with self._lock:
            # Add to client's subscriptions
            if client_id not in self._subscriptions:
                self._subscriptions[client_id] = set()
            self._subscriptions[client_id].add(channel)

            # Add to channel's subscribers
            if channel not in self._channel_subscribers:
                self._channel_subscribers[channel] = set()
            self._channel_subscribers[channel].add(client_id)

        logger.info(f"Client {client_id} subscribed to {channel}")

        # Send confirmation
        await self._send_to_client(client_id, create_subscribed_message(channel))

        return True

    async def unsubscribe(self, client_id: str, channel: str) -> bool:
        """
        Unsubscribe client from a channel

        Args:
            client_id: Client ID
            channel: Channel name

        Returns:
            True if unsubscribed successfully, False otherwise
        """
        if client_id not in self._connections:
            return False

        async with self._lock:
            # Remove from client's subscriptions
            if client_id in self._subscriptions:
                self._subscriptions[client_id].discard(channel)

            # Remove from channel's subscribers
            if channel in self._channel_subscribers:
                self._channel_subscribers[channel].discard(client_id)
                if not self._channel_subscribers[channel]:
                    del self._channel_subscribers[channel]

        logger.info(f"Client {client_id} unsubscribed from {channel}")

        # Send confirmation
        await self._send_to_client(client_id, create_unsubscribed_message(channel))

        return True

    async def broadcast(self, channel: str, message: WSMessage) -> int:
        """
        Broadcast message to all subscribers of a channel

        Args:
            channel: Channel name
            message: Message to broadcast (seq will be assigned)

        Returns:
            Number of clients message was sent to
        """
        # Assign sequence number
        async with self._lock:
            self._seq += 1
            message.seq = self._seq

            # Add to buffer
            self._buffer.append((self._seq, message))

        # Get subscribers (outside lock to avoid blocking)
        subscribers = self._channel_subscribers.get(channel, set()).copy()

        if not subscribers:
            logger.debug(f"No subscribers for channel {channel}")
            return 0

        # Broadcast to all subscribers
        sent_count = 0
        for client_id in subscribers:
            success = await self._send_to_client(client_id, message)
            if success:
                sent_count += 1

        logger.debug(f"Broadcasted seq={message.seq} to {sent_count}/{len(subscribers)} clients on {channel}")
        return sent_count

    async def resume(self, client_id: str, last_seq: int) -> bool:
        """
        Replay messages since last_seq for a client

        Args:
            client_id: Client requesting resume
            last_seq: Last sequence number client received

        Returns:
            True if resume succeeded, False if resync required
        """
        if client_id not in self._connections:
            return False

        async with self._lock:
            current_seq = self._seq
            buffer_list = list(self._buffer)

            # Check if last_seq is in buffer range
            if not buffer_list:
                # Empty buffer, no messages to replay
                logger.info(f"Resume for {client_id}: empty buffer")
                return True

            oldest_seq = buffer_list[0][0]
            newest_seq = buffer_list[-1][0]

            if last_seq < oldest_seq:
                # last_seq too old, buffer overflow
                logger.warning(f"Resume failed for {client_id}: last_seq={last_seq} < oldest={oldest_seq}")
                await self._send_to_client(
                    client_id,
                    create_resync_required_message(
                        reason="buffer_overflow",
                        last_available_seq=oldest_seq,
                    )
                )
                return False

            if last_seq > newest_seq:
                # last_seq in future? Should not happen
                logger.warning(f"Resume for {client_id}: last_seq={last_seq} > current={newest_seq}")
                return True

        # Replay messages from buffer
        client_channels = self._subscriptions.get(client_id, set())
        replayed = 0

        for seq, msg in buffer_list:
            if seq <= last_seq:
                continue  # Skip already received messages

            # Only send messages from subscribed channels
            if msg.channel and msg.channel in client_channels:
                await self._send_to_client(client_id, msg)
                replayed += 1

        logger.info(f"Resume for {client_id}: replayed {replayed} messages (from seq={last_seq+1})")
        return True

    async def _send_to_client(self, client_id: str, message: WSMessage) -> bool:
        """
        Send message to a specific client

        Args:
            client_id: Client ID
            message: Message to send

        Returns:
            True if sent successfully, False otherwise
        """
        websocket = self._connections.get(client_id)
        if not websocket:
            return False

        try:
            await websocket.send_json(message.to_dict())
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {client_id}: {e}")
            # Don't disconnect here, let the endpoint handler deal with it
            return False

    def get_stats(self) -> Dict[str, any]:
        """Get hub statistics"""
        return {
            "connected_clients": len(self._connections),
            "total_subscriptions": sum(len(subs) for subs in self._subscriptions.values()),
            "active_channels": len(self._channel_subscribers),
            "current_seq": self._seq,
            "buffer_size": len(self._buffer),
            "buffer_capacity": self._buffer_size,
        }


# Global hub instance (singleton)
_hub_instance: Optional[WebSocketHub] = None


def get_hub(buffer_size: int = 1000) -> WebSocketHub:
    """
    Get or create global WebSocketHub instance

    Args:
        buffer_size: Buffer size (only used if creating new instance)

    Returns:
        WebSocketHub singleton
    """
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = WebSocketHub(buffer_size=buffer_size)
    return _hub_instance
