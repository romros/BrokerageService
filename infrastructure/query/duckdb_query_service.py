"""
DuckDBQueryService — Phase 16.

Query layer sobre Parquet particionat (Phase 15) usant DuckDB embedded.

Avantatges vs read_range manual:
- Predicate pushdown: llegeix només les particions i columnes necessàries
- Paginació eficient per `next_ts` (cursor basat en timestamp)
- Agregacions futures (5m/1h) trivials

Layout esperat (Phase 15):
  {root}/historical_parquet/{SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet

Ús:
    svc = DuckDBQueryService(root_path="/datafiles")
    result = svc.query_ohlcv(
        symbol="EURUSD",
        from_ts=1700000000,
        to_ts=1700086400,
        limit=1000,
    )
    # result: {"candles": [[ts,o,h,l,c,v], ...], "next_ts": int|None, "total_in_range": int}
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from foundation.logging import get_logger

logger = get_logger(__name__)

PARQUET_SUBDIR = "historical_parquet"
TIMEFRAME = "1m"


class DuckDBQueryService:
    """
    Query OHLCV des de Parquet particionat via DuckDB embedded.

    Cada instància té la seva pròpia connexió DuckDB in-memory.
    Thread-safe per a ús concurrent si es creen instàncies separades.
    """

    def __init__(self, root_path: str):
        self._root = Path(root_path) / PARQUET_SUBDIR

    def _glob_pattern(self, symbol: str) -> str:
        """Retorna el glob pattern per llegir totes les particions d'un símbol."""
        return str(self._root / symbol.upper() / f"tf={TIMEFRAME}" / "**" / "*.parquet")

    def has_data(self, symbol: str) -> bool:
        """True si existeix almenys una partició Parquet per al símbol."""
        sym_dir = self._root / symbol.upper() / f"tf={TIMEFRAME}"
        if not sym_dir.exists():
            return False
        return any(sym_dir.rglob("*.parquet"))

    def query_ohlcv(
        self,
        symbol: str,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 1000,
        next_ts: Optional[int] = None,
    ) -> dict:
        """
        Consulta OHLCV paginada via DuckDB + Parquet.

        Args:
            symbol: Símbol (normalitzat a majúscules)
            from_ts: Epoch UTC inici (inclusiu). None = sense límit inferior.
            to_ts: Epoch UTC fi (exclusiu). None = sense límit superior.
            limit: Màxim candles retornades.
            next_ts: Cursor: si donat, comença a partir d'aquest timestamp (exclusiu).
                     Permet paginació eficient sense offset gran.

        Returns:
            {
                "candles": [[ts, open, high, low, close, volume], ...],
                "next_ts": int|None,    # timestamp del pròxim cursor; null si no hi ha més
                "total_in_range": int,  # total candles al rang (sense paginació)
                "source": "historical_parquet"
            }
        """
        import duckdb

        glob = self._glob_pattern(symbol)

        # Construir condicions WHERE
        conditions = []
        params = []
        if next_ts is not None:
            conditions.append("ts > ?")
            params.append(next_ts)
        elif from_ts is not None:
            conditions.append("ts >= ?")
            params.append(from_ts)
        if to_ts is not None:
            conditions.append("ts < ?")
            params.append(to_ts)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Comptem total (per next_ts correcte)
        count_sql = f"SELECT COUNT(*) FROM read_parquet('{glob}', hive_partitioning=true) {where_clause}"
        data_sql = f"""
            SELECT ts, open, high, low, close, volume
            FROM read_parquet('{glob}', hive_partitioning=true)
            {where_clause}
            ORDER BY ts ASC
            LIMIT ?
        """

        con = duckdb.connect(":memory:")
        try:
            total_in_range = con.execute(count_sql, params).fetchone()[0]
            rows = con.execute(data_sql, params + [limit]).fetchall()
        finally:
            con.close()

        candles = [[r[0], r[1], r[2], r[3], r[4], r[5]] for r in rows]

        # next_ts: timestamp de la candle SEGÜENT al límit retornat
        new_next_ts = None
        if len(candles) == limit and total_in_range > limit:
            new_next_ts = candles[-1][0]  # ts de l'última candle retornada

        logger.info(
            "duckdb_query symbol=%s from=%s to=%s limit=%d returned=%d total=%d",
            symbol, from_ts, to_ts, limit, len(candles), total_in_range,
        )

        return {
            "candles": candles,
            "next_ts": new_next_ts,
            "total_in_range": total_in_range,
            "source": "historical_parquet",
        }

    def compute_xdata_headers(
        self,
        symbol: str,
        candles: list,
        from_ts: Optional[int],
        to_ts: Optional[int],
    ) -> dict[str, str]:
        """
        Calcula headers X-Data-* per un chunk de candles retornat.

        candles: format [[ts, o, h, l, c, v], ...]
        """
        if not candles:
            return {
                "X-Data-Source": "historical_parquet",
                "X-Data-Coverage-From": str(from_ts or 0),
                "X-Data-Coverage-To": str(to_ts or 0),
                "X-Data-Missing-Minutes": "0",
                "X-Data-Max-Gap-S": "0",
            }

        ts_list = [c[0] for c in candles]
        coverage_from = ts_list[0]
        coverage_to = ts_list[-1] + 60  # fi de l'última candle

        expected = max(0, (coverage_to - coverage_from) // 60)
        actual = len(ts_list)
        missing = max(0, expected - actual)

        max_gap_s = 0
        if len(ts_list) > 1:
            for i in range(1, len(ts_list)):
                gap = ts_list[i] - ts_list[i - 1] - 60  # gap net (60s és normal)
                if gap > max_gap_s:
                    max_gap_s = gap

        return {
            "X-Data-Source": "historical_parquet",
            "X-Data-Coverage-From": str(coverage_from),
            "X-Data-Coverage-To": str(coverage_to),
            "X-Data-Missing-Minutes": str(missing),
            "X-Data-Max-Gap-S": str(max_gap_s),
        }
