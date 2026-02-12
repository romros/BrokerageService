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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from application.api.routes import router, set_dependencies
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
    config = {
        "mode": os.getenv("MODE", "backtest"),
        "venue": os.getenv("VENUE", "gtrade"),
        "datafiles_root": os.getenv("DATAFILES_ROOT", "/datafiles"),
        "canonical_tz": os.getenv("CANONICAL_TZ", "America/New_York"),
        "symbols": os.getenv("SYMBOLS", "XAUUSD,EURUSD").split(","),
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", "8000")),
    }

    logger.info(f"Configuration loaded: mode={config['mode']}, venue={config['venue']}")
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
    candle_store = CSVCandleStore(
        root_path=config["datafiles_root"],
        broker=config["venue"],
        canonical_tz=config["canonical_tz"],
    )

    # Set API dependencies
    set_dependencies(
        candle_store=candle_store,
        mode=config["mode"],
        venue=config["venue"],
    )

    logger.info("✓ BrokerageService ready")

    yield  # App is running

    logger.info("🛑 Shutting down BrokerageService...")
    # Future: cleanup venue adapter, close connections, etc.


# ============ APP INITIALIZATION ============

def create_app() -> FastAPI:
    """
    Create and configure FastAPI application

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="BrokerageService",
        description="Trading brokerage service with REST + WebSocket API (gTrade adapter ready)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: configure properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(router, prefix="/api/v1")
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
    import uvicorn

    config = load_config()

    uvicorn.run(
        "application.main:app",
        host=config["host"],
        port=config["port"],
        reload=True,  # Auto-reload for development
        log_level="info",
    )
