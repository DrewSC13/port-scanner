import unittest
from unittest.mock import MagicMock, patch

from config import config
from src.banner import BannerGrabber


class TestBannerProbePolicy(unittest.TestCase):
    def test_active_probes_are_limited_to_known_http_ports(self):
        for port in (80, 443, 8000, 8080, 8443, 9200):
            with self.subTest(port=port):
                self.assertTrue(BannerGrabber.should_send_http_probe(port))

        for port in (21, 22, 25, 3306, 6379):
            with self.subTest(port=port):
                self.assertFalse(BannerGrabber.should_send_http_probe(port))

    def test_tls_is_used_only_for_known_tls_ports(self):
        for port in (443, 465, 636, 993, 995, 2376, 8443):
            with self.subTest(port=port):
                self.assertTrue(BannerGrabber.should_use_tls(port))

        for port in (21, 22, 25, 80, 8080):
            with self.subTest(port=port):
                self.assertFalse(BannerGrabber.should_use_tls(port))

    def test_non_http_service_is_passive_only(self):
        connection = MagicMock()
        connection.recv.return_value = b"SSH-2.0-test\r\n"

        with patch(
            "src.banner.socket.create_connection",
            return_value=connection,
        ):
            banner = BannerGrabber.grab_banner(
                "127.0.0.1",
                22,
                timeout=0.1,
            )

        self.assertEqual(banner, "SSH-2.0-test")
        connection.sendall.assert_not_called()
        connection.recv.assert_called_once()

    def test_https_wraps_connection_before_sending_probe(self):
        connection = MagicMock()
        tls_stream = MagicMock()
        tls_stream.recv.return_value = b"HTTP/1.0 200 OK\r\n\r\n"
        context = MagicMock()
        context.wrap_socket.return_value = tls_stream

        with (
            patch(
                "src.banner.socket.create_connection",
                return_value=connection,
            ),
            patch.object(
                BannerGrabber,
                "_create_tls_context",
                return_value=context,
            ),
        ):
            banner = BannerGrabber.grab_banner(
                "example.com",
                443,
                timeout=0.1,
            )

        self.assertEqual(banner, "HTTP/1.0 200 OK")
        context.wrap_socket.assert_called_once_with(
            connection,
            server_hostname="example.com",
        )
        tls_stream.sendall.assert_called_once_with(
            BannerGrabber.build_http_probe("example.com")
        )
        connection.sendall.assert_not_called()

    def test_hostile_banner_sanitization_is_deterministic(self):
        raw = b"\x00=2+5\r\n<script>alert(1)</script>\xff\x00"

        self.assertEqual(
            BannerGrabber.sanitize_banner(raw),
            "=2+5  <script>alert(1)</script>",
        )

    def test_banner_length_is_limited_by_unicode_characters(self):
        banner = BannerGrabber.sanitize_banner(
            "é" * (config.MAX_BANNER_OUTPUT_LENGTH + 1)
        )

        self.assertEqual(len(banner), config.MAX_BANNER_OUTPUT_LENGTH)


if __name__ == "__main__":
    unittest.main()
