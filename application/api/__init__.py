"""
API layer - FastAPI REST + WebSocket endpoints

Endpoints:
- Core: /health, /mode, /capabilities
- Instruments: /pairs
- Market data: /ticker/{symbol}, /ohlcv/{symbol}
- Trading: /positions (CRUD + SL/TP updates)
- Account: /balance, /trade-history
- Backtest: /backtest/* (controls)
- WebSocket: /ws (multi-channel)
"""
