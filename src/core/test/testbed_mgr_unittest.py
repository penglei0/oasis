import unittest
from src.interfaces.network_mgr import NetworkType
from src.core.testbed_mgr import TestbedManager, load_all_hosts


class TestTestbedManager(unittest.TestCase):
    """Unit tests for TestbedManager."""

    def test_type_is_testbed(self):
        mgr = TestbedManager()
        self.assertEqual(mgr.get_type(), NetworkType.testbed)

    def test_initial_networks_empty(self):
        mgr = TestbedManager()
        self.assertEqual(mgr.get_networks(), [])

    def test_get_top_description_empty(self):
        mgr = TestbedManager()
        self.assertEqual(mgr.get_top_description(), '')

    def test_enable_halt(self):
        mgr = TestbedManager()
        # enable_halt should run without errors
        mgr.enable_halt()

    def test_start_networks(self):
        mgr = TestbedManager()
        # start_networks should run without errors on empty list
        mgr.start_networks()

    def test_stop_networks(self):
        mgr = TestbedManager()
        mgr.stop_networks()

    def test_reset_networks(self):
        mgr = TestbedManager()
        mgr.reset_networks()


class TestLoadAllHosts(unittest.TestCase):
    """Unit tests for load_all_hosts helper."""

    def test_empty_list_returns_none(self):
        with self.assertLogs(level='INFO') as log_context:
            result = load_all_hosts([])
        self.assertIsNone(result)
        self.assertTrue(
            any("No hosts were loaded for the testbed." in entry
                for entry in log_context.output)
        )

    def test_valid_host_configs(self):
        hosts_yaml = [
            {'user': 'root', 'ip': '10.0.0.1', 'arch': 'x86_64'},
            {'user': 'admin', 'ip': '10.0.0.2', 'arch': 'arm64'},
        ]
        # load_all_hosts currently returns False when hosts are loaded
        result = load_all_hosts(hosts_yaml)
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
