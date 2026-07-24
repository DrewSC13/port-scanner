"""Errores de dominio compartidos por los motores de CicadaPort."""


class ScanCancelledError(RuntimeError):
    """Indica que el usuario canceló una operación de escaneo."""


class SpecializedFlowError(RuntimeError):
    """Indica que el flujo obligatorio Rust/Go no puede ejecutarse."""
