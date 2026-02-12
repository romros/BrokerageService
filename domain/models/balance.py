"""
Balance model
"""


from dataclasses import dataclass



@dataclass
class Balance:
    """Account balance"""
    usdc: float  # USDC balance
    native_token: float  # ETH balance (for gas)
    available_margin: float = 0.0  # Available for new positions
    used_margin: float = 0.0  # Locked in open positions

    @property
    def total_equity(self) -> float:
        """Total account equity"""
        return self.usdc

    @property
    def margin_usage_percent(self) -> float:
        """Percentage of margin used"""
        total = self.available_margin + self.used_margin
        if total == 0:
            return 0.0
        return (self.used_margin / total) * 100
