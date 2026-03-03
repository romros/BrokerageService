"""
App factory — create_app(role) per Split vNext.

SERVICE_ROLE: realtime_datalayer | historical_datalayer | trading_service | None (monolithic).
Cada rol wireja només els components que li toquen.
"""

import asyncio
from contextlib import asynccontextmanager
import os
import subprocess
import threading
import time
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from application.api.broker_routes import get_routers_for_role, set_broker_deps
from application.api.ws_routes import router as ws_router
from foundation.config.constants import (
    BROKER_DIAG_ENV,
    DATA_LAYER_ENABLED_ENV,
    DATA_LAYER_STARTUP_GATE_ENV,
    DEFAULT_RAW_SYNC_INTERVAL_MIN,
    DEFAULT_RAW_SYNC_TAIL_DAYS,
    ENABLE_LEGACY_VENUES_ENV,
    HEARTBEAT_INTERVAL_S,
    LEGACY_VENUES,
    OSTIUM_ENABLED_ENV,
    RAW_SYNC_ENABLED_ENV,
    RAW_SYNC_INTERVAL_MIN_ENV,
    RAW_SYNC_TAIL_DAYS_ENV,
    REALTIME_DATALAYER_BASE_URL_ENV,
    REALTIME_DATALAYER_ROOT_ENV,
    TESTING_ENV,
    USE_FAKE_PRICE_FEED_ENV,
)
from foundation.config.service_role import get_service_role
from foundation.logging import get_logger
from infrastructure.storage.csv_store import CSVCandleStore

logger = get_logger(__name__)


