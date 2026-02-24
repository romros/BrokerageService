"""
Lighter L3 ZK-rollup venue adapter

Lighter is a perpetual DEX on L3 with:
- 0% protocol fees
- ~$0.16/RT cost (gas only)
- HTTP SDK (not EVM RPC)
- Two-key authentication (L1 wallet + API trading key)

References:
- Testnet: https://testnet.zklighter.elliot.ai
- UI: https://testnet.app.lighter.xyz
- Lab validation: lab/lighter/LIGHTER_COMPLETE_VALIDATION.md
"""

from .config import LighterConfig, load_lighter_config_from_env
from .lighter_adapter import LighterVenueAdapter

__all__ = [
    "LighterConfig",
    "load_lighter_config_from_env",
    "LighterVenueAdapter",
]
