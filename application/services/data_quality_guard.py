"""
Data Quality Guard — enforce quality gate abans d'executar ordres.

Equivalent a live_guards.py però per qualitat de dades:
si el data layer retorna dades degradades (X-Data-* headers BAD) → NO_TRADE.

Patró: guard pura que llança DataQualityGateBadError.
El caller (broker_routes._do_order_open) la captura i retorna 422/503.

NEVER throws per error de xarxa (fail-closed: si no podem comprovar la qualitat,
és bad per defecte).
"""

from typing import Any, Optional

from foundation.logging import get_logger
from application.errors import DataQualityGateBadError

logger = get_logger(__name__)


async def assert_data_quality_ok(
    reader: Any,
    symbol: str,
    tf: str = "1m",
    limit: int = 10,
) -> None:
    """
    Comprova la qualitat de les dades OHLCV via quality gate.

    Si gate.is_bad() → llança DataQualityGateBadError (NO_TRADE).
    Si gate.is_ok() → retorna sense fer res (caller continua).

    Sempre avalua: fail-closed si el reader falla o headers absents.

    Args:
        reader: IDataLayerReader (HttpDataLayerReader o LocalDataLayerReader)
        symbol: símbol a comprovar
        tf: timeframe (default 1m)
        limit: candles a demanar (petit: només per tenir headers; default 10)

    Raises:
        DataQualityGateBadError: si gate=BAD (dades degradades o headers absents)
    """
    try:
        _body, _headers, gate = await reader.get_ohlcv_with_gate(
            symbol=symbol, tf=tf, limit=limit
        )
    except Exception as exc:
        # Xarxa / servei down → fail-closed: tractar com BAD
        logger.warning(
            "NO_TRADE quality_gate_bad symbol=%s reason=reader_error error=%s",
            symbol, exc,
        )
        raise DataQualityGateBadError(
            symbol=symbol,
            reason="reader_error",
            quality_meta={"error": str(exc)},
        ) from exc

    if gate.is_bad():
        logger.warning(
            "NO_TRADE quality_gate_bad symbol=%s reason=%s meta=%s",
            symbol, gate.reason, gate.quality_meta,
        )
        raise DataQualityGateBadError(
            symbol=symbol,
            reason=gate.reason,
            quality_meta=gate.quality_meta,
        )

    logger.debug(
        "quality_gate_ok symbol=%s reason=%s meta=%s",
        symbol, gate.reason, gate.quality_meta,
    )
