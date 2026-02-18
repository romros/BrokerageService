"""
Entrypoint realtime_datalayer — Ostium recorder 24/7 + serve candles/ticks recents.

SERVICE_ROLE=realtime_datalayer. Només Data Layer + Ostium ingest + endpoints de dades.
"""

import os

from application.app_factory import create_app

os.environ.setdefault("SERVICE_ROLE", "realtime_datalayer")
app = create_app(role="realtime_datalayer")
