"""
OperationStorePort — interfície per persistència d'operacions (open/close).

El port exposa create, update, get, has, generate_id, rehydrate.
"""

from typing import Optional, Protocol


class OperationStorePort(Protocol):
    """
    Port per gestió d'operacions (JSONL + in-memory).

    Implementació: OperationService.
    """

    def generate_id(self) -> str:
        """Genera id curt per operació."""
        ...

    def create(
        self,
        operation_id: str,
        kind: str,
        venue: str,
        symbol: str,
        position_id: str = "",
    ) -> None:
        """Crea operació in_progress."""
        ...

    def update(
        self,
        operation_id: str,
        status: str,
        position_id: str = "",
        tx_hash: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Actualitza estat operació."""
        ...

    def get(self, operation_id: str) -> Optional[dict]:
        """Retorna operació o None."""
        ...

    def has(self, operation_id: str) -> bool:
        """Comprova si operació existeix."""
        ...

    def rehydrate(self) -> None:
        """Rehidratar store des del JSONL."""
        ...
