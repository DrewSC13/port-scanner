import unittest
from unittest.mock import patch, MagicMock
from src.scanner import PortScanner, ScanResult
from src.network import NetworkUtils

class TestPortScanner(unittest.TestCase):
    
    def setUp(self):
        self.scanner = PortScanner(timeout=0.1, max_threads=10)
    
    @patch('src.scanner.socket.socket')
    def test_scan_port_open(self, mock_socket):
        # Configurar mock
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0
        
        result = self.scanner.scan_port("127.0.0.1", 80)
        
        self.assertTrue(result.is_open)
        self.assertEqual(result.port, 80)
        self.assertIsNone(result.banner)
        mock_sock.sendall.assert_not_called()
        mock_sock.recv.assert_not_called()
    
    @patch('src.scanner.socket.socket')
    def test_scan_port_closed(self, mock_socket):
        mock_sock = MagicMock()
        mock_socket.return_value = mock_sock
        mock_sock.connect_ex.return_value = 1
        
        result = self.scanner.scan_port("127.0.0.1", 8080)
        
        self.assertFalse(result.is_open)

class TestNetworkUtils(unittest.TestCase):
    
    def test_resolve_host_ip(self):
        result = NetworkUtils.resolve_host("127.0.0.1")
        self.assertEqual(result, "127.0.0.1")
    
    def test_validate_port_range_valid(self):
        result = NetworkUtils.validate_port_range("1-100")
        self.assertEqual(result, (1, 100))
    
    def test_validate_port_range_invalid(self):
        result = NetworkUtils.validate_port_range("1000-100")
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
