
import logging
from collections import deque
from interfaces.routing import IRoutingStrategy


class StaticRoutingBfs(IRoutingStrategy):
    """Summary:
    Configure static routing for the network using BFS to find the shortest path.
    StaticRoutingBfs is the replacement for StaticRouting which only works with the chain network.
    """

    def __init__(self):
        self.pair_to_link_ip = {}
        self.net_routes = []

    def setup_routes(self, network: 'INetwork'):
        '''
        Setup the routing by ip route.
        For each (src, dst) pair, route to every IP address of dst.
        Each destination host may have multiple interfaces (and IPs) in
        mesh topologies.  For a given dst IP that sits on the link between
        dst and some neighbour *nbr*, we find the shortest path from src
        to nbr and use its first hop as the gateway.  This ensures each
        dst IP is reached through the interface that is topologically
        closest to the corresponding link.
        '''
        hosts = network.get_hosts()
        self.pair_to_link_ip = network.get_link_table()
        adjacency = network.net_mat  # adjacency matrix
        num_hosts = len(hosts)

        # Compute next hops for all pairs using BFS
        for src in range(num_hosts):
            for dst in range(num_hosts):
                if src == dst:
                    continue
                # Iterate over every neighbour of dst to discover all of
                # dst's interface IPs.
                for nbr in range(num_hosts):
                    if not adjacency[nbr][dst] or nbr == dst:
                        continue
                    # dst's IP on the nbr–dst link
                    dst_ip = self.pair_to_link_ip.get(
                        (hosts[nbr], hosts[dst]))
                    if not dst_ip:
                        continue
                    if nbr == src:
                        # src is directly connected to dst on this link;
                        # the connected-subnet route already covers it.
                        continue
                    # Route toward nbr so the packet arrives at the
                    # correct link where dst_ip resides.
                    path = self._bfs_shortest_path(adjacency, src, nbr)
                    if not path:
                        continue
                    if len(path) < 2:
                        # src == nbr, but we excluded that above
                        continue
                    next_hop = path[1]
                    gateway_ip = self.pair_to_link_ip.get(
                        (hosts[src], hosts[next_hop]))
                    if gateway_ip:
                        self._add_ip_gateway(
                            hosts[src], gateway_ip, dst_ip)
                        logging.debug(
                            "Static route: %s -> %s (ip %s) via %s (%s)",
                            hosts[src].name(), hosts[dst].name(),
                            dst_ip, hosts[next_hop].name(), gateway_ip)
                    else:
                        logging.warning(
                            "No link IP for %s to %s",
                            hosts[src].name(), hosts[next_hop].name())

    @staticmethod
    def _add_ip_gateway(host, gateway_ip, dst_ip):
        host.cmd(f'ip r a {dst_ip}/32 via {gateway_ip}')

    def _bfs_shortest_path(self, adjacency, start, goal):
        queue = deque([[start]])
        visited = set()
        while queue:
            path = queue.popleft()
            node = path[-1]
            if node == goal:
                return path
            if node in visited:
                continue
            visited.add(node)
            for neighbor, connected in enumerate(adjacency[node]):
                if connected and neighbor not in visited:
                    queue.append(path + [neighbor])
        return None
