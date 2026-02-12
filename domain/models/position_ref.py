"""
Position Reference - Canonical identifier for gTrade positions

A PositionRef uniquely identifies a position across the system:
- wallet_address: The trader's wallet
- pair_id: The trading pair (0=XAUUSD, 2=EURUSD)
- trade_index: The position index (unique per trader)

Immutable (frozen dataclass) to ensure referential integrity.
Used for:
- Position reconciliation
- Close operations
- Position tracking across backend/blockchain
"""


from dataclasses import dataclass



@dataclass(frozen=True)
class PositionRef:
    """
    Canonical position reference for gTrade

    Immutable identifier combining wallet + pair + index.
    """
    wallet_address: str
    pair_id: int
    trade_index: int

    def __str__(self) -> str:
        """String representation: wallet:pair_id:trade_index"""
        return f"{self.wallet_address}:{self.pair_id}:{self.trade_index}"

    def __repr__(self) -> str:
        """Debug representation"""
        return f"PositionRef({self.wallet_address[:6]}...:{self.pair_id}:{self.trade_index})"
