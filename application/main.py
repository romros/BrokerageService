"""
Application main - FastAPI server initialization

Responsibilities:
- Load configuration from environment
- Initialize storage layer (CSVCandleStore)
- Initialize venue adapter (future)
- Setup FastAPI app with routes
- Graceful shutdown
"""


from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from application.api.broker_routes import router as broker_router, set_broker_deps
from application.api.ws_routes import router as ws_router
from foundation.logging import get_logger
from infrastructure.storage.csv_store import CSVCandleStore


logger = get_logger(__name__)


# ============ CONFIGURATION ============

def load_config() -> dict:
    """
    Load configuration from environment variables

    Returns:
        Configuration dictionary
    """
    market_data_env = os.getenv("MARKET_DATA_ENV", "mainnet").lower()
    if market_data_env not in ("mainnet", "testnet"):
        market_data_env = "mainnet"

    config = {
        "mode": os.getenv("MODE", "paper"),
        "venue": os.getenv("VENUE", ""),
        "datafiles_root": os.getenv("DATAFILES_ROOT", "/datafiles"),
        "canonical_tz": os.getenv("CANONICAL_TZ", "America/New_York"),
        "symbols": os.getenv("SYMBOLS", "XAUUSD,EURUSD").split(","),
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", "8000")),
        "market_data_env": market_data_env,
        "enable_live_trading": os.getenv("ENABLE_LIVE_TRADING", "0") == "1",
    }

    logger.info(
        f"Configuration loaded: mode={config['mode']}, venue={config['venue']}, "
        f"market_data_env={config['market_data_env']}"
    )
    return config


# ============ LIFESPAN (STARTUP/SHUTDOWN) ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager

    Startup:
    - Load config
    - Initialize storage
    - Initialize venue adapter (future)
    - Setup dependencies

    Shutdown:
    - Cleanup resources
    """
    logger.info("🚀 Starting BrokerageService...")

    # Load config
    config = load_config()

    # Initialize storage
    venue = config["venue"] or ""
    candle_store = CSVCandleStore(
        root_path=config["datafiles_root"],
        broker=venue or "gtrade",
        canonical_tz=config["canonical_tz"],
    )

    # Set broker API dependencies. Només VENUE=lighter té adapter.
    adapter = None
    if venue == "lighter":
        # Lazy: evita carregar lighter si --venue gtrade
        from infrastructure.builders.lighter_di import build_lighter_paper_adapter
        adapter = build_lighter_paper_adapter()
        await adapter.start()
        set_broker_deps(
            candle_store=candle_store,
            adapter_factory=lambda v: adapter if v == "lighter" else None,
            mode=config["mode"],
            venue=venue,
            market_data_env=config["market_data_env"],
        )
    else:
        set_broker_deps(
            candle_store=candle_store,
            adapter_factory=None,
            mode=config["mode"],
            venue=venue,
            market_data_env=config["market_data_env"],
        )

    logger.info("✓ BrokerageService ready")

    yield  # App is running

    logger.info("🛑 Shutting down BrokerageService...")
    if adapter:
        await adapter.stop()


# ============ APP INITIALIZATION ============

def create_app() -> FastAPI:
    """
    Create and configure FastAPI application

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="BrokerageService",
        description="Trading brokerage service with REST + WebSocket API (Lighter)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Exception handler: HTTPException amb detail dict {detail, code} → retorna directament
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: configure properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes (broker_router ja té prefix /api/v1/broker)
    app.include_router(broker_router)
    app.include_router(ws_router, prefix="/api/v1")

    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "service": "BrokerageService",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


# Create app instance
app = create_app()


# ============ DEV SERVER ============

if __name__ == "__main__":
    # Lazy: uvicorn només per dev server (no es carrega a runtime normal)
    import uvicorn

    config = load_config()

    uvicorn.run(
        "application.main:app",
        host=config["host"],
        port=config["port"],
        reload=True,  # Auto-reload for development
        log_level="info",
    )