def _load_config() -> dict:
    """Load configuration from environment."""
    market_data_env = os.getenv("MARKET_DATA_ENV", "mainnet").lower()
    if market_data_env not in ("mainnet", "testnet"):
        market_data_env = "mainnet"
    return {
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


def _role_starts_adapter(role: str | None) -> bool:
    """Trading service (o monolithic) arrenca adapter."""
    return role in (None, "trading_service")


def _role_starts_ingest_or_writer(role: str | None) -> bool:
    """Realtime (Ostium ingest) o historical (Data Layer backfill) arrenquen writer."""
    return role in ("realtime_datalayer", "historical_datalayer", None)


def _role_starts_ostium_ingest(role: str | None) -> bool:
    """Només realtime_datalayer (o monolithic) arrenca Ostium ingest."""
    return role in ("realtime_datalayer", None)


def _role_starts_market_data_pipeline(role: str | None) -> bool:
    """Trading (paper/Lighter) o monolithic: market data pipeline."""
    return role in (None, "trading_service")


def _role_starts_backfill_service(role: str | None) -> bool:
    """BackfillService (Lighter) només per monolithic/trading amb pipeline."""
    return role in (None, "trading_service")


def create_app(role: str | None = None) -> FastAPI:
    """
    Crea FastAPI app amb wiring role-aware.

    role: realtime_datalayer | historical_datalayer | trading_service | None (monolithic).
    Si None, llegeix SERVICE_ROLE des de env.
    """
    if role is None:
        role = get_service_role()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("🚀 Starting BrokerageService (role=%s)...", role or "monolithic")

        config = _load_config()
        venue = config["venue"] or ""
        # Realtime DataLayer v1: storage dedicat datafiles/realtime_datalayer/candles
        if role == "realtime_datalayer":
            realtime_root = os.getenv(REALTIME_DATALAYER_ROOT_ENV, "").strip()
            if not realtime_root:
                realtime_root = os.path.join(config["datafiles_root"], "realtime_datalayer")
            candle_store = CSVCandleStore(
                root_path=realtime_root,
                broker="candles",
                canonical_tz=config["canonical_tz"],
            )
        else:
            candle_store = CSVCandleStore(
                root_path=config["datafiles_root"],
                broker=venue or "gtrade",
                canonical_tz=config["canonical_tz"],
            )

        fallback_provider = None
        try:
            from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
            fallback_provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
        except Exception as e:
            logger.debug("P7 fallback provider not available: %s", e)

        adapter = None
        market_data_service = None
        backfill_service = None
        data_layer_prod_service = None
        ostium_ingest_service = None

        use_fake_feed = os.getenv(USE_FAKE_PRICE_FEED_ENV, "").strip() == "1"
        enable_live = config["enable_live_trading"]
        mode_lower = (config["mode"] or "").lower()
        enable_legacy_venues = os.getenv(ENABLE_LEGACY_VENUES_ENV, "0").strip() == "1"

        # Phase F: paper-first — sense VENUE explícit o VENUE=paper → paper adapter
        # Legacy venues (lighter, gtrade) requereixen ENABLE_LEGACY_VENUES=1
        use_paper_execution = venue in ("", "paper")
        use_ostium_execution = venue == "ostium"
        use_lighter_execution = venue == "lighter" and enable_legacy_venues
        # gtrade no té execution adapter: cau al bloc else → adapter_factory=None

        # --- Adapter + market data (només trading / monolithic) ---
        if _role_starts_adapter(role):
            from application.services.paper_market_data_builder import build_paper_market_data_provider
            from infrastructure.paper_market_data import get_symbols_from_env

            if use_paper_execution:
                symbols = get_symbols_from_env()
                _, market_data_service = build_paper_market_data_provider(
                    candle_store=candle_store,
                    canonical_tz=config["canonical_tz"],
                )
                await market_data_service.start()
                source = "fake"
                logger.info("execution_mode=paper_simulated market_data_env=%s source=%s", config["market_data_env"], source)

                async def _get_price(sym: str):
                    from domain.models import PriceData
                    from datetime import datetime, timezone
                    p = market_data_service.get_latest_price(sym)
                    ts = datetime.now(timezone.utc)
                    if p is None:
                        return PriceData(symbol=sym, bid=0, ask=0, mid=0, timestamp=ts)
                    return PriceData(symbol=sym, bid=p, ask=p, mid=p, timestamp=ts)

                from infrastructure.venues.paper.paper_venue_adapter import PaperVenueAdapter
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
            elif use_ostium_execution:
                # Phase F: OstiumExecutionAdapter — LIVE exec via chain; start() obligatori
                from infrastructure.venues.ostium.ostium_execution_adapter import OstiumExecutionAdapter
                ostium_adapter = OstiumExecutionAdapter()
                try:
                    await ostium_adapter.start()
                except Exception as e:
                    logger.warning("OstiumExecutionAdapter.start FAILED: %s — ostium no disponible", e)
                    ostium_adapter = None
                if ostium_adapter is not None and ostium_adapter._client is not None:
                    adapter = ostium_adapter
                    logger.info("execution_mode=ostium (LIVE)")
                    set_broker_deps(
                        candle_store=candle_store,
                        adapter_factory=lambda v: ostium_adapter if v == "ostium" else None,
                        mode=config["mode"],
                        venue="ostium",
                        market_data_env=config["market_data_env"],
                        market_data_source="n/a",
                        fallback_provider=fallback_provider,
                    )
                else:
                    logger.warning("OstiumExecutionAdapter: client no inicialitzat (PK o RPC mancant) — ostium no disponible")
                    set_broker_deps(
                        candle_store=candle_store,
                        adapter_factory=lambda v: None,
                        mode=config["mode"],
                        venue=venue,
                        market_data_env=config["market_data_env"],
                        market_data_source="n/a",
                        fallback_provider=fallback_provider,
                    )
            elif use_lighter_execution:
                # Legacy arxivat (T5.35): lighter no disponible al tree principal
                logger.warning("venue=lighter arxivat (T5.35). Usa venue=ostium o venue=paper.")
                set_broker_deps(
                    candle_store=candle_store,
                    adapter_factory=None,
                    mode=config["mode"],
                    venue=venue,
                    market_data_env=config["market_data_env"],
                    market_data_source="n/a",
                    fallback_provider=fallback_provider,
                )
            else:
                # Venue no configurat o legacy sense opt-in → adapter_factory=None
                # TradingCore llançarà AdapterNotAvailableError o VenueNotConfiguredError
                if venue in LEGACY_VENUES and not enable_legacy_venues:
                    logger.warning(
                        "venue=%s és legacy: requereix ENABLE_LEGACY_VENUES=1 (Phase F). "
                        "Adapter no disponible.", venue
                    )
                set_broker_deps(
                    candle_store=candle_store,
                    adapter_factory=None,
                    mode=config["mode"],
                    venue=venue,
                    market_data_env=config["market_data_env"],
                    market_data_source="n/a",
                    fallback_provider=fallback_provider,
                )
        else:
            # realtime / historical: sense adapter
            set_broker_deps(
                candle_store=candle_store,
                adapter_factory=None,
                mode=config["mode"],
                venue=venue or "gtrade",
                market_data_env=config["market_data_env"],
                market_data_source="n/a",
                fallback_provider=fallback_provider,
            )

        # Split vNext Phase 2: trading_service consumeix realtime_datalayer via HTTP
        if role == "trading_service" and os.getenv(REALTIME_DATALAYER_BASE_URL_ENV, "").strip():
            from packages.shared.realtime_datalayer_client import get_realtime_datalayer_client_from_env
            from application.data.data_layer_reader import HttpDataLayerReader
            client = get_realtime_datalayer_client_from_env()
            if client is not None:
                set_broker_deps(data_layer_reader=HttpDataLayerReader(client))
                logger.info("Data Layer reader: HTTP (realtime_datalayer)")

        logger.info("✓ BrokerageService ready (role=%s)", role or "monolithic")

        # --- Data Layer prod + Ostium ingest (realtime, historical, monolithic) ---
        # Realtime/historical: sempre init metrics perquè data_status retorni 200 (mai 503 en initializing)
        if _role_starts_ingest_or_writer(role):
            from application.data.data_layer_lifecycle import DATA_LAYER_INITIALIZING, set_data_layer_status
            from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics
            set_data_layer_metrics(DataLayerMetrics())
            set_data_layer_status(DATA_LAYER_INITIALIZING, reason="Data Layer startup")

        if _role_starts_ingest_or_writer(role) and os.getenv(DATA_LAYER_ENABLED_ENV, "0") == "1":

            ostium_enabled = os.getenv(OSTIUM_ENABLED_ENV, "0") == "1"
            cfg = {}
            try:
                from application.services.data_layer_prod_service import DataLayerProdService, _get_config
                cfg = _get_config()
                # historical: backfill_only + Dukascopy
                # realtime_datalayer: Ostium només (independent de Dukascopy, AGENTS_ARQUITECTURA)
                if role == "historical_datalayer":
                    cfg["write_mode"] = "backfill_only"
                    from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
                    provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
                    cfg["symbols"] = cfg.get("symbols") or [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD").split(",") if s.strip()]
                elif role == "realtime_datalayer":
                    cfg["write_mode"] = os.getenv("DATA_LAYER_WRITE_MODE", "realtime_only").lower()
                    if cfg["write_mode"] not in ("realtime_only", "realtime_plus_backfill", "backfill_only"):
                        cfg["write_mode"] = "realtime_only"
                    from apps.realtime_datalayer.symbol_config import get_desired_symbols
                    cfg["symbols"] = get_desired_symbols()
                    from infrastructure.data.null_backfill_provider import NullBackfillProvider
                    provider = NullBackfillProvider()
                elif ostium_enabled:
                    cfg["write_mode"] = os.getenv("DATA_LAYER_WRITE_MODE", "realtime_plus_backfill").lower()
                    if cfg["write_mode"] not in ("realtime_only", "realtime_plus_backfill", "backfill_only"):
                        cfg["write_mode"] = "realtime_plus_backfill"
                    from application.data.ostium_symbol_policy import get_ostium_ingest_symbols
                    cfg["symbols"] = list(get_ostium_ingest_symbols())
                    from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
                    provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
                else:
                    from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
                    provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
                if cfg["symbols"]:
                    data_layer_prod_service = DataLayerProdService(
                        store=candle_store,
                        provider=provider,
                        symbols=cfg["symbols"],
                        prefetch_minutes=cfg["prefetch_minutes"],
                        warmup_minutes=cfg.get("warmup_minutes", 120),
                        max_gap_s=cfg["max_gap_s"],
                        max_missing_per_24h=cfg["max_missing_per_24h"],
                        stale_seconds=cfg["stale_seconds"],
                        write_mode=cfg.get("write_mode", "realtime"),
                    )
                    await data_layer_prod_service.start()
                    logger.info("Data Layer prod v0 started symbols=%s", cfg["symbols"])
                    set_broker_deps(data_layer_write_mode=cfg.get("write_mode", "realtime"))
                    if os.getenv(DATA_LAYER_STARTUP_GATE_ENV, "0") == "1":
                        ok, reason = data_layer_prod_service.run_startup_gate_check()
                        if not ok:
                            raise RuntimeError(f"DATA_LAYER_STARTUP_GATE failed: {reason}")
            except Exception as e:
                logger.warning("Data Layer prod v0 not started: %s", e)

            # Ostium ingest: només realtime (o monolithic)
            if _role_starts_ostium_ingest(role) and ostium_enabled:
                if role == "realtime_datalayer":
                    from apps.realtime_datalayer.symbol_config import get_desired_symbols
                    from apps.realtime_datalayer.instrument_resolver import resolve_all
                    ostium_symbols = get_desired_symbols()
                    resolved = resolve_all(ostium_symbols)
                    symbol_to_ostium_asset = {s: r["ostium_asset"] for s, r in resolved.items()}
                else:
                    from application.data.ostium_symbol_policy import get_ostium_ingest_symbols
                    ostium_symbols = list(get_ostium_ingest_symbols())
                    symbol_to_ostium_asset = None
                _write_mode = cfg.get("write_mode", os.getenv("DATA_LAYER_WRITE_MODE", "realtime_plus_backfill"))
                _write_mode = str(_write_mode).lower()
                ostium_ingest_allowed = _write_mode in ("realtime_only", "realtime_plus_backfill")
                if ostium_symbols and ostium_ingest_allowed:
                    try:
                        from application.services.ostium_candle_ingest_service import OstiumCandleIngestService
                        from foundation.config.constants import (
                            OSTIUM_POLL_S_ENV, DEFAULT_OSTIUM_POLL_S,
                            DATA_LAYER_GATES_MAX_GAP_S_ENV, DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV,
                            DATA_LAYER_STALE_SECONDS_ENV, DATA_LAYER_WARMUP_MINUTES_ENV,
                            OSTIUM_TICK_RECORDER_ENABLED_ENV, OSTIUM_TICK_RECORDER_OUTDIR_ENV,
                            OSTIUM_TICK_RETENTION_DAYS_ENV,
                            DEFAULT_DATA_LAYER_GATES_MAX_GAP_S, DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H,
                            DEFAULT_DATA_LAYER_STALE_SECONDS, DEFAULT_DATA_LAYER_WARMUP_MINUTES,
                            DEFAULT_OSTIUM_TICK_RECORDER_OUTDIR, DEFAULT_OSTIUM_TICK_RETENTION_DAYS,
                        )
                        tick_recorder = None
                        if os.getenv(OSTIUM_TICK_RECORDER_ENABLED_ENV, "").strip().lower() in ("1", "true", "yes"):
                            from application.services.ostium_tick_recorder import OstiumTickRecorder
                            tick_recorder = OstiumTickRecorder(
                                outdir=os.getenv(OSTIUM_TICK_RECORDER_OUTDIR_ENV, DEFAULT_OSTIUM_TICK_RECORDER_OUTDIR),
                                retention_days=int(os.getenv(OSTIUM_TICK_RETENTION_DAYS_ENV, str(DEFAULT_OSTIUM_TICK_RETENTION_DAYS))),
                            )
                        market_hours_fn = None
                        market_hours_full_fn = None
                        if role == "realtime_datalayer":
                            from apps.realtime_datalayer.market_hours import get_market_state_for_ingest, get_market_state_full
                            market_hours_fn = get_market_state_for_ingest
                            market_hours_full_fn = get_market_state_full
                        ostium_ingest_service = OstiumCandleIngestService(
                            store=candle_store,
                            symbols=ostium_symbols,
                            poll_interval_s=int(os.getenv(OSTIUM_POLL_S_ENV, str(DEFAULT_OSTIUM_POLL_S))),
                            warmup_minutes=int(os.getenv(DATA_LAYER_WARMUP_MINUTES_ENV, "120")),
                            max_gap_s=int(os.getenv(DATA_LAYER_GATES_MAX_GAP_S_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_GAP_S))),
                            max_missing_per_24h=int(os.getenv(DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H))),
                            stale_seconds=int(os.getenv(DATA_LAYER_STALE_SECONDS_ENV, str(DEFAULT_DATA_LAYER_STALE_SECONDS))),
                            tick_recorder=tick_recorder,
                            symbol_to_ostium_asset=symbol_to_ostium_asset,
                            market_hours_fn=market_hours_fn,
                            market_hours_full_fn=market_hours_full_fn,
                        )
                        await ostium_ingest_service.start()
                        logger.info("OstiumCandleIngestService started symbols=%s", ostium_symbols)
                        set_broker_deps(data_layer_write_mode=_write_mode, ostium_ingest_enabled=True)
                        if role == "realtime_datalayer":
                            app.state.ostium_ingest_service = ostium_ingest_service
                    except Exception as e:
                        logger.warning("OstiumCandleIngestService not started: %s", e)

        # BackfillService (Dukascopy) — només trading / monolithic
        if _role_starts_backfill_service(role) and market_data_service is not None:
            try:
                from application.services.backfill_service import BackfillService
                from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
                backfill_symbols = [s.strip() for s in os.getenv("BACKFILL_SYMBOLS", "EURUSD,XAUUSD").split(",") if s.strip()]
                if backfill_symbols:
                    backfill_provider = DukascopyBackfillProvider(cache_root=config["datafiles_root"])
                    backfill_service = BackfillService(
                        store=candle_store,
                        provider=backfill_provider,
                        symbols=backfill_symbols,
                        corrective_window_minutes=int(os.getenv("CORRECTIVE_WINDOW_MINUTES", "60")),
                        interval_seconds=int(os.getenv("BACKFILL_INTERVAL_SECONDS", "600")),
                    )
                    await backfill_service.start()
                    set_broker_deps(primary_backfill_provider=backfill_provider)
            except Exception as e:
                logger.warning("BackfillService not started: %s", e)

        # T8.6: SyncManager singleton — historical_datalayer (o monolithic)
        if role in ("historical_datalayer", None):
            try:
                from application.data.sync_manager import SyncManager
                sync_workers = int(os.getenv("SYNC_WORKERS", "4"))
                app.state.sync_manager = SyncManager(
                    datafiles_root=config["datafiles_root"],
                    workers=sync_workers,
                )
                logger.info("SyncManager init (workers=%d, root=%s)", sync_workers, config["datafiles_root"])
            except Exception as e:
                logger.warning("SyncManager not started: %s", e)

        # T9.07: RawSyncWorker (RAW BI5 M1 BID) — historical_datalayer (o monolithic)
        raw_sync_task = None
        if role in ("historical_datalayer", None):
            try:
                from infrastructure.venues.dukascopy.raw_sync_worker import RawSyncWorker, get_supported_symbols  # lazy import to reduce startup cost (raw sync only when role historical/monolithic)
                app.state.raw_sync_worker = RawSyncWorker(datafiles_root=config["datafiles_root"])
                logger.info("RawSyncWorker init (root=%s)", config["datafiles_root"])
                # Scheduler incremental: tail N dies cada RAW_SYNC_INTERVAL_MIN
                if os.getenv(RAW_SYNC_ENABLED_ENV, "").strip().lower() in ("1", "true", "yes"):
                    interval_min = float(os.getenv(RAW_SYNC_INTERVAL_MIN_ENV, str(DEFAULT_RAW_SYNC_INTERVAL_MIN)))
                    tail_days = int(os.getenv(RAW_SYNC_TAIL_DAYS_ENV, str(DEFAULT_RAW_SYNC_TAIL_DAYS)))
                    async def _raw_sync_loop():
                        while True:
                            await asyncio.sleep(interval_min * 60)
                            try:
                                w = getattr(app.state, "raw_sync_worker", None)
                                if not w:
                                    continue
                                to_d = date.today()
                                from_d = to_d - timedelta(days=tail_days)
                                symbols = get_supported_symbols()
                                if not symbols:
                                    continue
                                job = w.create_job(symbols, from_d.isoformat(), to_d.isoformat(), force=False)
                                asyncio.create_task(w.run_job(job.job_id))
                                logger.info("RAW_SYNC: scheduler job_id=%s symbols=%s tail=%d days", job.job_id, symbols, tail_days)
                            except asyncio.CancelledError:
                                break
                            except Exception as e:
                                logger.warning("RAW_SYNC scheduler error: %s", e)
                    raw_sync_task = asyncio.create_task(_raw_sync_loop())
                    logger.info("RAW_SYNC scheduler started (interval_min=%.0f tail_days=%d)", interval_min, tail_days)
            except Exception as e:
                logger.warning("RawSyncWorker not started: %s", e)

        heartbeat_task = None
        if os.getenv(TESTING_ENV, "").strip() == "1" or os.getenv(BROKER_DIAG_ENV, "").strip() == "1":
            async def _heartbeat_loop():
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                    logger.info("heartbeat alive pending_tasks=%d", len(asyncio.all_tasks()))
            heartbeat_task = asyncio.create_task(_heartbeat_loop())

        yield

        if raw_sync_task:
            raw_sync_task.cancel()
            try:
                await raw_sync_task
            except asyncio.CancelledError:
                pass
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 Shutting down BrokerageService (role=%s)...", role or "monolithic")
        if data_layer_prod_service:
            try:
                await data_layer_prod_service.stop()
            except Exception as e:
                logger.error("DataLayerProdService stop error: %s", e)
        if ostium_ingest_service:
            try:
                await ostium_ingest_service.stop()
            except Exception as e:
                logger.error("OstiumCandleIngestService stop error: %s", e)
        if backfill_service:
            try:
                await backfill_service.stop()
            except Exception as e:
                logger.error("BackfillService stop error: %s", e)
        if market_data_service:
            try:
                await market_data_service.stop()
            except Exception as e:
                logger.error("MARKETDATA_STOP error: %s", e)
        if adapter:
            await adapter.stop()

    if role == "realtime_datalayer":
        _title = "Realtime DataLayer API"
        _desc = (
            "Realtime DataLayer v1 — Ostium ingest 24/7, candles/ticks, hot-reload símbols. "
            "Endpoints: /health, /status, /symbols (GET/PUT), /docs, /ui"
        )
    elif role == "historical_datalayer":
        _title = "Historical DataLayer API"
        _desc = (
            "Historical DataLayer v1 — Parquet/DuckDB backfill, coverage, mixed stitching. "
            "Endpoints: /health, /status, /ohlcv/{symbol}, /coverage/{symbol}"
        )
    else:
        _title = "BrokerageService"
        _desc = "Trading brokerage service (role=%s)" % (role or "monolithic")
    app = FastAPI(
        title=_title,
        description=_desc,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for r in get_routers_for_role(role):
        app.include_router(r)

    # Phase 12: backtest API (trading_service i monolithic)
    if role in (None, "trading_service"):
        from application.api.backtest_routes import router as backtest_router
        app.include_router(backtest_router)

    # Phase 14/C: OHLCV + Coverage data API
    # - trading_service + monolithic: prefix /api/v1/data (registry-aware backtest)
    # - historical_datalayer: munta data_routes sense prefix afegit
    #   → nginx fa /data/* → strip → /ohlcv/{sym} i /coverage/{sym}
    if role in (None, "trading_service"):
        from application.api.data_routes import router as data_router
        app.include_router(data_router)
    elif role == "historical_datalayer":
        from application.api.data_routes import get_historical_router
        app.include_router(get_historical_router())

    if _role_starts_adapter(role):
        app.include_router(ws_router, prefix="/api/v1")

    @app.get("/")
    async def root():
        if role == "realtime_datalayer":
            return RedirectResponse(url="/ui", status_code=302)
        if role == "historical_datalayer":
            return {
                "service": "Historical DataLayer",
                "role": "historical_datalayer",
                "version": "0.1.0",
                "endpoints": ["/health", "/status", "/ohlcv/{symbol}", "/coverage/{symbol}", "/docs"],
            }
        return {
            "service": "BrokerageService",
            "role": role or "monolithic",
            "version": "0.1.0",
            "docs": "/docs",
        }

    # Historical DataLayer: /health i /status
    if role == "historical_datalayer":
        _historical_start = time.time()

        @app.get("/health")
        async def _historical_health():
            """
            Health del historical_datalayer.
            ok       → sense failed months (o index no creat encara)
            degraded → hi ha mesos amb status=failed
            """
            datafiles_root = os.getenv("DATAFILES_ROOT", "/datafiles")
            symbols_env = os.getenv("SYMBOLS", "EURUSD,XAUUSD")
            symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]

            from application.data.coverage_index import CoverageIndex
            total_failed = 0
            for sym in symbols:
                idx = CoverageIndex(root_path=datafiles_root, symbol=sym)
                summary = idx.summary()
                total_failed += summary.get("months_failed", 0)

            if total_failed > 0:
                return JSONResponse(
                    status_code=200,
                    content={"status": "degraded", "reason": f"{total_failed} failed month(s)"},
                )
            return {"status": "ok"}

        @app.get("/status")
        async def _historical_status():
            """
            Status del historical_datalayer: coverage per símbol + cron metadata.
            """
            datafiles_root = os.getenv("DATAFILES_ROOT", "/datafiles")
            symbols_env = os.getenv("SYMBOLS", "EURUSD,XAUUSD")
            symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]
            canonical_tz = os.getenv("CANONICAL_TZ", "America/New_York")

            from application.data.coverage_index import CoverageIndex
            from application.data.cron_metadata import read_cron_metadata

            now_utc = datetime.now(timezone.utc)
            try:
                tz_obj = zoneinfo.ZoneInfo(canonical_tz)
                now_local = now_utc.astimezone(tz_obj).strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                now_local = "—"

            symbols_data = {}
            for sym in symbols:
                idx = CoverageIndex(root_path=datafiles_root, symbol=sym)
                has_index = idx._path.exists()
                summary = idx.summary()
                # latest done month
                months = idx._data.get("months", {})
                done_months = sorted(
                    [k for k, v in months.items() if v.get("status") == "done"],
                    reverse=True,
                )
                failed_months = sorted(
                    [k for k, v in months.items() if v.get("status") == "failed"]
                )
                symbols_data[sym] = {
                    "has_index": has_index,
                    "months_done": summary.get("months_done", 0),
                    "months_failed": summary.get("months_failed", 0),
                    "months_empty": summary.get("months_empty", 0),
                    "total_rows": summary.get("total_rows", 0),
                    "latest_done_month": done_months[0] if done_months else None,
                    "failed_months": failed_months[:10],  # màxim 10 per no inflar
                }

            cron_meta = read_cron_metadata(datafiles_root)

            return {
                "effective_tz": canonical_tz,
                "now_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "now_local": now_local,
                "uptime_s": int(time.time() - _historical_start),
                "symbols": symbols_data,
                "cron": cron_meta.get("runs", {}),
            }

    # Realtime DataLayer v1: /health i /status (root)
    if role == "realtime_datalayer":
        _realtime_start = time.time()

        @app.get("/health")
        async def _realtime_health():
            from application.data.data_layer_lifecycle import get_data_layer_status  # lazy import to reduce startup cost
            from application.data.data_layer_metrics import get_data_layer_metrics, SYMBOL_STATE_DEGRADED  # lazy import to reduce startup cost
            status, _ = get_data_layer_status()
            if status == "initializing":
                return {"status": "initializing"}
            if status == "warming_up":
                return {"status": "ok"}  # warming_up = operatiu (cold start)
            metrics = get_data_layer_metrics()
            if metrics:
                snapshot = metrics.snapshot()
                for sym_data in snapshot.get("symbols", {}).values():
                    if sym_data.get("market_open") and sym_data.get("symbol_state") == SYMBOL_STATE_DEGRADED:
                        return {"status": "degraded"}
            return {"status": "ok"}

        @app.get("/status")
        async def _realtime_status():
            from application.data.data_layer_metrics import get_data_layer_metrics  # lazy import to reduce startup cost
            from application.services.ostium_tick_recorder import get_ostium_tick_recorder  # lazy import to reduce startup cost
            metrics = get_data_layer_metrics()
            tick_rec = get_ostium_tick_recorder()
            symbols_data = {}
            if metrics:
                snapshot = metrics.snapshot()
                for sym, m in snapshot.get("symbols", {}).items():
                    tick_info = {}
                    if tick_rec and tick_rec.get_status().get("symbols", {}).get(sym):
                        tick_info = tick_rec.get_status()["symbols"][sym]
                    coverage_expected = m.get("expected_open_minutes_24h", 0)
                    coverage_observed = m.get("observed_open_minutes_24h", 0)
                    coverage_missing = m.get("missing_minutes_24h", 0)
                    coverage_ratio = round(coverage_observed / coverage_expected, 4) if coverage_expected > 0 else None
                    symbols_data[sym] = {
                        "last_candle_ts": m.get("last_candle_ts"),
                        "last_tick_ts": tick_info.get("last_tick_ts"),
                        "candles_written": m.get("candles_written", 0),
                        "duplicates": m.get("duplicates", 0),
                        "gaps_detected": m.get("gaps_detected", 0),
                        "symbol_state": m.get("symbol_state", "ACTIVE"),
                        "market_open": m.get("market_open", True),
                        "market_state_reason": m.get("market_state_reason", "open"),
                        "lines_written_ticks": tick_info.get("lines_written", 0),
                        "dupes_detected_ticks": tick_info.get("dupes_detected", 0),
                        # Coverage informativa
                        "coverage_expected_minutes": coverage_expected,
                        "coverage_missing_minutes": coverage_missing,
                        "coverage_ratio": coverage_ratio,
                    }
            retention = {
                "candles_max_hours": int(os.getenv("REALTIME_CANDLES_MAX_HOURS", "168")),
                "ticks_max_hours": int(os.getenv("REALTIME_TICKS_MAX_HOURS", "72")),
            }
            canonical_tz = os.getenv("CANONICAL_TZ", "America/New_York")
            now_utc = datetime.now(timezone.utc)
            try:
                tz_obj = zoneinfo.ZoneInfo(canonical_tz)
                now_local = now_utc.astimezone(tz_obj)
                now_local_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                now_local_str = "—"
            return {
                "symbols": symbols_data,
                "retention": retention,
                "uptime_s": int(time.time() - _realtime_start),
                "ingest_state": "running" if metrics else "initializing",
                "tick_recorder_enabled": tick_rec is not None,
                "effective_tz": canonical_tz,
                "now_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "now_local": now_local_str,
            }

        @app.get("/symbols")
        async def _realtime_symbols_get():
            """Llista desired + active + mapping resolved (spot/perp) + per-symbol stats."""
            from apps.realtime_datalayer.symbol_config import load_symbols_config, get_desired_symbols  # lazy import to reduce startup cost
            from apps.realtime_datalayer.instrument_resolver import resolve_all  # lazy import to reduce startup cost
            ingest = getattr(app.state, "ostium_ingest_service", None)
            desired = get_desired_symbols()
            active = (
                [s for s in ingest.symbols if s not in ingest._stopped_symbols]
                if ingest else desired
            )
            all_symbols = set(desired) | set(active)
            if ingest:
                all_symbols |= ingest._stopped_symbols
            resolved = resolve_all(list(all_symbols))
            per_symbol_stats = ingest.get_symbol_stats() if ingest else {}
            now_ts = int(datetime.now(timezone.utc).timestamp())
            by_symbol = {}
            for sym in all_symbols:
                r = resolved.get(sym, {"ostium_asset": sym, "kind": "unknown", "resolution_source": "auto"})
                stats = per_symbol_stats.get(sym, {})
                tick_ts = stats.get("ticks_last_ts")
                candle_ts = stats.get("candle_last_ts")
                last_tick_age_s = (now_ts - tick_ts) if tick_ts else None
                last_candle_age_s = (now_ts - candle_ts) if candle_ts else None
                by_symbol[sym] = {
                    "ostium_asset": r.get("ostium_asset", sym),
                    "kind": r.get("kind", "unknown"),
                    "resolution_source": r.get("resolution_source", "auto"),
                    "market_state": stats.get("market_state", "open"),
                    "market_open": stats.get("market_open", True),
                    "market_state_reason": stats.get("market_state_reason", "open"),
                    "next_open_local": stats.get("next_open_local"),
                    "last_price": stats.get("last_price"),
                    "ticks_seen": stats.get("ticks_seen", 0),
                    "ticks_last_ts": stats.get("ticks_last_ts"),
                    "last_tick_age_s": last_tick_age_s,
                    "candles_written": stats.get("candles_written", 0),
                    "candle_last_ts": stats.get("candle_last_ts"),
                    "last_candle_age_s": last_candle_age_s,
                    "errors_count": stats.get("errors_count", 0),
                    "last_error": stats.get("last_error"),
                    "state": stats.get("state", "stopped" if sym not in active else "running"),
                    "degrade_reason": stats.get("degrade_reason"),
                    "next_poll_in_s": stats.get("next_poll_in_s"),
                    # Coverage informativa (no governa health)
                    "coverage_expected_minutes": stats.get("coverage_expected_minutes", 0),
                    "coverage_missing_minutes": stats.get("coverage_missing_minutes", 0),
                    "coverage_ratio": stats.get("coverage_ratio"),
                    "symbol_uptime_s": stats.get("symbol_uptime_s"),
                }
            return {
                "desired": desired,
                "active": active,
                "by_symbol": by_symbol,
            }

        @app.get("/ui")
        async def _realtime_ui():
            """Mini dashboard: health, status, symbols + PUT /symbols (diff/replace)."""
            ui_path = Path(__file__).resolve().parent.parent / "apps" / "realtime_datalayer" / "ui" / "index.html"
            if ui_path.exists():
                return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))
            return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)

        @app.get("/info")
        async def _realtime_info():
            """Servei info per UI: version, build, utc_now."""
            build = "dev"
            try:
                r = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=2, cwd=Path(__file__).resolve().parent.parent
                )
                if r.returncode == 0 and r.stdout.strip():
                    build = r.stdout.strip()
            except Exception:
                pass
            return {
                "service": "Realtime DataLayer",
                "version": "0.1.0",
                "build": build,
                "port": int(os.getenv("PORT", "8081")),
                "utc_now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        @app.put("/symbols")
        async def _realtime_symbols_put(body: dict = Body(default={})):
            """Hot-reload: actualitza símbols. Body: {symbols: [...], apply_mode: diff|replace}."""
            from apps.realtime_datalayer.symbol_config import (
                load_symbols_config,
                save_symbols_config,
                get_desired_symbols,
            )  # lazy import to reduce startup cost
            from apps.realtime_datalayer.instrument_resolver import resolve_all  # lazy import to reduce startup cost
            ingest = getattr(app.state, "ostium_ingest_service", None)
            if not ingest:
                raise HTTPException(status_code=503, detail="Ostium ingest not available")
            symbols_raw = body.get("symbols", [])
            apply_mode = body.get("apply_mode", "diff")
            symbols = [s.strip().upper() for s in symbols_raw if s and str(s).strip()]
            if not symbols:
                raise HTTPException(status_code=400, detail="symbols required, non-empty")
            cfg = load_symbols_config()
            current = set(cfg["symbols"])
            if apply_mode == "replace":
                new_desired = symbols
            else:
                new_desired = list(current | set(symbols))
            resolved = resolve_all(new_desired)
            symbol_to_ostium_asset = {s: r["ostium_asset"] for s, r in resolved.items()}
            save_symbols_config(new_desired, cfg.get("instrument_overrides"))
            ingest.update_symbols(new_desired, symbol_to_ostium_asset)
            return {"desired": new_desired, "active": list(ingest.symbols)}

    return app
