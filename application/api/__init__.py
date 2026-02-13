"""
API layer - FastAPI REST + WebSocket endpoints

Broker API (prefix /api/v1/broker):
- Core: /broker/health, /broker/mode
- Market data: /broker/venues, /broker/pairs, /broker/price/latest, /broker/candles, /broker/ohlcv/{symbol}
- Trading: /broker/balance, /broker/positions, /broker/orders/open, /broker/orders/close (JSON body)
- WebSocket: /ws (multi-channel)
"""
