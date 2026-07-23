import socket
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from src.contracts import AddressFamily, ReasonCode
from src.targets import (
    TargetExpansionLimitError,
    TargetParseError,
    TargetParser,
    TargetResolutionError,
    TargetResolver,
)


class TestTargetParser(unittest.TestCase):
    def test_mixed_specs_expand_deduplicate_and_keep_order(self):
        parser = TargetParser(max_targets=16)

        targets = parser.parse(
            [
                "192.0.2.1",
                "192.0.2.2-192.0.2.4",
                "2001:db8::1",
                "example.test",
                "192.0.2.0/31",
            ]
        )

        self.assertEqual(
            [target.value for target in targets],
            [
                "192.0.2.1",
                "192.0.2.2",
                "192.0.2.3",
                "192.0.2.4",
                "2001:db8::1",
                "example.test",
                "192.0.2.0",
            ],
        )

    def test_target_file_comments_and_exclusions(self):
        parser = TargetParser(max_targets=16)

        with tempfile.TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / "targets.txt"
            target_file.write_text(
                """
                # laboratorio autorizado
                192.0.2.1
                192.0.2.2-192.0.2.4  # segmento local
                example.test
                """,
                encoding="utf-8",
            )

            targets = parser.parse(
                target_files=[target_file],
                exclusions=["192.0.2.2", "example.test"],
            )

        self.assertEqual(
            [target.value for target in targets],
            ["192.0.2.1", "192.0.2.3", "192.0.2.4"],
        )
        self.assertTrue(targets[0].source.endswith("targets.txt:3"))

    def test_expansion_limit_blocks_large_network_before_materializing(self):
        parser = TargetParser(max_targets=4)

        with self.assertRaisesRegex(TargetExpansionLimitError, "4"):
            parser.parse(["10.0.0.0/8"])

    def test_reversed_ip_range_is_rejected(self):
        parser = TargetParser(max_targets=16)

        with self.assertRaisesRegex(TargetParseError, "invertido"):
            parser.parse(["192.0.2.10-192.0.2.1"])

    def test_ipv4_to_ipv6_range_is_rejected(self):
        parser = TargetParser(max_targets=16)

        with self.assertRaisesRegex(TargetParseError, "familia"):
            parser.parse(["192.0.2.1-2001:db8::1"])

    def test_empty_input_is_rejected(self):
        with self.assertRaisesRegex(TargetParseError, "objetivo"):
            TargetParser().parse([])


class TestTargetResolver(unittest.TestCase):
    @patch("src.targets.socket.getaddrinfo")
    def test_getaddrinfo_deduplicates_and_orders_ipv4_before_ipv6(
        self,
        getaddrinfo,
    ):
        getaddrinfo.return_value = [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "example.test",
                ("2001:db8::2", 0, 0, 0),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "example.test",
                ("192.0.2.2", 0),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.0.2.2", 0),
            ),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::1", 0, 0, 0),
            ),
        ]

        identities = TargetResolver().resolve("example.test")

        self.assertEqual(
            [identity.address for identity in identities],
            ["192.0.2.2", "2001:db8::1", "2001:db8::2"],
        )
        self.assertEqual(
            [identity.family for identity in identities],
            [
                AddressFamily.IPV4,
                AddressFamily.IPV6,
                AddressFamily.IPV6,
            ],
        )
        getaddrinfo.assert_called_once_with(
            "example.test",
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
            flags=socket.AI_CANONNAME,
        )

    @patch("src.targets.socket.getaddrinfo")
    def test_literal_address_does_not_use_dns(self, getaddrinfo):
        identities = TargetResolver().resolve("2001:db8::10")

        getaddrinfo.assert_not_called()
        self.assertEqual(identities[0].address, "2001:db8::10")
        self.assertEqual(identities[0].family, AddressFamily.IPV6)

    @patch("src.targets.socket.getaddrinfo")
    def test_resolution_failure_has_structured_reason(self, getaddrinfo):
        getaddrinfo.side_effect = socket.gaierror("not found")

        with self.assertRaises(TargetResolutionError) as context:
            TargetResolver().resolve("missing.test")

        self.assertEqual(context.exception.reason, ReasonCode.RESOLUTION_FAILED)
        self.assertEqual(context.exception.target, "missing.test")


if __name__ == "__main__":
    unittest.main()
