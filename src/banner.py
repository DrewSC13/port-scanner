"""Banner grabbing explícito con sondeos de aplicación limitados."""

from __future__ import annotations

import socket
import ssl
from typing import Any, Dict, Optional

from config import config


class BannerGrabber:
    """Obtiene banners solo cuando la CLI lo solicita expresamente."""

    HTTP_PROBE_PORTS = frozenset({80, 443, 8000, 8080, 8443, 9200})
    TLS_PORTS = frozenset({443, 465, 636, 993, 995, 2376, 8443})

    @staticmethod
    def _normalize_host(host: str) -> str:
        """Quita corchetes externos para conexiones y SNI."""
        normalized = host.strip()
        if normalized.startswith("[") and normalized.endswith("]"):
            return normalized[1:-1]
        return normalized

    @classmethod
    def should_send_http_probe(cls, port: int) -> bool:
        """Indica si está permitido el único sondeo activo soportado."""
        return port in cls.HTTP_PROBE_PORTS

    @classmethod
    def should_use_tls(cls, port: int) -> bool:
        """Indica si el flujo de banner debe protegerse con TLS."""
        return port in cls.TLS_PORTS

    @classmethod
    def build_http_probe(cls, host: str) -> bytes:
        """Construye un único HEAD conservador para puertos HTTP conocidos."""
        normalized_host = cls._normalize_host(host)
        host_header = (
            f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        )
        return (
            "HEAD / HTTP/1.0\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: CicadaPort\r\n"
            "\r\n"
        ).encode("ascii", errors="ignore")

    @staticmethod
    def _create_tls_context() -> ssl.SSLContext:
        """
        Crea un contexto de inspección compatible con servicios autofirmados.

        El banner grabber comprueba que el servicio habla TLS, pero no afirma
        la identidad del objetivo ni usa el resultado como canal de confianza.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    @staticmethod
    def sanitize_banner(raw: bytes | str) -> Optional[str]:
        """Normaliza banners de red de forma idéntica al motor Go."""
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="ignore")
        else:
            text = str(raw)

        cleaned = (
            text.replace("\x00", "")
            .replace("\r", " ")
            .replace("\n", " ")
            .strip()
        )
        cleaned = cleaned[: config.MAX_BANNER_OUTPUT_LENGTH]
        return cleaned or None

    @classmethod
    def grab_banner(
        cls,
        host: str,
        port: int,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """
        Obtiene un banner con una sola conexión.

        Solo los puertos HTTP conocidos reciben un sondeo ``HEAD``. El resto
        se limita a esperar un banner pasivo. Los puertos HTTPS conocidos usan
        TLS antes de enviar o leer datos de aplicación.
        """
        effective_timeout = timeout or config.BANNER_TIMEOUT
        normalized_host = cls._normalize_host(host)
        connection = None
        stream = None

        try:
            connection = socket.create_connection(
                (normalized_host, port),
                timeout=effective_timeout,
            )
            connection.settimeout(effective_timeout)
            stream = connection

            if cls.should_use_tls(port):
                context = cls._create_tls_context()
                stream = context.wrap_socket(
                    connection,
                    server_hostname=normalized_host,
                )
                stream.settimeout(effective_timeout)

            if cls.should_send_http_probe(port):
                stream.sendall(cls.build_http_probe(host))

            raw_banner = stream.recv(config.MAX_BANNER_LENGTH)
            return cls.sanitize_banner(raw_banner)
        except (OSError, ssl.SSLError):
            return None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
            elif connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    @classmethod
    def get_service_info(
        cls,
        host: str,
        port: int,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Conserva la API informativa sin acoplarla al escaneo TCP."""
        from src.network import NetworkUtils

        service_name = NetworkUtils.get_service_name(port)
        common_service = config.COMMON_PORTS.get(port, "Unknown")
        return {
            "port": port,
            "service": service_name,
            "common_name": common_service,
            "banner": cls.grab_banner(host, port, timeout),
            "protocol": "tcp",
        }
