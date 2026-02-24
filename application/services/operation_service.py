"""
OperationService — create/update/get/persist/rehydrate operations (T5.40).

Manté operations.jsonl com ara. Usat per OrderOpenService i OrderCloseService.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from foundation.config.constants import (
    OPERATIONS_JSONL_ENV,
    DEFAULT_OPERATIONS_JSONL,
    OPERATIONS_REHYDRATE_MAX_LINES,
)
from foundation.logging import get_logger

logger = get_logger(__name__)


class OperationService:
    """Gestió d'operacions open/close: store in-memory + persistència JSONL."""

    def __init__(self) -> None:
        self._store: Dict[str, dict] = {}
        self._path: Optional[Path] = None

    def _get_path(self) -> Path:
        if self._path is None:
            raw = os.getenv(OPERATIONS_JSONL_ENV, DEFAULT_OPERATIONS_JSONL).strip()
            self._path = Path(raw) if raw else Path(DEFAULT_OPERATIONS_JSONL)
        return self._path

    def _append(self, op: dict) -> None:
        """Append JSONL (best-effort, no bloqueja)."""
        try:
            path = self._get_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(op, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("operations JSONL append failed: %s", e)

    def rehydrate(self) -> None:
        """Rehidratar store des del JSONL (últims N events)."""
        path = self._get_path()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-OPERATIONS_REHYDRATE_MAX_LINES:] if len(lines) > OPERATIONS_REHYDRATE_MAX_LINES else lines
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    op = json.loads(line)
                    oid = op.get("operation_id")
                    if oid:
                        self._store[oid] = op
                except json.JSONDecodeError:
                    continue
            if self._store:
                logger.info("operations rehydrated: %d from %s", len(self._store), path)
        except Exception as e:
            logger.warning("operations rehydrate failed: %s", e)

    def generate_id(self) -> str:
        """Short operation id (12 chars)."""
        return uuid.uuid4().hex[:12]

    def create(
        self,
        operation_id: str,
        kind: str,
        venue: str,
        symbol: str,
        position_id: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        op = {
            "operation_id": operation_id,
            "kind": kind,
            "venue": venue,
            "symbol": symbol,
            "position_id": position_id or "",
            "tx_hash": "",
            "status": "in_progress",
            "created_at": now,
            "last_update": now,
            "error": None,
        }
        self._store[operation_id] = op
        self._append(op)

    def update(
        self,
        operation_id: str,
        status: str,
        position_id: str = "",
        tx_hash: str = "",
        error: Optional[str] = None,
    ) -> None:
        if operation_id not in self._store:
            return
        op = self._store[operation_id]
        op["last_update"] = datetime.now(timezone.utc).isoformat()
        op["status"] = status
        if position_id:
            op["position_id"] = position_id
        if tx_hash:
            op["tx_hash"] = tx_hash
        if error is not None:
            op["error"] = error
        self._append(op)

    def get(self, operation_id: str) -> Optional[dict]:
        return self._store.get(operation_id)

    def has(self, operation_id: str) -> bool:
        return operation_id in self._store


# Singleton per compartir store
_operation_service: Optional[OperationService] = None


def get_operation_service() -> OperationService:
    global _operation_service
    if _operation_service is None:
        _operation_service = OperationService()
    return _operation_service
