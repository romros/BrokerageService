"""
Lighter Client Order Index Generator

Lighter uses uint32 (0-4294967295) for client_order_index instead of UUID strings.
This is used for idempotency (preventing duplicate orders on retry).

Critical rules:
- MUST be unique per order
- MUST be uint32 range (0 to 2^32-1)
- Recommended: timestamp-based with collision prevention

TASK 2 - Invariant 4: Client order index + idempotency mapping
"""

import time
from typing import Set


class ClientOrderIndexGenerator:
    """
    Generator for unique uint32 client_order_index values

    Uses timestamp-based generation with collision tracking.
    Thread-safe for single-threaded usage (for multi-threaded,
    add Lock around _used_indices).
    """

    def __init__(self, seed: int = None):
        """
        Initialize generator

        Args:
            seed: Optional seed for deterministic testing.
                  If None, uses current timestamp.
        """
        self._seed = seed
        self._counter = 0
        self._used_indices: Set[int] = set()

    def next(self) -> int:
        """
        Generate next unique uint32 client_order_index

        Returns:
            Unique uint32 value (0 to 4294967295)

        Note:
            In production, this should track used indices to prevent
            collisions on retry. For simplicity, we use monotonic counter.
        """
        if self._seed is not None:
            # Deterministic mode (testing)
            index = (self._seed + self._counter) % (2**32)
            self._counter += 1
        else:
            # Production mode (timestamp-based)
            index = int(time.time() * 1000) % (2**32)

            # Collision prevention: increment if already used
            while index in self._used_indices:
                index = (index + 1) % (2**32)

        self._used_indices.add(index)
        return index

    def reset(self):
        """Reset generator (for testing)"""
        self._counter = 0
        self._used_indices.clear()


def map_to_idempotency_store_key(client_order_index: int) -> str:
    """
    Map uint32 client_order_index to IdempotencyStore key

    IdempotencyStore expects string keys, so we convert uint32 to string.

    Args:
        client_order_index: uint32 value (0 to 4294967295)

    Returns:
        String representation for IdempotencyStore

    Example:
        >>> map_to_idempotency_store_key(12345)
        '12345'
    """
    if not isinstance(client_order_index, int):
        raise TypeError(f"client_order_index must be int, got {type(client_order_index)}")

    if client_order_index < 0 or client_order_index >= 2**32:
        raise ValueError(f"client_order_index must be uint32 (0 to 4294967295), got {client_order_index}")

    return str(client_order_index)
