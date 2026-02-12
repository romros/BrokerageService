"""
WebSocket message models

Defines message structure for WS communication:
- Client → Server: subscribe, unsubscribe, resume
- Server → Client: ticker, candle, position, balance, execution, resync_required
"""


from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Literal


class WSMessageType(str, Enum):
    """WebSocket message types"""
    # Client → Server
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    RESUME = "resume"

    # Server → Client (data)
    TICKER = "ticker"
    CANDLE = "candle"
    POSITION = "position"
    BALANCE = "balance"
    EXECUTION = "execution"

    # Server → Client (control)
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    ERROR = "error"
    RESYNC_REQUIRED = "resync_required"


class WSChannelType(str, Enum):
    """WebSocket channel types"""
    TICKER = "ticker"      # ticker:XAUUSD
    CANDLE = "candle"      # candle:XAUUSD:1m
    POSITIONS = "positions"  # positions (all user positions)
    BALANCE = "balance"    # balance (user balance)
    EXECUTION = "execution"  # execution (trade confirmations)


@dataclass
class WSMessage:
    """
    Base WebSocket message

    All messages have:
    - type: Message type (ticker, candle, etc.)
    - seq: Sequence number (server → client messages only)
    - data: Payload (optional)
    - channel: Channel name (optional)
    - timestamp: Message timestamp
    """
    type: str
    seq: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    channel: Optional[str] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        result = {
            "type": self.type,
        }

        if self.seq is not None:
            result["seq"] = self.seq

        if self.channel is not None:
            result["channel"] = self.channel

        if self.data is not None:
            result["data"] = self.data

        if self.timestamp is not None:
            result["timestamp"] = self.timestamp.isoformat()

        if self.error is not None:
            result["error"] = self.error

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WSMessage":
        """Create from dict (client messages)"""
        return cls(
            type=data["type"],
            seq=data.get("seq"),
            data=data.get("data"),
            channel=data.get("channel"),
            error=data.get("error"),
        )


@dataclass
class WSSubscription:
    """
    Client subscription to a channel

    Channel format:
    - ticker:XAUUSD
    - candle:XAUUSD:1m
    - positions
    - balance
    - execution
    """
    channel: str
    client_id: str
    subscribed_at: datetime

    @property
    def channel_type(self) -> str:
        """Extract channel type (ticker, candle, etc.)"""
        return self.channel.split(":")[0]

    @property
    def symbol(self) -> Optional[str]:
        """Extract symbol from channel (if applicable)"""
        parts = self.channel.split(":")
        if len(parts) >= 2:
            return parts[1]
        return None

    @property
    def timeframe(self) -> Optional[str]:
        """Extract timeframe from candle channel"""
        parts = self.channel.split(":")
        if len(parts) >= 3 and parts[0] == "candle":
            return parts[2]
        return None


def create_ticker_message(seq: int, symbol: str, price: float, timestamp: datetime) -> WSMessage:
    """Create ticker update message"""
    return WSMessage(
        type=WSMessageType.TICKER,
        seq=seq,
        channel=f"ticker:{symbol}",
        data={
            "symbol": symbol,
            "price": price,
        },
        timestamp=timestamp,
    )


def create_candle_message(seq: int, symbol: str, timeframe: str, candle_data: Dict[str, Any], timestamp: datetime) -> WSMessage:
    """Create candle update message"""
    return WSMessage(
        type=WSMessageType.CANDLE,
        seq=seq,
        channel=f"candle:{symbol}:{timeframe}",
        data=candle_data,
        timestamp=timestamp,
    )


def create_position_message(seq: int, action: str, position_data: Dict[str, Any], timestamp: datetime) -> WSMessage:
    """Create position update message"""
    return WSMessage(
        type=WSMessageType.POSITION,
        seq=seq,
        channel="positions",
        data={
            "action": action,  # "opened", "closed", "updated"
            "position": position_data,
        },
        timestamp=timestamp,
    )


def create_balance_message(seq: int, balance_data: Dict[str, Any], timestamp: datetime) -> WSMessage:
    """Create balance update message"""
    return WSMessage(
        type=WSMessageType.BALANCE,
        seq=seq,
        channel="balance",
        data=balance_data,
        timestamp=timestamp,
    )


def create_execution_message(seq: int, execution_data: Dict[str, Any], timestamp: datetime) -> WSMessage:
    """Create execution confirmation message"""
    return WSMessage(
        type=WSMessageType.EXECUTION,
        seq=seq,
        channel="execution",
        data=execution_data,
        timestamp=timestamp,
    )


def create_subscribed_message(channel: str) -> WSMessage:
    """Create subscription confirmation"""
    return WSMessage(
        type=WSMessageType.SUBSCRIBED,
        channel=channel,
        data={"status": "subscribed"},
        timestamp=datetime.utcnow(),
    )


def create_unsubscribed_message(channel: str) -> WSMessage:
    """Create unsubscription confirmation"""
    return WSMessage(
        type=WSMessageType.UNSUBSCRIBED,
        channel=channel,
        data={"status": "unsubscribed"},
        timestamp=datetime.utcnow(),
    )


def create_error_message(error: str, channel: Optional[str] = None) -> WSMessage:
    """Create error message"""
    return WSMessage(
        type=WSMessageType.ERROR,
        channel=channel,
        error=error,
        timestamp=datetime.utcnow(),
    )


def create_resync_required_message(reason: str, last_available_seq: Optional[int] = None) -> WSMessage:
    """Create resync required message"""
    return WSMessage(
        type=WSMessageType.RESYNC_REQUIRED,
        data={
            "reason": reason,
            "last_available_seq": last_available_seq,
        },
        timestamp=datetime.utcnow(),
    )
