"""Compatibility shim; canonical BI5 implementation lives in foundation.market_data."""
from foundation.market_data.dukascopy_bi5 import (
    BASE_URL, M1_FILENAME, RECORD_SIZE_M1, PRICE_SCALE, PRICE_SCALE_JPY,
    REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY_S,
    build_m1_url, _download_bytes, _get_price_scale, decode_bi5_m1,
    fetch_m1_day, fetch_m1_range, fetch_m1_month, _write_csv, _cli,
)

if __name__ == "__main__":
    raise SystemExit(_cli())
