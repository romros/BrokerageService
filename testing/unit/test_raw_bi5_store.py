"""
BS.T9.07 — Tests unitaris per RawBi5M1Store (0-network).

- path_for_day / path_bi5 / exists_day
- write_day_atomic: .tmp → rename, manifest.json atòmic, no corrupció
- read_watermark / write_watermark
- skip si existeix i no force
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.venues.dukascopy.raw_bi5_store import (
    RawBi5M1Store,
    M1_FILENAME,
    MANIFEST_FILENAME,
    WATERMARK_FILENAME,
)


def test_path_for_day():
    store = RawBi5M1Store("/data")
    p = store.path_for_day("EURUSD", 2024, 3, 9)
    assert "EURUSD" in str(p)
    assert "year=2024" in str(p)
    assert "month=03" in str(p)
    assert "day=09" in str(p)
    assert p == store.path_bi5("EURUSD", 2024, 3, 9).parent


def test_exists_day_false(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    assert not store.exists_day("EURUSD", 2024, 1, 1)


def test_write_day_atomic_creates_bi5_and_manifest(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    raw = b"fake_bi5_content_lzma"
    url = "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/00/01/BID_candles_min_1.bi5"
    out = store.write_day_atomic("EURUSD", 2024, 1, 1, raw, url, force=False)
    assert out is not None
    assert out.exists()
    assert out.name == M1_FILENAME
    assert out.read_bytes() == raw
    manifest_path = out.parent / MANIFEST_FILENAME
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["symbol"] == "EURUSD"
    assert manifest["date"] == "2024-01-01"
    assert manifest["source_url"] == url
    assert manifest["bytes"] == len(raw)
    assert "sha256" in manifest
    assert "downloaded_at" in manifest


def test_write_day_atomic_skip_existing(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    raw = b"existing"
    store.write_day_atomic("EURUSD", 2024, 1, 1, raw, "http://example.com", force=False)
    out2 = store.write_day_atomic("EURUSD", 2024, 1, 1, b"new_content", "http://example.com", force=False)
    assert out2 is None
    assert store.path_bi5("EURUSD", 2024, 1, 1).read_bytes() == raw


def test_write_day_atomic_force_overwrites(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    store.write_day_atomic("EURUSD", 2024, 1, 1, b"old", "http://a.com", force=False)
    out = store.write_day_atomic("EURUSD", 2024, 1, 1, b"new", "http://b.com", force=True)
    assert out is not None
    assert out.read_bytes() == b"new"
    manifest = json.loads((out.parent / MANIFEST_FILENAME).read_text())
    assert manifest["source_url"] == "http://b.com"


def test_write_day_empty_returns_none(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    out = store.write_day_atomic("EURUSD", 2024, 1, 1, b"", "http://x.com", force=False)
    assert out is None
    assert not store.path_bi5("EURUSD", 2024, 1, 1).exists()


def test_exists_day_true_after_write(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    store.write_day_atomic("EURUSD", 2024, 1, 1, b"x", "http://x.com", force=False)
    assert store.exists_day("EURUSD", 2024, 1, 1)


def test_watermark_read_empty(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    w = store.read_watermark("EURUSD")
    assert w["last_complete_day"] is None
    assert w["last_attempt_day"] is None


def test_watermark_write_and_read(tmp_path):
    store = RawBi5M1Store(str(tmp_path))
    store.write_watermark("EURUSD", last_complete_day="2024-01-15", last_success_at="2024-01-15T12:00:00Z")
    w = store.read_watermark("EURUSD")
    assert w["last_complete_day"] == "2024-01-15"
    assert w["last_success_at"] == "2024-01-15T12:00:00Z"
    store.write_watermark("EURUSD", last_error="Download failed")
    w2 = store.read_watermark("EURUSD")
    assert w2["last_complete_day"] == "2024-01-15"
    assert w2["last_error"] == "Download failed"


def main():
    import tempfile
    tests = [
        test_path_for_day,
        test_exists_day_false,
        test_write_day_atomic_creates_bi5_and_manifest,
        test_write_day_atomic_skip_existing,
        test_write_day_atomic_force_overwrites,
        test_write_day_empty_returns_none,
        test_exists_day_true_after_write,
        test_watermark_read_empty,
        test_watermark_write_and_read,
    ]
    for t in tests:
        if t.__name__ in ("test_exists_day_false", "test_write_day_atomic_creates_bi5_and_manifest",
                          "test_write_day_atomic_skip_existing", "test_write_day_atomic_force_overwrites",
                          "test_write_day_empty_returns_none", "test_exists_day_true_after_write",
                          "test_watermark_read_empty", "test_watermark_write_and_read"):
            with tempfile.TemporaryDirectory() as tmp:
                t(Path(tmp))
        else:
            t()
        print(f"OK {t.__name__}")
    print("OK test_raw_bi5_store (all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
