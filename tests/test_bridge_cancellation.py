import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

from src.bridge_go import GoBannerBridge
from src.bridge_rust import RustScannerBridge
from src.errors import ScanCancelledError


class TestNativeBridgeCancellation(unittest.TestCase):
    @staticmethod
    def _cancelled_process():
        process = MagicMock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="native", timeout=0.1),
            ("", ""),
        ]
        return process

    def test_rust_subprocess_is_terminated_on_cancellation(self):
        cancel_event = threading.Event()
        cancel_event.set()
        process = self._cancelled_process()

        with (
            patch.object(
                RustScannerBridge,
                "is_available",
                return_value=True,
            ),
            patch(
                "src.bridge_rust.subprocess.Popen",
                return_value=process,
            ),
        ):
            with self.assertRaises(ScanCancelledError):
                RustScannerBridge("/tmp/rust-core").scan(
                    "127.0.0.1",
                    [80],
                    cancel_event=cancel_event,
                )

        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_go_subprocess_is_terminated_on_cancellation(self):
        cancel_event = threading.Event()
        cancel_event.set()
        process = self._cancelled_process()

        with (
            patch.object(
                GoBannerBridge,
                "is_available",
                return_value=True,
            ),
            patch(
                "src.bridge_go.subprocess.Popen",
                return_value=process,
            ),
        ):
            with self.assertRaises(ScanCancelledError):
                GoBannerBridge("/tmp/go-banner").grab_banners(
                    "127.0.0.1",
                    [443],
                    cancel_event=cancel_event,
                )

        process.terminate.assert_called_once()
        process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
