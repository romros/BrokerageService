"""
Application main - FastAPI server initialization

Responsibilities:
- Load configuration from environment
- Initialize storage layer (CSVCandleStore)
- Initialize venue adapter (future)
- Setup FastAPI app with routes
- Graceful shutdown
"""


import asyncio
from contextlib import asynccontextmanager
import os
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from application.api.broker_routes import router as broker_router, set_broker_deps
from application.api.ws_routes import router as ws_router
from foundation.config.constants import (
    BROKER_DIAG_ENV,
    DATA_LAYER_ENABLED_ENV,
    DATA_LAYER_STARTUP_GATE_ENV,
    HEARTBEAT_INTERVAL_S,
    OSTIUM_ENABLED_ENV,
    TESTING_ENV,
    USE_FAKE_PRICE_FEED_ENV,
)
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

    # P7: Fallback provider (Dukascopy) per mixed stitching — opcional
    fallback_provider = None
    try:
        from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider  # lazy: evita carregar Dukascopy si no es fa servir P7
        fallback_provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
    except Exception as e:
        logger.debug("P7 fallback provider not available: %s", e)

    # Set broker API dependencies. Paper = zero tx; Lighter = tx reals.
    adapter = None
    market_data_service = None
    backfill_service = None
    use_fake_feed = os.getenv(USE_FAKE_PRICE_FEED_ENV, "").strip() == "1"
    enable_live = config["enable_live_trading"]
    mode_lower = (config["mode"] or "").lower()
    # PAPER: zero tx. Kill switch: ENABLE_LIVE_TRADING=0 → paper. No paper si venue=gtrade (backtest).
    use_paper_execution = (mode_lower == "paper" or not enable_live) and venue in ("", "lighter", "paper")

    from infrastructure.builders.lighter_di import build_lighter_paper_market_data  # lazy: evita carregar lighter si venue=gtrade
    from infrastructure.venues.lighter.config import (
        get_lighter_symbols_from_env,
        get_lighter_tick_interval_ms,
    )

    if use_paper_execution:
        # PAPER: execució simulada, zero tx. Market data de pipeline.
        symbols = get_lighter_symbols_from_env()
        _, market_data_service = build_lighter_paper_market_data(
            candle_store=candle_store,
            canonical_tz=config["canonical_tz"],
        )
        await market_data_service.start()
        source = "fake" if use_fake_feed else "real"
        logger.info(
            "execution_mode=paper_simulated market_data_env=%s source=%s",
            config["market_data_env"],
            source,
        )

        async def _get_price(sym: str):
            from domain.models import PriceData  # local import dins closure (evita circular)
            from datetime import datetime, timezone
            p = market_data_service.get_latest_price(sym)
            ts = datetime.now(timezone.utc)
            if p is None:
                return PriceData(symbol=sym, bid=0, ask=0, mid=0, timestamp=ts)
            return PriceData(symbol=sym, bid=p, ask=p, mid=p, timestamp=ts)

        from infrastructure.venues.paper.paper_venue_adapter import PaperVenueAdapter  # lazy: evita carregar paper si venue=gtrade
        paper_adapter = PaperVenueAdapter(get_price=_get_price, symbols=symbols)
        await paper_adapter.start()
        adapter = paper_adapter
        set_broker_deps(
            candle_store=candle_store,
            adapter_factory=lambda v: paper_adapter if v == "paper" else None,
            mode=config["mode"],
            venue="paper",
            market_data_env=config["market_data_env"],
            market_data_source=source,
            fallback_provider=fallback_provider,
        )
    elif venue == "lighter":
        # Lazy: evita carregar lighter si --venue gtrade
        from infrastructure.builders.lighter_di import (
            build_lighter_paper_adapter,
            build_lighter_paper_market_data,
        )
        from infrastructure.venues.lighter.config import (
            get_lighter_symbols_from_env,
            get_lighter_tick_interval_ms,
        )
        from infrastructure.venues.lighter.price_cache import PriceSnapshotCache
        from infrastructure.venues.lighter.config import get_price_cache_ttl_s

        source = "fake" if use_fake_feed else "real"
        shared_price_cache = PriceSnapshotCache(ttl_s=get_price_cache_ttl_s())
        if use_fake_feed:
            # P2.0.1: Sense adapter quan fake — broker arrenca sense xarxa
            adapter = None
            set_broker_deps(
                candle_store=candle_store,
                adapter_factory=lambda v: None,
                mode=config["mode"],
                venue=venue,
                market_data_env=config["market_data_env"],
                market_data_source=source,
                fallback_provider=fallback_provider,
            )
        else:
            adapter_mode = "live" if config["enable_live_trading"] else "paper"
            adapter = build_lighter_paper_adapter(
                mode=adapter_mode,
                price_cache=shared_price_cache,
            )
            await adapter.start()
            set_broker_deps(
                candle_store=candle_store,
                adapter_factory=lambda v: adapter if v == "lighter" else None,
                mode=config["mode"],
                venue=venue,
                market_data_env=config["market_data_env"],
                market_data_source=source,
                fallback_provider=fallback_provider,
            )

        # P2.0: Arrencar pipeline ticks→candles→store→WS quan MODE in (paper, live)
        mode_lower = (config["mode"] or "").lower()
        if mode_lower in ("paper", "live"):
            symbols = get_lighter_symbols_from_env()
            tick_interval_ms = get_lighter_tick_interval_ms()
            _, market_data_service = build_lighter_paper_market_data(
                candle_store=candle_store,
                canonical_tz=config["canonical_tz"],
                price_cache=shared_price_cache,
            )
            await market_data_service.start()
            logger.info(
                "MARKETDATA_START venue=%s source=%s symbols=%s interval_ms=%s",
                venue,
                source,
                symbols,
                tick_interval_ms,
            )
    else:
        set_broker_deps(
            candle_store=candle_store,
            adapter_factory=None,
            mode=config["mode"],
            venue=venue,
            market_data_env=config["market_data_env"],
            market_data_source="n/a",
            fallback_provider=fallback_provider,
        )

    logger.info("✓ BrokerageService ready")

    # P7c: DataLayerMetrics (telemetria) quan tenim pipeline o Data Layer prod
    data_layer_prod_service = None
    if market_data_service is not None or os.getenv(DATA_LAYER_ENABLED_ENV, "0") == "1":
        from application.data.data_layer_lifecycle import (
            DATA_LAYER_INITIALIZING,
            set_data_layer_status,
        )
        from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics  # lazy: només quan hi ha pipeline
        set_data_layer_metrics(DataLayerMetrics())
        set_data_layer_status(DATA_LAYER_INITIALIZING, reason="Data Layer startup")

    # Data Layer prod v0: prefetch + writer loop (DATA_LAYER_ENABLED=1)
    # Ostium mode: realtime_plus_backfill (ingest) | backfill_only (no ingest)
    ostium_enabled = os.getenv(OSTIUM_ENABLED_ENV, "0") == "1"
    cfg = {}
    if os.getenv(DATA_LAYER_ENABLED_ENV, "0") == "1":
        try:
            from application.services.data_layer_prod_service import DataLayerProdService, _get_config  # lazy
            cfg = _get_config()
            if ostium_enabled:
                cfg["write_mode"] = os.getenv("DATA_LAYER_WRITE_MODE", "realtime_plus_backfill").lower()
                if cfg["write_mode"] not in ("realtime_only", "realtime_plus_backfill", "backfill_only"):
                    cfg["write_mode"] = "realtime_plus_backfill"
                ostium_symbols = os.getenv("OSTIUM_SYMBOLS", os.getenv("SYMBOLS", "EURUSD,XAUUSD")).split(",")
                cfg["symbols"] = [s.strip() for s in ostium_symbols if s.strip()]
                from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider  # lazy
                provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
            else:
                from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import LighterCandlestickBackfillProvider  # lazy
                provider = LighterCandlestickBackfillProvider()
            if cfg["symbols"]:
                data_layer_prod_service = DataLayerProdService(
                    store=candle_store,
                    provider=provider,
                    symbols=cfg["symbols"],
                    prefetch_minutes=cfg["prefetch_minutes"],
                    max_gap_s=cfg["max_gap_s"],
                    max_missing_per_24h=cfg["max_missing_per_24h"],
                    stale_seconds=cfg["stale_seconds"],
                    write_mode=cfg.get("write_mode", "realtime"),
                )
                await data_layer_prod_service.start()
                logger.info("Data Layer prod v0 started symbols=%s prefetch_min=%s", cfg["symbols"], cfg["prefetch_minutes"])
                set_broker_deps(data_layer_write_mode=cfg.get("write_mode", "realtime"))
                # Startup gate: si activat i Data Layer DEGRADED → fallar startup
                if os.getenv(DATA_LAYER_STARTUP_GATE_ENV, "0") == "1":
                    ok, reason = data_layer_prod_service.run_startup_gate_check()
                    if not ok:
                        raise RuntimeError(f"DATA_LAYER_STARTUP_GATE failed: {reason}")
                    logger.info("Data Layer startup gate passed")
        except Exception as e:
            logger.warning("Data Layer prod v0 not started: %s", e)

    # Ostium realtime writer (OSTIUM_ENABLED=1 + write_mode permet ingest)
    ostium_ingest_service = None
    ostium_symbols = [s.strip() for s in os.getenv("OSTIUM_SYMBOLS", os.getenv("SYMBOLS", "EURUSD,XAUUSD")).split(",") if s.strip()]
    _write_mode = (cfg.get("write_mode", os.getenv("DATA_LAYER_WRITE_MODE", "realtime_plus_backfill")) if ostium_enabled else "realtime")
    _write_mode = str(_write_mode).lower()
    ostium_ingest_allowed = _write_mode in ("realtime_only", "realtime_plus_backfill")
    if ostium_enabled and ostium_symbols and ostium_ingest_allowed:
        try:
            from application.services.ostium_candle_ingest_service import OstiumCandleIngestService  # lazy
            from foundation.config.constants import (
                OSTIUM_POLL_S_ENV,
                DEFAULT_OSTIUM_POLL_S,
                DATA_LAYER_GATES_MAX_GAP_S_ENV,
                DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV,
                DATA_LAYER_STALE_SECONDS_ENV,
                DEFAULT_DATA_LAYER_GATES_MAX_GAP_S,
                DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H,
                DEFAULT_DATA_LAYER_STALE_SECONDS,
            )
            ostium_ingest_service = OstiumCandleIngestService(
                store=candle_store,
                symbols=ostium_symbols,
                poll_interval_s=int(os.getenv(OSTIUM_POLL_S_ENV, str(DEFAULT_OSTIUM_POLL_S))),
                max_gap_s=int(os.getenv(DATA_LAYER_GATES_MAX_GAP_S_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_GAP_S))),
                max_missing_per_24h=int(os.getenv(DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H))),
                stale_seconds=int(os.getenv(DATA_LAYER_STALE_SECONDS_ENV, str(DEFAULT_DATA_LAYER_STALE_SECONDS))),
            )
            await ostium_ingest_service.start()
            logger.info("OstiumCandleIngestService started symbols=%s", ostium_symbols)
            set_broker_deps(
                data_layer_write_mode=_write_mode,
                ostium_ingest_enabled=True,
                ostium_ingest_poll_s=int(os.getenv(OSTIUM_POLL_S_ENV, str(DEFAULT_OSTIUM_POLL_S))),
            )
        except Exception as e:
            logger.warning("OstiumCandleIngestService not started: %s", e)
    elif ostium_enabled and not ostium_ingest_allowed:
        set_broker_deps(data_layer_write_mode=_write_mode, ostium_ingest_enabled=False)

    # Test-only: simular ostium_ingest_enabled sense arrencar OstiumCandleIngestService (0-network)
    if ostium_enabled and os.getenv("OSTIUM_INGEST_ENABLED_OVERRIDE", "") == "1":
        set_broker_deps(ostium_ingest_enabled=True)

    # P4.0: BackfillService (gap repair) quan tenim Lighter market data
    if market_data_service is not None:
        try:
            from application.services.backfill_service import BackfillService  # lazy: només quan hi ha pipeline
            from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import (  # lazy: només quan hi ha pipeline
                LighterCandlestickBackfillProvider,
            )
            backfill_symbols = [
                s.strip() for s in os.getenv("BACKFILL_SYMBOLS", "EURUSD,XAUUSD").split(",")
                if s.strip()
            ]
            if backfill_symbols:
                backfill_provider = LighterCandlestickBackfillProvider()
                backfill_service = BackfillService(
                    store=candle_store,
                    provider=backfill_provider,
                    symbols=backfill_symbols,
                    corrective_window_minutes=int(os.getenv("CORRECTIVE_WINDOW_MINUTES", "60")),
                    interval_seconds=int(os.getenv("BACKFILL_INTERVAL_SECONDS", "600")),
                )
                await backfill_service.start()
                logger.info("P4.0 BackfillService started symbols=%s", backfill_symbols)
                # P8.0: Exposar primary provider per read-through (response-only)
                set_broker_deps(primary_backfill_provider=backfill_provider)
        except Exception as e:
            logger.warning("P4.0 BackfillService not started: %s", e)

    # P3.1: Heartbeat per diagnostics (TESTING=1 o BROKER_DIAG=1)
    heartbeat_task = None
    if os.getenv(TESTING_ENV, "").strip() == "1" or os.getenv(BROKER_DIAG_ENV, "").strip() == "1":
        async def _heartbeat_loop():
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                pending = len(asyncio.all_tasks())
                th = threading.current_thread().name
                logger.info("heartbeat alive thread=%s pending_tasks=%d", th, pending)

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info("P3.1 heartbeat enabled (interval=%ds)", HEARTBEAT_INTERVAL_S)

    yield  # App is running

    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    logger.info("🛑 Shutting down BrokerageService...")
    effective_venue = "paper" if use_paper_execution else venue
    if data_layer_prod_service:
        try:
            await data_layer_prod_service.stop()
            logger.info("Data Layer prod v0 stopped")
        except Exception as e:
            logger.error("DataLayerProdService stop error: %s", e)
    if ostium_ingest_service:
        try:
            await ostium_ingest_service.stop()
            logger.info("OstiumCandleIngestService stopped")
        except Exception as e:
            logger.error("OstiumCandleIngestService stop error: %s", e)
    if backfill_service:
        try:
            await backfill_service.stop()
            logger.info("P4.0 BackfillService stopped")
        except Exception as e:
            logger.error("BackfillService stop error: %s", e)
    if market_data_service:
        try:
            await market_data_service.stop()
            logger.info("MARKETDATA_STOP venue=%s", effective_venue)
        except Exception as e:
            logger.error("MARKETDATA_STOP error: %s", e)
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
