"""
Unit tests: GET /mode retorna market_data_env (PAPER mainnet-data per Freqtrade)

Valida:
1) GET /mode retorna camp market_data_env
2) market_data_env es propaga des de config/set_broker_deps
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient

from application.main import create_app
from application.api.broker_routes import set_broker_deps


def test_mode_returns_market_data_env_default():
    """GET /mode retorna market_data_env (default mainnet)."""
    app = create_app()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        r = client.get("/api/v1/broker/mode")
    assert r.status_code == 200
    data = r.json()
    assert "market_data_env" in data
    assert data["market_data_env"] in ("mainnet", "testnet")
    # Default from load_config (sense MARKET_DATA_ENV) és mainnet
    assert data["market_data_env"] == "mainnet"
    print("✓ GET /mode retorna market_data_env (default mainnet) OK")


def test_mode_market_data_env_from_set_broker_deps():
    """market_data_env es pot injectar via set_broker_deps."""
    app = create_app()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(market_data_env="testnet")
        r = client.get("/api/v1/broker/mode")
    assert r.status_code == 200
    data = r.json()
    assert data["market_data_env"] == "testnet"
    print("✓ market_data_env=testnet via set_broker_deps OK")
