import sys
import unittest
from unittest.mock import MagicMock

# containernet_network imports mininet which is not available in the
# unit-test environment.  Stub the modules out before importing.
sys.modules.setdefault('mininet', MagicMock())
sys.modules.setdefault('mininet.net', MagicMock())
sys.modules.setdefault('mininet.util', MagicMock())

from src.containernet.containernet_network import ContainerizedNetwork


class TestDisableBracketedPasteMode(unittest.TestCase):
    """Verify that _disable_bracketed_paste_mode sends the correct
    command to each host in the requested range."""

    def _make_network_with_hosts(self, num_hosts):
        """Build a ContainerizedNetwork-like object with mock hosts,
        bypassing __init__ to avoid requiring real containernet."""
        net = object.__new__(ContainerizedNetwork)
        hosts = []
        for i in range(num_hosts):
            adapter = MagicMock()
            adapter.cmd = MagicMock(return_value='')
            adapter.name = MagicMock(return_value=f'h{i}')
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


class TestResetNetwork(unittest.TestCase):
    """Verify reload teardown removes the links that were actually added."""

    def _make_network_with_hosts(self, num_hosts):
        net = object.__new__(ContainerizedNetwork)
        net.hosts = []
        for i in range(num_hosts):
            adapter = MagicMock()
            adapter.cmd = MagicMock(return_value='')
            adapter.cleanup = MagicMock()
            adapter.deleteIntfs = MagicMock()
            adapter.name = MagicMock(return_value=f'h{i}')
            net.hosts.append(adapter)
        net.routing_strategy = MagicMock()
        net.containernet = MagicMock()
        net.num_of_hosts = num_hosts
        net.pair_to_link = {}
        net.pair_to_link_ip = {}
        return net

    def test_add_link_records_link_for_future_reset(self):
        """Added links should be tracked so reload can remove them later."""
        net = self._make_network_with_hosts(3)
        for host in net.hosts:
            host.get_host.return_value = MagicMock()
        net._bandwidth_limit_on_egress = MagicMock()
        net._traffic_shaping_on_ingress = MagicMock()
        link = MagicMock()
        link.intf1.name = 'h0-eth0'
        link.intf2.name = 'h2-eth0'
        net.containernet.addLink.return_value = link

        returned_link = net._addLink(0, 2, params1={'ip': '10.0.0.1/24'})

        self.assertIs(returned_link, link)
        self.assertEqual(net.pair_to_link, {(net.hosts[0], net.hosts[2]): link})

    def test_reset_network_removes_existing_mesh_links(self):
        """Reset should remove the exact mesh links instead of assuming a chain."""
        net = self._make_network_with_hosts(4)
        net.pair_to_link = {
            (net.hosts[0], net.hosts[1]): MagicMock(),
            (net.hosts[0], net.hosts[2]): MagicMock(),
            (net.hosts[1], net.hosts[3]): MagicMock(),
            (net.hosts[2], net.hosts[3]): MagicMock(),
        }

        net._reset_network(4, 0)

        expected_calls = [
            unittest.mock.call(node1='h0', node2='h1'),
            unittest.mock.call(node1='h0', node2='h2'),
            unittest.mock.call(node1='h1', node2='h3'),
            unittest.mock.call(node1='h2', node2='h3'),
        ]
        net.containernet.removeLink.assert_has_calls(
            expected_calls, any_order=True)
        self.assertEqual(net.containernet.removeLink.call_count, 4)
        self.assertNotIn(
            unittest.mock.call(node1='h1', node2='h2'),
            net.containernet.removeLink.call_args_list)


if __name__ == '__main__':
    unittest.main()
