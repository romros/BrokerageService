from datetime import datetime, timezone
from urllib.error import HTTPError

from infrastructure.venues.dukascopy.bi5_ticks_backfill_provider import (
    Bi5TicksBackfillProvider,
    _retry_delay,
)


def test_429_retry_after_wins(monkeypatch):
    error = HTTPError("https://example", 429, "limited", {"Retry-After": "17"}, None)
    assert _retry_delay(error, 0) == 17


def test_429_exponential_backoff_is_configurable(monkeypatch):
    monkeypatch.setenv("DUKASCOPY_TICK_429_BACKOFF_S", "10")
    monkeypatch.setenv("DUKASCOPY_TICK_429_BACKOFF_MAX_S", "25")
    error = HTTPError("https://example", 429, "limited", {}, None)
    assert [_retry_delay(error, n) for n in range(4)] == [10, 20, 25, 25]


def test_provider_defaults_to_conservative_rate(monkeypatch, tmp_path):
    monkeypatch.delenv("DUKASCOPY_TICK_RATE_LIMIT_S", raising=False)
    assert Bi5TicksBackfillProvider(str(tmp_path))._rate_limit_s == 1.0


def test_historical_404_is_cached_as_empty(monkeypatch, tmp_path):
    provider = Bi5TicksBackfillProvider(str(tmp_path), rate_limit_s=0)
    calls = []

    def no_data(url):
        calls.append(url)
        return None

    monkeypatch.setattr(
        "infrastructure.venues.dukascopy.bi5_ticks_backfill_provider._download_bytes",
        no_data,
    )
    assert provider._fetch_hour_sync("GBPUSD", 2020, 1, 4, 3) == []
    assert provider._fetch_hour_sync("GBPUSD", 2020, 1, 4, 3) == []
    assert len(calls) == 1
    marker = provider._empty_cache_path("GBPUSD", 2020, 1, 4, 3)
    assert marker.exists()
