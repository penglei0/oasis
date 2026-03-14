import sys
import unittest
from unittest.mock import MagicMock, call

# containernet_network imports mininet which is not available in the
# unit-test environment.  Stub the modules out before importing.
sys.modules.setdefault('mininet', MagicMock())
sys.modules.setdefault('mininet.net', MagicMock())
sys.modules.setdefault('mininet.util', MagicMock())

from src.containernet.containernet_network import ContainerizedNetwork


def _make_host_mock(name):
    """Create a mock host that wraps a MagicMock containernet host."""
    host = MagicMock()
    host.name = name
    host.cmd = MagicMock(return_value='')
    return host


class TestDisableBracketedPasteMode(unittest.TestCase):
    """Verify that _disable_bracketed_paste_mode sends the correct
    command to each host in the requested range."""

    def _make_network_with_hosts(self, num_hosts):
        """Build a ContainerizedNetwork-like object with mock hosts,
        bypassing __init__ to avoid requiring real containernet."""
        net = object.__new__(ContainerizedNetwork)
        hosts = []
        for i in range(num_hosts):
            mock_containernet_host = _make_host_mock(f'h{i}')
            adapter = MagicMock()
            adapter.cmd = MagicMock(return_value='')
            adapter.name.return_value = f'h{i}'
            hosts.append(adapter)
        net.hosts = hosts
        return net

    def test_disables_paste_mode_on_all_initial_hosts(self):
        """On initial setup (start=0, end=N-1), every host should
        receive the bind command to disable bracketed paste mode."""
        net = self._make_network_with_hosts(3)
        net._disable_bracketed_paste_mode(0, 2)

        expected_cmd = "bind 'set enable-bracketed-paste off' 2>/dev/null || true"
        for i in range(3):
            net.hosts[i].cmd.assert_called_once_with(expected_cmd)

    def test_disables_paste_mode_only_on_new_hosts(self):
        """On network expansion, only newly added hosts (in the
        specified range) should receive the bind command."""
        net = self._make_network_with_hosts(5)
        # Simulate expansion: only hosts 3 and 4 are new
        net._disable_bracketed_paste_mode(3, 4)

        expected_cmd = "bind 'set enable-bracketed-paste off' 2>/dev/null || true"
        # Hosts 0-2 should NOT have been called
        for i in range(3):
            net.hosts[i].cmd.assert_not_called()
        # Hosts 3-4 should have been called
        for i in range(3, 5):
            net.hosts[i].cmd.assert_called_once_with(expected_cmd)

    def test_no_call_when_range_is_empty(self):
        """When start_index > end_index, no commands should be sent."""
        net = self._make_network_with_hosts(2)
        net._disable_bracketed_paste_mode(2, 1)  # empty range

        for host in net.hosts:
            host.cmd.assert_not_called()


if __name__ == '__main__':
    unittest.main()
