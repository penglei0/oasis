import unittest

from src.core.linear_topology import LinearTopology
from src.core.mesh_topology import MeshTopology
from src.core.topology import MatrixType, TopologyConfig, TopologyType


class TestTopologyAsciiArt(unittest.TestCase):

    @staticmethod
    def make_mesh_topology(adjacency, bandwidth, loss, latency):
        topology = MeshTopology(
            '',
            TopologyConfig(
                name='mesh',
                nodes=len(adjacency),
                topology_type=TopologyType.mesh
            ),
            False
        )
        topology.all_mats[MatrixType.ADJACENCY_MATRIX] = adjacency
        topology.all_mats[MatrixType.BW_MATRIX] = bandwidth
        topology.all_mats[MatrixType.LOSS_MATRIX] = loss
        topology.all_mats[MatrixType.LATENCY_MATRIX] = latency
        topology.all_mats[MatrixType.JITTER_MATRIX] = [
            [0 for _ in row] for row in adjacency
        ]
        return topology

    def test_linear_topology_ascii_art_uses_link_metrics(self):
        topology = LinearTopology(
            '',
            TopologyConfig(
                name='linear',
                nodes=3,
                topology_type=TopologyType.linear,
                array_description=[
                    {'link_loss': None, 'init_value': [1]},
                    {'link_latency': None, 'init_value': [10]},
                    {'link_jitter': None, 'init_value': [0]},
                    {'link_bandwidth_forward': None, 'init_value': [1000]},
                    {'link_bandwidth_backward': None, 'init_value': [1000]},
                ]
            )
        )

        self.assertEqual(
            next(iter(topology)).ascii_art(),
            "h0 <----(1000,10ms,1%)-----> h1 <----(1000,10ms,1%)-----> h2"
        )

    def test_mesh_topology_ascii_art_renders_diamond_layout(self):
        topology = self.make_mesh_topology(
            adjacency=[
                [0, 1, 1, 0],
                [1, 0, 0, 1],
                [1, 0, 0, 1],
                [0, 1, 1, 0],
            ],
            bandwidth=[
                [0, 1000, 1000, 0],
                [1000, 0, 0, 1000],
                [1000, 0, 0, 1000],
                [0, 1000, 1000, 0],
            ],
            loss=[
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0.5, 0, 0, 0.5],
                [0, 0.5, 0.5, 0],
            ],
            latency=[
                [0, 25, 25, 0],
                [25, 0, 0, 25],
                [25, 0, 0, 25],
                [0, 25, 25, 0],
            ]
        )

        ascii_art = topology.ascii_art().splitlines()

        self.assertEqual(ascii_art[0].strip(), 'h1')
        self.assertEqual(ascii_art[2], 'h0                           h3')
        self.assertEqual(ascii_art[-1].strip(), 'h2')
        self.assertIn('(1000,25ms,0%)', ascii_art[1])
        self.assertIn('(1000,25ms,0.5%)', ascii_art[3])

    def test_mesh_topology_ascii_art_renders_rectangle_layout(self):
        topology = self.make_mesh_topology(
            adjacency=[
                [0, 1, 0, 1],
                [1, 0, 1, 0],
                [0, 1, 0, 1],
                [1, 0, 1, 0],
            ],
            bandwidth=[
                [0, 100, 0, 400],
                [100, 0, 200, 0],
                [0, 200, 0, 300],
                [400, 0, 300, 0],
            ],
            loss=[
                [0, 1, 0, 4],
                [1, 0, 2, 0],
                [0, 2, 0, 3],
                [4, 0, 3, 0],
            ],
            latency=[
                [0, 10, 0, 40],
                [10, 0, 20, 0],
                [0, 20, 0, 30],
                [40, 0, 30, 0],
            ]
        )

        ascii_art = topology.ascii_art().splitlines()

        self.assertEqual(ascii_art[0], 'h0 <----(100,10ms,1%)-----> h1')
        self.assertIn('(400,40ms,4%)', ascii_art[1])
        self.assertIn('(200,20ms,2%)', ascii_art[1])
        self.assertEqual(ascii_art[2], 'h3 <----(300,30ms,3%)-----> h2')

    def test_mesh_topology_ascii_art_renders_star_layout(self):
        topology = self.make_mesh_topology(
            adjacency=[
                [0, 1, 1, 1, 1],
                [1, 0, 0, 0, 0],
                [1, 0, 0, 0, 0],
                [1, 0, 0, 0, 0],
                [1, 0, 0, 0, 0],
            ],
            bandwidth=[
                [0, 50, 60, 70, 80],
                [50, 0, 0, 0, 0],
                [60, 0, 0, 0, 0],
                [70, 0, 0, 0, 0],
                [80, 0, 0, 0, 0],
            ],
            loss=[
                [0, 1, 2, 3, 4],
                [1, 0, 0, 0, 0],
                [2, 0, 0, 0, 0],
                [3, 0, 0, 0, 0],
                [4, 0, 0, 0, 0],
            ],
            latency=[
                [0, 10, 11, 12, 13],
                [10, 0, 0, 0, 0],
                [11, 0, 0, 0, 0],
                [12, 0, 0, 0, 0],
                [13, 0, 0, 0, 0],
            ]
        )

        ascii_art = topology.ascii_art().splitlines()

        self.assertEqual(ascii_art[0].strip(), 'h1')
        self.assertEqual(
            ascii_art[4],
            'h2 <----(60,11ms,2%)-----> h0 <----(70,12ms,3%)-----> h3'
        )
        self.assertIn('(80,13ms,4%)', ascii_art[6])
        self.assertEqual(ascii_art[-1].strip(), 'h4')


if __name__ == '__main__':
    unittest.main()
