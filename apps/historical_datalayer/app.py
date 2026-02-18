"""
Entrypoint historical_datalayer — Dukascopy/backfill/compat. Consumeix dades del realtime.

SERVICE_ROLE=historical_datalayer. Només backfill/repair + endpoints de coverage/ohlcv.
"""

import os

from application.app_factory import create_app

os.environ.setdefault("SERVICE_ROLE", "historical_datalayer")
app = create_app(role="historical_datalayer")
