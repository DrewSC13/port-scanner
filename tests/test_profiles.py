import inspect
import unittest

from config import config
from src.profiles import SCAN_PROFILES, resolve_scan_options


class TestScanProfiles(unittest.TestCase):
    def test_all_public_profiles_exist(self):
        self.assertEqual(
            list(SCAN_PROFILES),
            ["safe", "standard", "deep", "custom"],
        )

    def test_custom_uses_specialized_engine_defaults(self):
        options = resolve_scan_options("custom")

        self.assertEqual(options.ports, config.DEFAULT_PORTS)
        self.assertFalse(options.common_ports)
        self.assertEqual(options.threads, config.DEFAULT_THREADS)
        self.assertEqual(options.timeout, config.DEFAULT_TIMEOUT)
        self.assertEqual(options.engine, "rust")
        self.assertFalse(options.banner_grab)
        self.assertEqual(options.banner_engine, "go")

    def test_public_option_resolution_does_not_accept_engine_selectors(self):
        parameters = inspect.signature(resolve_scan_options).parameters

        self.assertNotIn("engine", parameters)
        self.assertNotIn("banner_engine", parameters)

    def test_explicit_port_range_overrides_safe_common_ports(self):
        options = resolve_scan_options("safe", ports="443")

        self.assertEqual(options.ports, "443")
        self.assertFalse(options.common_ports)

    def test_deep_profile_covers_full_tcp_range(self):
        options = resolve_scan_options("deep")

        self.assertEqual(options.ports, "1-65535")
        self.assertEqual(options.engine, "rust")
        self.assertTrue(options.banner_grab)
        self.assertEqual(options.banner_engine, "go")


if __name__ == "__main__":
    unittest.main()
