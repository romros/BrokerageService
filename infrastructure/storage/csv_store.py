"""
CSVCandleStore - File-based OHLCV storage implementation

Layout: datafiles/{broker}/{asset}/{timezone}/{YYYY}/{MM}.csv
Format: ts,open,high,low,close,volume

Features:
- Atomic writes (tmp + rename)
- File locking (single writer per symbol)
- Monthly partitioning
- Timezone-aware (canonical TZ: America/New_York)
- Gap validation
"""


from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import os
import shutil
import tempfile

from zoneinfo import ZoneInfo
import fcntl

from domain.interfaces import ICandleStore
from domain.models import Candle, CandleRange
from foundation.logging import get_logger
from foundation.utils.file_permissions import set_host_readable_permissions


logger = get_logger(__name__)


class CSVCandleStore(ICandleStore):
    """
    CSV-based candle storage with atomic writes and locking

    Thread-safe implementation using file locks.
    Follows canonical layout: broker/asset/timezone/year/month.csv
    """

    def __init__(
        self,
        root_path: str,
        broker: str = "gtrade",
        canonical_tz: str = "America/New_York",
    ):
        """
        Initialize CSV store

        Args:
            root_path: Root directory for datafiles (e.g., "/datafiles")
            broker: Broker/venue name (e.g., "lighter")
            canonical_tz: Timezone for storage (default: America/New_York)
        """
        self.root_path = Path(root_path)
        self.broker = broker
        self.canonical_tz = ZoneInfo(canonical_tz)

        # Ensure root exists
        self.root_path.mkdir(parents=True, exist_ok=True)
        set_host_readable_permissions(self.root_path)

        logger.info(f"CSVCandleStore initialized: root={root_path}, broker={broker}, tz={canonical_tz}")

    def _get_file_path(self, symbol: str, dt: datetime) -> Path:
        """
        Get CSV file path for given symbol and datetime

        Layout: {root}/{broker}/{symbol}/{timezone}/{YYYY}/{MM}.csv

        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            dt: Datetime to locate file for

        Returns:
            Path to CSV file
        """
        # Convert timezone name to filename-safe format
        tz_name = str(self.canonical_tz).replace("/", "_")

        # Extract year and month
        year = dt.year
        month = f"{dt.month:02d}"

        # Build path
        file_path = (
            self.root_path
            / self.broker
            / symbol
            / tz_name
            / str(year)
            / f"{month}.csv"
        )

        return file_path

    def _read_csv_file(self, file_path: Path, symbol: str) -> List[Candle]:
        """
        Read candles from CSV file

        Args:
            file_path: Path to CSV file
            symbol: Trading pair

        Returns:
            List of Candle objects (sorted by timestamp)
        """
        if not file_path.exists():
            return []

        candles = []

        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    candle = Candle.from_csv_row(symbol, line)
                    candles.append(candle)
                except Exception as e:
                    logger.warning(f"Failed to parse line {line_num} in {file_path}: {e}")
                    continue

        # Sort by timestamp (should already be sorted, but ensure it)
        candles.sort(key=lambda c: c.timestamp)

        return candles

    def _write_csv_file(self, file_path: Path, candles: List[Candle]) -> None:
        """
        Write candles to CSV file atomically

        Args:
            file_path: Path to CSV file
            candles: List of candles to write (must be sorted)

        Note:
            - Uses tmp + rename for atomicity
            - Creates parent directories if needed
        """
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        set_host_readable_permissions(file_path.parent)

        # Write to temporary file
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp"
        )

        try:
            with os.fdopen(tmp_fd, 'w') as f:
                for candle in candles:
                    f.write(candle.to_csv_row() + '\n')

            # Atomic rename
            shutil.move(tmp_path, file_path)
            set_host_readable_permissions(file_path)

        except Exception as e:
            # Cleanup tmp file on error
            try:
                os.unlink(tmp_path)
            except:
                pass
            raise e

    def _acquire_lock(self, file_path: Path) -> int:
        """
        Acquire exclusive lock on file

        Args:
            file_path: Path to lock

        Returns:
            File descriptor (to be released later)

        Note:
            - Creates lock file if doesn't exist
            - Blocks until lock acquired
        """
        lock_path = file_path.parent / f".{file_path.name}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        set_host_readable_permissions(lock_path.parent)

        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        set_host_readable_permissions(lock_path)

        return lock_fd

    def _release_lock(self, lock_fd: int) -> None:
        """Release lock"""
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    def read_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        validate_gaps: bool = True,
        log_incomplete: bool = True,
    ) -> CandleRange:
        """
        Read candles in time range [start, end)

        Args:
            symbol: Trading pair
            start: Start timestamp (inclusive)
            end: End timestamp (exclusive)
            validate_gaps: Check for gaps
            log_incomplete: Log a warning when the requested range is incomplete

        Returns:
            CandleRange with candles and completeness info
        """
        logger.debug(f"Reading range: {symbol} [{start} to {end})")

        candles = []

        # Iterate through months in range
        current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        while current < end:
            file_path = self._get_file_path(symbol, current)
            month_candles = self._read_csv_file(file_path, symbol)

            # Filter to range
            filtered = [
                c for c in month_candles
                if start <= c.timestamp < end
            ]
            candles.extend(filtered)

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        # Create range
        candle_range = CandleRange(
            symbol=symbol,
            start=start,
            end=end,
            candles=candles,
        )

        # Validate gaps if requested
        if validate_gaps:
            candle_range.validate_completeness()

            if log_incomplete and not candle_range.is_complete:
                logger.warning(
                    f"Range incomplete: {symbol} has {candle_range.missing_count} missing candles "
                    f"({candle_range.count}/{candle_range.expected_count})"
                )

        return candle_range

    def append(self, candle: Candle) -> bool:
        """
        Append a new closed candle

        Args:
            candle: Candle to append

        Returns:
            True if appended, False if already exists
        """
        if not candle.is_closed:
            raise ValueError("Cannot append open candle")

        file_path = self._get_file_path(candle.symbol, candle.timestamp)

        # Acquire lock
        lock_fd = self._acquire_lock(file_path)

        try:
            # Read existing candles
            existing = self._read_csv_file(file_path, candle.symbol)

            # Check if candle already exists
            existing_timestamps = {c.timestamp for c in existing}
            if candle.timestamp in existing_timestamps:
                logger.debug(f"Candle already exists: {candle.symbol} {candle.timestamp}")
                return False

            # Append and sort
            existing.append(candle)
            existing.sort(key=lambda c: c.timestamp)

            # Write atomically
            self._write_csv_file(file_path, existing)

            logger.debug(f"Appended candle: {candle.symbol} {candle.timestamp}")
            return True

        finally:
            self._release_lock(lock_fd)

    def patch(self, candles: List[Candle]) -> int:
        """
        Patch (insert/update) multiple candles

        Args:
            candles: Candles to patch

        Returns:
            Number of candles written
        """
        if not candles:
            return 0

        logger.info(f"Patching {len(candles)} candles for {candles[0].symbol}")

        # Group by month
        by_month = {}
        for candle in candles:
            month_key = (candle.timestamp.year, candle.timestamp.month)
            if month_key not in by_month:
                by_month[month_key] = []
            by_month[month_key].append(candle)

        written_count = 0

        # Process each month
        for (year, month), month_candles in by_month.items():
            dt = datetime(year, month, 1, tzinfo=self.canonical_tz)
            file_path = self._get_file_path(month_candles[0].symbol, dt)

            # Acquire lock
            lock_fd = self._acquire_lock(file_path)

            try:
                # Read existing
                existing = self._read_csv_file(file_path, month_candles[0].symbol)
                existing_dict = {c.timestamp: c for c in existing}

                # Merge (prefer new data)
                for candle in month_candles:
                    existing_dict[candle.timestamp] = candle
                    written_count += 1

                # Sort and write
                merged = sorted(existing_dict.values(), key=lambda c: c.timestamp)
                self._write_csv_file(file_path, merged)

            finally:
                self._release_lock(lock_fd)

        logger.info(f"Patched {written_count} candles")
        return written_count

    def get_last_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        Get timestamp of last stored candle

        Args:
            symbol: Trading pair

        Returns:
            Last timestamp or None
        """
        # Start from current month and go backward
        now = datetime.now(self.canonical_tz)
        current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Check last 12 months
        for _ in range(12):
            file_path = self._get_file_path(symbol, current)

            if file_path.exists():
                candles = self._read_csv_file(file_path, symbol)
                if candles:
                    return candles[-1].timestamp

            # Go to previous month
            if current.month == 1:
                current = current.replace(year=current.year - 1, month=12)
            else:
                current = current.replace(month=current.month - 1)

        return None

    def count_stored_candles(self, symbol: str) -> int:
        """
        Compta el total de candles emmagatzemades en disc per un símbol.

        Usa un glob per trobar tots els fitxers CSV del símbol i compta les files
        (excloent la capçalera si n'hi ha). Operació lleu: llegeix metadades de fitxer,
        no carrega les candles en memòria.

        Retorna 0 si no hi ha fitxers o el símbol és desconegut.
        """
        tz_name = str(self.canonical_tz).replace("/", "_")
        symbol_dir = self.root_path / self.broker / symbol / tz_name
        if not symbol_dir.exists():
            return 0
        total = 0
        for csv_path in symbol_dir.rglob("*.csv"):
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    lines = sum(1 for line in f if line.strip())
                # Si el fitxer té capçalera (primera línia no numèrica), resta 1
                # El nostre format CSV comença directament amb timestamp (int) — sense header
                total += lines
            except OSError:
                pass
        return total

    def get_earliest_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        Get timestamp of first stored candle (P5 coverage).

        Args:
            symbol: Trading pair

        Returns:
            First timestamp or None
        """
        tz_name = str(self.canonical_tz).replace("/", "_")
        base = self.root_path / self.broker / symbol / tz_name
        if not base.exists():
            return None
        # Iterate years forward from 2020
        for year_dir in sorted(base.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            for month_file in sorted(year_dir.glob("*.csv")):
                candles = self._read_csv_file(month_file, symbol)
                if candles:
                    return candles[0].timestamp
        return None

    def get_coverage(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[int, int, float]:
        """
        Get coverage statistics

        Args:
            symbol: Trading pair
            start: Start timestamp
            end: End timestamp

        Returns:
            (actual_count, expected_count, coverage_percent)
        """
        candle_range = self.read_range(symbol, start, end, validate_gaps=True)

        actual = candle_range.count
        expected = candle_range.expected_count
        coverage = (actual / expected * 100) if expected > 0 else 0.0

        return (actual, expected, coverage)

    def validate_integrity(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> bool:
        """
        Validate data integrity

        Args:
            symbol: Trading pair
            start: Start timestamp (optional)
            end: End timestamp (optional)

        Returns:
            True if valid

        Raises:
            ValueError: If integrity issues found
        """
        # Default range: last 30 days
        if end is None:
            end = datetime.now(self.canonical_tz)
        if start is None:
            start = end.replace(day=1)

        candle_range = self.read_range(symbol, start, end, validate_gaps=True)

        # Check gaps
        if not candle_range.is_complete:
            raise ValueError(
                f"Data has gaps: {candle_range.missing_count} missing candles"
            )

        # Check sorted
        for i in range(1, len(candle_range.candles)):
            prev = candle_range.candles[i - 1]
            curr = candle_range.candles[i]

            if curr.timestamp <= prev.timestamp:
                raise ValueError(
                    f"Timestamps not sorted: {prev.timestamp} >= {curr.timestamp}"
                )

        # Check duplicates (should not happen if sorted)
        timestamps = [c.timestamp for c in candle_range.candles]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("Duplicate timestamps found")

        logger.info(f"Integrity check passed: {symbol} [{start} to {end})")
        return True
