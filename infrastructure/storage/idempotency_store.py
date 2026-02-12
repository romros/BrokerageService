"""
IdempotencyStore - In-memory store for idempotent request handling

Tracks client_order_id to prevent duplicate order execution.

Usage:
    store = IdempotencyStore(ttl_seconds=3600)

    # Check if already processed
    result = store.get("client_order_123")
    if result:
        return result  # Return cached result

    # Process order
    result = await execute_order(...)

    # Store result
    store.set("client_order_123", result)
"""


from threading import Lock
from typing import Optional, Dict, Any
import time

from foundation.logging import get_logger


logger = get_logger(__name__)


class IdempotencyStore:
    """
    In-memory idempotency store with TTL

    Features:
    - Thread-safe operations
    - TTL-based expiration
    - Automatic cleanup of expired entries
    """

    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize idempotency store

        Args:
            ttl_seconds: Time-to-live for entries (default: 1 hour)
        """
        self._store: Dict[str, tuple[Any, float]] = {}  # key -> (value, expire_time)
        self._lock = Lock()
        self._ttl_seconds = ttl_seconds

        logger.info(f"IdempotencyStore initialized (TTL={ttl_seconds}s)")

    def get(self, key: str) -> Optional[Any]:
        """
        Get value by key

        Args:
            key: Client order ID

        Returns:
            Stored value or None if not found/expired
        """
        with self._lock:
            self._cleanup_expired()

            if key not in self._store:
                return None

            value, expire_time = self._store[key]

            # Check if expired
            if time.time() > expire_time:
                del self._store[key]
                return None

            logger.debug(f"Idempotency hit: {key}")
            return value

    def set(self, key: str, value: Any) -> None:
        """
        Store value with key

        Args:
            key: Client order ID
            value: OrderResult or any serializable value
        """
        with self._lock:
            expire_time = time.time() + self._ttl_seconds
            self._store[key] = (value, expire_time)
            logger.debug(f"Idempotency stored: {key}")

    def delete(self, key: str) -> None:
        """Delete entry by key"""
        with self._lock:
            if key in self._store:
                del self._store[key]
                logger.debug(f"Idempotency deleted: {key}")

    def clear(self) -> None:
        """Clear all entries"""
        with self._lock:
            self._store.clear()
            logger.info("IdempotencyStore cleared")

    def _cleanup_expired(self) -> None:
        """Remove expired entries (called automatically during get)"""
        now = time.time()
        expired_keys = [k for k, (_, expire_time) in self._store.items() if now > expire_time]

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired idempotency entries")

    @property
    def size(self) -> int:
        """Get number of stored entries"""
        with self._lock:
            return len(self._store)
