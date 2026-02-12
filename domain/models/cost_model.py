"""
Cost Model for gTrade Official Fees

Implements official gTrade fee structure using basis points (bps).
100 bps = 1%

Fee calculation:
- Base: position_size = collateral × leverage
- Fee: fee_amount = position_size × fee_bps / BASIS_POINTS_DIVISOR

Official fees from: https://docs.gains.trade/developer/integrators/guides/calculating-borrowing-fees
"""


from dataclasses import dataclass
from typing import Dict

from foundation.config.constants import BASIS_POINTS_DIVISOR, BORROWING_FEE_PLACEHOLDER, DYNAMIC_SPREAD_PLACEHOLDER


@dataclass
class CostModel:
    """
    Cost model for a trading symbol

    All costs stored in basis points (bps):
    - 1 bps = 0.01%
    - 10 bps = 0.1%
    - 100 bps = 1%

    Fee calculation base: position_size = collateral_usdc × leverage
    Fee formula: fee = position_size × fee_bps / 10_000
    """
    symbol: str
    spread_bps: float          # Fixed spread cost
    open_fee_bps: float        # Opening fee
    close_fee_bps: float       # Closing fee

    # Placeholders (MVP - Fase 4.5)
    # Will be implemented in Fase 6 with real OI data
    price_impact_bps: float = 0.0    # Dynamic spread / OI-based cost
    borrowing_fee_bps: float = 0.0   # Per-block borrowing (not applicable for single-block calc)

    def calculate_open_fees(self, position_size: float) -> Dict[str, float]:
        """
        Calculate fees for opening a position

        Args:
            position_size: Notional position size (collateral × leverage)

        Returns:
            Fees breakdown dict with:
            - spread_cost: Fixed spread cost
            - open_fee: Opening fee
            - price_impact_cost: Dynamic spread (placeholder = 0.0)
            - total_entry_cost: Sum of all entry costs
        """
        spread_cost = position_size * self.spread_bps / BASIS_POINTS_DIVISOR
        open_fee = position_size * self.open_fee_bps / BASIS_POINTS_DIVISOR
        price_impact_cost = position_size * self.price_impact_bps / 10_000

        return {
            "spread_cost": spread_cost,
            "open_fee": open_fee,
            "price_impact_cost": price_impact_cost,
            "total_entry_cost": spread_cost + open_fee + price_impact_cost,
        }

    def calculate_close_fees(self, position_size: float) -> Dict[str, float]:
        """
        Calculate fees for closing a position

        Args:
            position_size: Notional position size (collateral × leverage)

        Returns:
            Fees breakdown dict with:
            - close_fee: Closing fee
            - borrowing_cost: Accumulated borrowing fee (placeholder = 0.0)
            - total_exit_cost: Sum of all exit costs
        """
        close_fee = position_size * self.close_fee_bps / BASIS_POINTS_DIVISOR
        borrowing_cost = BORROWING_FEE_PLACEHOLDER  # Needs OI data (Fase 6) + block tracking

        return {
            "close_fee": close_fee,
            "borrowing_cost": borrowing_cost,
            "total_exit_cost": close_fee + borrowing_cost,
        }

    def calculate_total_fees(self, position_size: float) -> Dict[str, float]:
        """
        Calculate total fees for complete trade (open + close)

        Args:
            position_size: Notional position size (collateral × leverage)

        Returns:
            Complete fees breakdown with all components
        """
        open_fees = self.calculate_open_fees(position_size)
        close_fees = self.calculate_close_fees(position_size)

        return {
            "spread_cost": open_fees["spread_cost"],
            "open_fee": open_fees["open_fee"],
            "close_fee": close_fees["close_fee"],
            "price_impact_cost": open_fees["price_impact_cost"],
            "borrowing_cost": close_fees["borrowing_cost"],
            "total_fees": open_fees["total_entry_cost"] + close_fees["total_exit_cost"],
        }

    @classmethod
    def for_gtrade_symbol(cls, symbol: str) -> "CostModel":
        """
        Factory method for official gTrade fees

        Official fees from gTrade docs:
        https://docs.gains.trade/developer/integrators/guides/calculating-borrowing-fees

        Args:
            symbol: Trading symbol (e.g., "XAUUSD", "EURUSD")

        Returns:
            CostModel instance with official fees

        Raises:
            ValueError: If symbol not supported
        """
        symbol = symbol.upper()

        if symbol == "EURUSD":
            return cls(
                symbol=symbol,
                spread_bps=1.0,      # 0.01%
                open_fee_bps=1.2,    # 0.012%
                close_fee_bps=1.2,   # 0.012%
            )
        elif symbol == "XAUUSD":
            return cls(
                symbol=symbol,
                spread_bps=1.0,      # 0.01%
                open_fee_bps=5.0,    # 0.05%
                close_fee_bps=5.0,   # 0.05%
            )
        else:
            raise ValueError(f"Unsupported symbol for gTrade cost model: {symbol}")


# Example usage / verification
if __name__ == "__main__":
    # EURUSD example
    eurusd_model = CostModel.for_gtrade_symbol("EURUSD")
    position_size = 10_000  # $10k notional (e.g., $1000 × 10x leverage)

    fees = eurusd_model.calculate_total_fees(position_size)
    print(f"EURUSD ($10k notional) total fees: ${fees['total_fees']:.2f}")
    # Expected: spread 1.0 + open 1.2 + close 1.2 = 3.4 bps = $3.40

    # XAUUSD example
    xauusd_model = CostModel.for_gtrade_symbol("XAUUSD")
    fees = xauusd_model.calculate_total_fees(position_size)
    print(f"XAUUSD ($10k notional) total fees: ${fees['total_fees']:.2f}")
    # Expected: spread 1.0 + open 5.0 + close 5.0 = 11.0 bps = $11.00
