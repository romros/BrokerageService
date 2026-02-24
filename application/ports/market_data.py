"""
MarketDataPort — interfície per quality gate (inputs del Data Layer).

El port exposa get_ohlcv_with_gate per avaluar qualitat abans d'executar.
"""

from typing import Any, Optional, Protocol


class MarketDataPort(Protocol):
    """
    Port per lectura de dades amb quality gate.

    Implementacions: IDataLayerReader (HttpDataLayerReader, LocalDataLayerReader).
    """

    async def get_ohlcv_with_gate(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> tuple[dict[str, Any], dict[str, str], Any]:
        """
        Retorna (body, headers, QualityGateResult).
        El caller aplica NO_TRADE si gate.is_bad().
        """
        ...
