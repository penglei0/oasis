import unittest
from unittest.mock import MagicMock, call

from src.routing.static_routing_bfs import StaticRoutingBfs


def _make_host(name):
    host = MagicMock()
    host.name.return_value = name
    host.cmd = MagicMock()
    return host


def _make_network(adjacency, hosts, pair_to_link_ip):
    """Build a minimal mock network for routing tests."""
    net = MagicMock()
    net.get_hosts.return_value = hosts
    net.get_link_table.return_value = pair_to_link_ip
    net.net_mat = adjacency
    return net


class TestStaticRoutingBfsDiamond(unittest.TestCase):
    """Test BFS routing on a diamond (2-path) topology.

    Topology (path2-p0-p1 style):
        h0 --- h1 --- h3
        h0 --- h2 --- h3

    Links & IPs (mimicking containernet IP assignment):
        link(0,1): h0=10.0.0.1, h1=10.0.0.2
        link(0,2): h0=10.0.1.1, h2=10.0.1.2
        link(1,3): h1=10.0.2.1, h3=10.0.2.2
        link(2,3): h2=10.0.3.1, h3=10.0.3.2
    """

    def setUp(self):
        self.adjacency = [
            [0, 1, 1, 0],
            [1, 0, 0, 1],
            [1, 0, 0, 1],
            [0, 1, 1, 0],
        ]
        self.hosts = [_make_host(f'h{i}') for i in range(4)]
        h = self.hosts
        self.pair_to_link_ip = {
            # link (0,1)
            (h[0], h[1]): '10.0.0.2',   # h1's IP on h0-h1 link
            (h[1], h[0]): '10.0.0.1',   # h0's IP on h0-h1 link
            # link (0,2)
            (h[0], h[2]): '10.0.1.2',   # h2's IP on h0-h2 link
            (h[2], h[0]): '10.0.1.1',   # h0's IP on h0-h2 link
            # link (1,3)
            (h[1], h[3]): '10.0.2.2',   # h3's IP on h1-h3 link
            (h[3], h[1]): '10.0.2.1',   # h1's IP on h1-h3 link
            # link (2,3)
            (h[2], h[3]): '10.0.3.2',   # h3's IP on h2-h3 link
            (h[3], h[2]): '10.0.3.1',   # h2's IP on h2-h3 link
        }
        self.network = _make_network(
            self.adjacency, self.hosts, self.pair_to_link_ip)

    def _routes_on(self, host_index):
        """Collect (dst_ip, gateway_ip) tuples from ip-route add calls."""
        routes = []
        for c in self.hosts[host_index].cmd.call_args_list:
            args = c[0][0]
            if args.startswith('ip r a '):
                parts = args.split()
                # ip r a <dst>/32 via <gw>
                dst = parts[3].replace('/32', '')
                gw = parts[5]
                routes.append((dst, gw))
        return routes

    def test_h0_has_route_to_h3_via_h1(self):
        """h3's IP on the h1-h3 link must be reachable from h0 via h1."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(0)
        self.assertIn(('10.0.2.2', '10.0.0.2'), routes)

    def test_h0_has_route_to_h3_via_h2(self):
        """h3's IP on the h2-h3 link must be reachable from h0 via h2."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(0)
        self.assertIn(('10.0.3.2', '10.0.1.2'), routes)

    def test_h3_has_route_to_h0_via_h1(self):
        """h0's IP on the h0-h1 link must be reachable from h3 via h1."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(3)
        self.assertIn(('10.0.0.1', '10.0.2.1'), routes)

    def test_h3_has_route_to_h0_via_h2(self):
        """h0's IP on the h0-h2 link must be reachable from h3 via h2."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(3)
        self.assertIn(('10.0.1.1', '10.0.3.1'), routes)

    def test_no_routes_to_directly_connected_same_link(self):
        """No explicit route should be added for an IP that is on a
        directly connected subnet (e.g. h0 to h1's IP on the h0-h1 link)."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(0)
        dst_ips = [dst for dst, _ in routes]
        # 10.0.0.2 is h1's IP on h0-h1 link; h0 is directly connected.
        self.assertNotIn('10.0.0.2', dst_ips)
        # 10.0.1.2 is h2's IP on h0-h2 link; h0 is directly connected.
        self.assertNotIn('10.0.1.2', dst_ips)


class TestStaticRoutingBfsChain(unittest.TestCase):
    """Test BFS routing on a simple 3-node chain topology.

    h0 --- h1 --- h2
    """

    def setUp(self):
        self.adjacency = [
            [0, 1, 0],
            [1, 0, 1],
            [0, 1, 0],
        ]
        self.hosts = [_make_host(f'h{i}') for i in range(3)]
        h = self.hosts
        self.pair_to_link_ip = {
            (h[0], h[1]): '10.0.0.2',
            (h[1], h[0]): '10.0.0.1',
            (h[1], h[2]): '10.0.1.2',
            (h[2], h[1]): '10.0.1.1',
        }
        self.network = _make_network(
            self.adjacency, self.hosts, self.pair_to_link_ip)

    def _routes_on(self, host_index):
        routes = []
        for c in self.hosts[host_index].cmd.call_args_list:
            args = c[0][0]
            if args.startswith('ip r a '):
                parts = args.split()
                dst = parts[3].replace('/32', '')
                gw = parts[5]
                routes.append((dst, gw))
        return routes

    def test_h0_routes_to_h2_via_h1(self):
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(0)
        # h2's IP on h1-h2 link → via h1
        self.assertIn(('10.0.1.2', '10.0.0.2'), routes)

    def test_h2_routes_to_h0_via_h1(self):
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(2)
        # h0's IP on h0-h1 link → via h1
        self.assertIn(('10.0.0.1', '10.0.1.1'), routes)

    def test_h1_has_no_explicit_route_for_directly_connected_ip(self):
        """h0's only IP on the h0-h1 link is on a directly connected subnet
        of h1, so no explicit route should be added."""
        StaticRoutingBfs().setup_routes(self.network)
        routes = self._routes_on(1)
        dst_ips = [dst for dst, _ in routes]
        self.assertNotIn('10.0.0.1', dst_ips)


if __name__ == '__main__':
    unittest.main()
