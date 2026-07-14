import sys
import unittest
from unittest.mock import MagicMock, patch

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


class TestMultiHomingShaping(unittest.TestCase):
    """Multi-homing applies one physical link profile at both ends."""

    def test_link_profile_is_shared_by_both_endpoints(self):
        net = object.__new__(ContainerizedNetwork)
        net.hosts = [MagicMock(), MagicMock()]
        net.hosts[0].get_host.return_value = MagicMock()
        net.hosts[1].get_host.return_value = MagicMock()
        net.pair_to_link = {}
        net.is_multihoming = True
        profile = {'bw': 8, 'rtt': 10, 'loss': 2, 'jitter': 1}
        net.multihoming_link_attributes = {1: profile}
        net._bandwidth_limit_on_egress_for_multihoming = MagicMock()
        net._traffic_shaping_on_ingress = MagicMock()
        link = MagicMock()
        link.intf1.name = 'h0-eth1'
        link.intf2.name = 'h1-eth1'
        net.containernet = MagicMock()
        net.containernet.addLink.return_value = link

        net._addLink(1, 0, link_index=1)

        net._bandwidth_limit_on_egress_for_multihoming.assert_called_once_with(
            link, 1, 0, profile)
        self.assertEqual(net._traffic_shaping_on_ingress.call_count, 2)
        for call in net._traffic_shaping_on_ingress.call_args_list:
            self.assertIs(call.args[-1], profile)


class TestTopologyLinkExpansion(unittest.TestCase):
    """Verify adjacency triangles expand to the intended physical links."""

    def _make_network(self, adjacency, multihoming=False):
        net = object.__new__(ContainerizedNetwork)
        net.num_of_hosts = 2
        net.net_mat = adjacency
        net.node_ip_start = '10.0.0.0/24'
        net.node_ip_range = '10.0.0.0/16'
        net.hosts = [MagicMock(), MagicMock()]
        net.hosts[0].name.return_value = 'h0'
        net.hosts[1].name.return_value = 'h1'
        net.pair_to_link_ip = {}
        net.is_multihoming = multihoming
        net.net_topology = MagicMock()
        net.net_topology.ascii_art.return_value = ''
        net._addLink = MagicMock()
        return net

    @staticmethod
    def _parse_network(value):
        return (0, 24) if value.endswith('/24') else (0, 8)

    def test_non_multihoming_uses_only_upper_triangle_for_one_link(self):
        net = self._make_network([[0, 1], [1, 0]])

        with patch('src.containernet.containernet_network.netParse',
                   side_effect=self._parse_network):
            self.assertTrue(net._setup_topology())

        net._addLink.assert_called_once()
        self.assertEqual(net._addLink.call_args.args[:2], (0, 1))

    def test_multihoming_uses_lower_triangle_for_second_link(self):
        net = self._make_network([[0, 1], [1, 0]], multihoming=True)
        net.multihoming_link_attributes = {
            0: {'bw': 8, 'rtt': 10, 'loss': 0, 'jitter': 0},
            1: {'bw': 24, 'rtt': 25, 'loss': 0, 'jitter': 0},
        }

        with patch('src.containernet.containernet_network.netParse',
                   side_effect=self._parse_network):
            self.assertTrue(net._setup_topology())

        self.assertEqual(net._addLink.call_count, 2)
        self.assertEqual(net._addLink.call_args_list[0].args[:2], (0, 1))
        self.assertEqual(net._addLink.call_args_list[1].args[:2], (1, 0))
        self.assertEqual(net._addLink.call_args_list[0].kwargs['link_index'], 0)
        self.assertEqual(net._addLink.call_args_list[1].kwargs['link_index'], 1)


if __name__ == '__main__':
    unittest.main()
