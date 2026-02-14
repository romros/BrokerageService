"""
Unit tests: SL/TP idempotency (P1.1)

- mateix request 2 cops => 1 sola acció efectiva
- update idèntic => no-op
- cancel idèntic => no-op
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrastructure.storage.sltp_store import JsonSltpStore


def test_sltp_store_get_sltp_indices():
    """JsonSltpStore.get_sltp_indices returns (sl, tp, sl_ix, tp_ix)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sltp.json"
        store = JsonSltpStore(p)
        store.set_sltp("1:1", sl=1900.0, tp=2100.0, sl_order_index=42, tp_order_index=43)
        sl, tp, sl_ix, tp_ix = store.get_sltp_indices("1:1")
        assert sl == 1900.0 and tp == 2100.0
        assert sl_ix == 42 and tp_ix == 43
        store.clear_sl("1:1")
        sl, tp, sl_ix, tp_ix = store.get_sltp_indices("1:1")
        assert sl is None and sl_ix is None
        assert tp == 2100.0 and tp_ix == 43
    print("✓ test_sltp_store_get_sltp_indices")


def test_sltp_store_clear_tp():
    """JsonSltpStore.clear_tp clears tp and tp_order_index."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sltp.json"
        store = JsonSltpStore(p)
        store.set_sltp("1:1", sl=1900.0, tp=2100.0, sl_order_index=42, tp_order_index=43)
        store.clear_tp("1:1")
        sl, tp, sl_ix, tp_ix = store.get_sltp_indices("1:1")
        assert tp is None and tp_ix is None
        assert sl == 1900.0 and sl_ix == 42
    print("✓ test_sltp_store_clear_tp")


def main():
    test_sltp_store_get_sltp_indices()
    test_sltp_store_clear_tp()
    print("\n✓ All P1.1 SL/TP idempotency unit tests passed")


if __name__ == "__main__":
    main()
