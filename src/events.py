"""Eventos compartidos por la CLI, la TUI y el núcleo de CicadaPort."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from src.scanner import ScanResult


class ScanEventType(str, Enum):
    """Tipos de eventos emitidos por el orquestador."""

    STATUS = "status"
    TARGET_STARTED = "target_started"
    PROGRESS = "progress"
    OPEN_PORT = "open_port"
    REPORT = "report"
    TARGET_COMPLETE = "target_complete"
    TARGET_FAILED = "target_failed"
    COMPLETE = "complete"
    BATCH_COMPLETE = "batch_complete"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ScanEvent:
    """Actualización inmutable producida durante una sesión de escaneo."""

    kind: ScanEventType
    message: str = ""
    progress: Optional[float] = None
    result: Optional[ScanResult] = None
    data: Dict[str, Any] = field(default_factory=dict)
