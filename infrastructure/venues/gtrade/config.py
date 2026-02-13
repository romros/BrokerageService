"""
gTrade venue configuration

Constants and mappings for gTrade integration.
No hardcoded values in business logic - all here.
"""

import os

# WebSocket URL for gTrade price feed
DEFAULT_GTRADE_PRICE_WS_URL_MAINNET = "wss://backend-arbitrum.gains.trade"
DEFAULT_GTRADE_PRICE_WS_URL_TESTNET = "wss://backend-sepolia.gains.trade"
# REST backend URL (open-trades, trading-variables)
DEFAULT_GTRADE_BACKEND_URL_MAINNET = "https://backend-arbitrum.gains.trade"
DEFAULT_GTRADE_BACKEND_URL_TESTNET = "https://backend-sepolia.gains.trade"

# Legacy defaults (mainnet) for backward compatibility
DEFAULT_GTRADE_PRICE_WS_URL = DEFAULT_GTRADE_PRICE_WS_URL_MAINNET
DEFAULT_GTRADE_BACKEND_URL = DEFAULT_GTRADE_BACKEND_URL_MAINNET
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


def get_gtrade_backend_url() -> str:
    """
    Backend REST URL from env.
    - GTRADE_BACKEND_REST_URL: if set, use it
    - Else: MARKET_DATA_ENV=mainnet → mainnet, testnet → testnet
    """
    url = os.getenv("GTRADE_BACKEND_REST_URL")
    if url:
        return url
    env = os.getenv("MARKET_DATA_ENV", "mainnet").lower()
    if env == "testnet":
        return DEFAULT_GTRADE_BACKEND_URL_TESTNET
    return DEFAULT_GTRADE_BACKEND_URL_MAINNET


def get_gtrade_price_ws_url() -> str:
    """
    Price feed WS URL from env.
    - GTRADE_PRICE_WS_URL: if set, use it
    - Else: MARKET_DATA_ENV=mainnet → mainnet, testnet → testnet
    """
    url = os.getenv("GTRADE_PRICE_WS_URL")
    if url:
        return url
    env = os.getenv("MARKET_DATA_ENV", "mainnet").lower()
    if env == "testnet":
        return DEFAULT_GTRADE_PRICE_WS_URL_TESTNET
    return DEFAULT_GTRADE_PRICE_WS_URL_MAINNET