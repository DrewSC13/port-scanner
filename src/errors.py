"""Errores de dominio compartidos por los motores de CicadaPort."""


class ScanCancelledError(RuntimeError):
    """Indica que el usuario canceló una operación de escaneo."""
