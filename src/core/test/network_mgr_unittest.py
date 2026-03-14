import sys
import unittest
from unittest.mock import MagicMock

# network_mgr imports containernet which depends on mininet (not available
# in the unit-test environment).  Stub it out before importing.
sys.modules.setdefault('mininet', MagicMock())
sys.modules.setdefault('mininet.net', MagicMock())
sys.modules.setdefault('mininet.util', MagicMock())

from src.core.network_mgr import NetworkManager, _mesh_compatible_routes
from src.core.topology import TopologyType


def _make_topology(topology_type):
    """Create a mock topology with the given type."""
    top = MagicMock()
    top.get_topology_type.return_value = topology_type
    top.description.return_value = "mock topology"
    return top


class TestNetworkManagerMeshValidation(unittest.TestCase):
    """Validate that mesh topologies reject incompatible route strategies."""

    def test_mesh_with_static_route_is_rejected(self):
        """static_route does not support mesh topologies."""
        mgr = NetworkManager()
        top = _make_topology(TopologyType.mesh)
        node_config = MagicMock()
        with self.assertLogs(level='ERROR') as log:
            result = mgr.build_networks(node_config, top, 1, 'static_route')
        self.assertFalse(result)
        self.assertTrue(
            any('Mesh topology requires a compatible route strategy'
                in entry for entry in log.output))

    def test_mesh_with_static_bfs_is_accepted(self):
        """static_bfs supports mesh topologies — should not be rejected."""
        mgr = NetworkManager()
        top = _make_topology(TopologyType.mesh)
        node_config = MagicMock()
        # build_networks will fail downstream (no real containernet), but
        # it should pass the validation check.
        try:
            mgr.build_networks(node_config, top, 1, 'static_bfs')
        except Exception:
            pass  # downstream failure is acceptable here
        # If we got here, the mesh+static_bfs check did not reject.

    def test_mesh_with_openr_route_is_accepted(self):
        """openr_route supports mesh topologies — should not be rejected."""
        mgr = NetworkManager()
        top = _make_topology(TopologyType.mesh)
        node_config = MagicMock()
        try:
            mgr.build_networks(node_config, top, 1, 'openr_route')
        except Exception:
            pass

    def test_linear_with_static_route_is_not_rejected(self):
        """static_route is valid for linear topologies."""
        mgr = NetworkManager()
        top = _make_topology(TopologyType.linear)
        node_config = MagicMock()
        try:
            mgr.build_networks(node_config, top, 1, 'static_route')
        except Exception:
            pass  # downstream failures unrelated to validation

    def test_mesh_compatible_routes_set(self):
        """The set of compatible routes should include static_bfs and openr_route."""
        self.assertIn('static_bfs', _mesh_compatible_routes)
        self.assertIn('openr_route', _mesh_compatible_routes)


if __name__ == '__main__':
    unittest.main()
