"""
gTrade venue configuration

Constants and mappings for gTrade integration.
No hardcoded values in business logic - all here.
"""

# WebSocket URL for gTrade price feed
DEFAULT_GTRADE_PRICE_WS_URL = "wss://backend-arbitrum.gains.trade"
# Pair ID mapping: gTrade pairId -> our canonical symbol
# Source: https://docs.gains.trade/
#
# NOTE: Mainnet vs Testnet have DIFFERENT pair IDs!
# - Mainnet (chain_id=42161): 0=XAUUSD, 2=EURUSD
# - Sepolia Testnet (chain_id=421614): 0=BTCUSD, 1=ETHUSD (NO forex pairs!)
#
# For now, using Sepolia testnet mapping:
GTRADE_PAIR_ID_TO_SYMBOL = {
    0: "BTCUSD",  # Bitcoin / USD (Sepolia testnet)
    1: "ETHUSD",  # Ethereum / USD (Sepolia testnet)
    2: "LINKUSD",  # Chainlink / USD (Sepolia testnet)
}
# Reverse mapping for lookups
GTRADE_SYMBOL_TO_PAIR_ID = {
    symbol: pair_id for pair_id, symbol in GTRADE_PAIR_ID_TO_SYMBOL.items()
}
# Supported symbols (MVP)
GTRADE_SUPPORTED_SYMBOLS = ["BTCUSD", "ETHUSD", "LINKUSD"]
# Reconnection settings
DEFAULT_RECONNECT_DELAY_SECONDS = 5.0
DEFAULT_MAX_RECONNECT_ATTEMPTS = 10
# Ticker broadcast throttle (milliseconds)
DEFAULT_TICKER_BROADCAST_MS = 200