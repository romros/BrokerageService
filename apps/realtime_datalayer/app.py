"""
Entrypoint realtime_datalayer — Ostium recorder 24/7 + serve candles/ticks recents.

SERVICE_ROLE=realtime_datalayer. Només Data Layer + Ostium ingest + endpoints de dades.
GET /health i GET /status registrats a create_app quan role=realtime_datalayer.
"""

import os

from application.app_factory import create_app

os.environ.setdefault("SERVICE_ROLE", "realtime_datalayer")
app = create_app(role="realtime_datalayer")
