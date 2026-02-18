"""
Entrypoint trading_service — Broker/execució. Consumeix Data Layer.

SERVICE_ROLE=trading_service. Només trading/broker API (sense ingest, sense data layer writer).
"""

import os

from application.app_factory import create_app

os.environ.setdefault("SERVICE_ROLE", "trading_service")
app = create_app(role="trading_service")
