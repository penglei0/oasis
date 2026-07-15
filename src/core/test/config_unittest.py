import unittest
from pathlib import Path
from unittest.mock import patch
from functools import reduce
from operator import mul
import yaml
from src.core.config import IConfig, load_all_tests
from src.core.config import Test, TopologyConfig
from src.core.mesh_topology import MeshTopology
from src.core.multi_homing_topology import MultiHomingTopology
from src.core.topology import MatrixType, TopologyType


class TestLoadAllTests(unittest.TestCase):

    @staticmethod
    def find_repo_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / '.git').exists():
                return parent
        raise FileNotFoundError(
            f"Could not locate repository root starting from {current} "
            "(no .git directory found in parent directories).")

    @staticmethod
    def expected_path_description_count(path_description):
        vector_keys = ("bw_vector", "rtt_vector", "loss_vector", "jitter_vector")
        return reduce(
            mul,
            (
                len(path[vector_key])
                for path in path_description
                for vector_key in vector_keys
            ),
            1)

    @patch('builtins.open')
    @patch('yaml.safe_load')
    def test_load_all_tests_with_valid_yaml(self, mock_yaml_load, mock_open):
        # Mock data
        mock_yaml_content = {
            "tests": {
                "test1": {
                    "if": True,
                    # other test configurations
                },
                "test2": {
                    "if": False,
                    # other test configurations
                },
                "test3": {
                    # 'if' key not present, should default to True
                    # other test configurations
                }
            }
        }
        mock_yaml_load.return_value = mock_yaml_content

        test_yaml_file = 'test.yaml'
        test_name = 'all'

        # Call the function
        result = load_all_tests(test_yaml_file, test_name)

        # Check that open was called
        mock_open.assert_called_once_with(
            test_yaml_file, 'r', encoding='utf-8')

        # Verify the result
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, 'test1')
        self.assertEqual(result[1].name, 'test3')

    @patch('builtins.open')
    @patch('yaml.safe_load')
    def test_load_all_tests_with_specific_test_name(self, mock_yaml_load, mock_open):
        # Mock data
        mock_yaml_content = {
            "tests": {
                "test1": {
                    "if": True,
                },
                "test2": {
                    "if": True,
                }
            }
        }
        mock_yaml_load.return_value = mock_yaml_content

        test_yaml_file = 'test.yaml'
        test_name = 'test1'

        # Call the function
        result = load_all_tests(test_yaml_file, test_name)

        # Verify the result
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'test1')

    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_load_all_tests_file_not_found(self, mock_open):
        test_yaml_file = 'non_existing.yaml'
        result = load_all_tests(test_yaml_file)

        # Verify the result is empty due to file not found
        self.assertEqual(result, [])

    @patch('builtins.open')
    @patch('yaml.safe_load', side_effect=yaml.YAMLError)
    def test_load_all_tests_yaml_error(self, mock_yaml_load, mock_open):
        test_yaml_file = 'invalid.yaml'
        result = load_all_tests(test_yaml_file)

        # Verify the result is empty due to YAML error
        self.assertEqual(result, [])

    @patch('builtins.open')
    @patch('yaml.safe_load')
    def test_load_all_tests_no_tests_key(self, mock_yaml_load, mock_open):
        # Mock data without 'tests' key
        mock_yaml_content = {}
        mock_yaml_load.return_value = mock_yaml_content

        test_yaml_file = 'test.yaml'
        result = load_all_tests(test_yaml_file)

        # Verify the result is empty
        self.assertEqual(result, [])

    @patch('builtins.open')
    @patch('yaml.safe_load')
    def test_load_all_tests_no_active_tests(self, mock_yaml_load, mock_open):
        # Mock data with all tests inactive
        mock_yaml_content = {
            "tests": {
                "test1": {
                    "if": False,
                },
                "test2": {
                    "if": False,
                }
            }
        }
        mock_yaml_load.return_value = mock_yaml_content

        test_yaml_file = 'test.yaml'
        result = load_all_tests(test_yaml_file)

        # Verify the result is empty
        self.assertEqual(len(result), 0)

    @patch('builtins.open')
    @patch('yaml.safe_load')
    def test_load_all_tests_with_none_test_cases_logs_info(self, mock_yaml_load, mock_open):
        mock_yaml_load.return_value = {"tests": None}

        with self.assertLogs(level='INFO') as log_context:
            result = load_all_tests('test.yaml')

        self.assertEqual(result, [])
        mock_open.assert_called_once_with('test.yaml', 'r', encoding='utf-8')
        self.assertTrue(
            any("No test cases were loaded from test.yaml." in entry
                for entry in log_context.output)
        )

    def test_bats_iperf_config_validation(self):
        repo_root = self.find_repo_root()
        tests = load_all_tests(str(repo_root / 'test' / 'protocol-ci-test.yaml'))

        test3 = next((test for test in tests if test.name == 'test3'), None)
        self.assertIsNotNone(
            test3,
            f"test3 not found in loaded tests. Available tests: {[test.name for test in tests]}")
        test_tools = test3.yaml()['test_tools']

        self.assertEqual(set(test_tools.keys()), {'bats_iperf'})
        self.assertEqual(test_tools['bats_iperf'], {
            'interval': 1,
            'interval_num': 20,
            'client_host': 0,
            'server_host': 3,
        })

    def test_quic_multipath_3paths_topology_has_three_parallel_paths(self):
        repo_root = self.find_repo_root()
        top_config = IConfig.load_config_reference(
            str(repo_root / 'test'),
            'predefined.topology.yaml',
            'quic_multipath_3paths',
            '',
            {},
            'topology')

        self.assertIsNotNone(top_config)

        topology = MeshTopology(str(repo_root / 'test'), top_config, False)
        topology.load_all_mats(top_config.json_description)
        adjacency = topology.get_matrix(MatrixType.ADJACENCY_MATRIX)

        def count_simple_paths(graph, src, dst, visited):
            """Count all simple paths between two nodes via depth-first search."""
            if src == dst:
                return 1
            visited.add(src)
            total = 0
            for neighbor, connected in enumerate(graph[src]):
                if connected and neighbor not in visited:
                    total += count_simple_paths(graph, neighbor, dst, visited)
            visited.remove(src)
            return total

        self.assertEqual(count_simple_paths(adjacency, 0, 4, set()), 3)

    def test_h0h1_multi_homing_mesh_path_description_loads_sweep(self):
        repo_root = self.find_repo_root()
        top_config = IConfig.load_config_reference(
            str(repo_root / 'test'),
            'predefined.topology.yaml',
            'h0h1-multi-homing',
            '',
            {},
            'topology')

        self.assertIsNotNone(top_config)
        self.assertEqual(top_config.topology_type, 'mesh')

        topology = MultiHomingTopology(str(repo_root / 'test'), top_config)
        generated_topologies = list(topology)

        self.assertEqual(
            len(generated_topologies),
            self.expected_path_description_count(top_config.path_description))
        first_topology = generated_topologies[0]
        self.assertEqual(
            first_topology.get_matrix(MatrixType.ADJACENCY_MATRIX),
            [
                [0, 1],
                [1, 0],
            ])
        self.assertEqual(
            first_topology.get_matrix(MatrixType.BW_MATRIX),
            [
                [0, 100],
                [100, 0],
            ])
        self.assertEqual(
            first_topology.get_matrix(MatrixType.LATENCY_MATRIX),
            [
                [0, 100],
                [100, 0],
            ])
        self.assertEqual(
            first_topology.get_matrix(MatrixType.LOSS_MATRIX),
            [
                [0, 0],
                [1, 0],
            ])
        self.assertEqual(
            first_topology.get_matrix(MatrixType.JITTER_MATRIX),
            [
                [0, 0],
                [0, 0],
            ])

    def test_load_topology_accepts_mesh_path_description(self):
        repo_root = self.find_repo_root()
        test = Test({
            "topology": {
                "config_file": "predefined.topology.yaml",
                "config_name": "h0h1-multi-homing",
            }
        }, "h0h1-multi-homing")

        topology = test.load_topology(str(repo_root / 'test'))

        self.assertIsInstance(topology, MultiHomingTopology)
        self.assertEqual(
            len(list(topology)),
            self.expected_path_description_count(
                topology.top_config.path_description))


class TestTestClass(unittest.TestCase):

    def setUp(self):
        self.test_yaml_active = {
            "if": True,
            "topology": {
                "topology_type": "linear",
                "name": "test_topology"
            }
        }
        self.test_yaml_inactive = {
            "if": False,
            "topology": {
                "topology_type": "linear",
                "name": "test_topology"
            }
        }
        self.test_yaml_no_if = {
            "topology": {
                "topology_type": "linear",
                "name": "test_topology"
            }
        }
        self.test_yaml_no_topology = {
            "if": True
        }

    def test_yaml_method(self):
        test_instance = Test(self.test_yaml_active, "test1")
        self.assertEqual(test_instance.yaml(), self.test_yaml_active)

    def test_is_active(self):
        test_instance_active = Test(self.test_yaml_active, "test1")
        test_instance_inactive = Test(self.test_yaml_inactive, "test2")
        test_instance_no_if = Test(self.test_yaml_no_if, "test3")
        test_instance_none = Test({}, "test4")

        self.assertTrue(test_instance_active.is_active())
        self.assertFalse(test_instance_inactive.is_active())
        self.assertTrue(test_instance_no_if.is_active())
        self.assertFalse(test_instance_none.is_active())

    @patch('src.core.config.IConfig.load_yaml_config')
    def test_load_topology(self, mock_load_yaml_config):
        mock_load_yaml_config.return_value = TopologyConfig(
            topology_type=TopologyType.linear, name="test_topology", nodes=5)

        test_instance = Test(self.test_yaml_active, "test1")
        result = test_instance.load_topology("/fake/path")
        # no 'topology' in file
        self.assertIsNone(result)
        mock_load_yaml_config.assert_called_once_with(
            "/fake/path", self.test_yaml_active["topology"], 'topology')

    @patch('src.core.config.IConfig.load_yaml_config')
    def test_load_topology_no_topology(self, mock_load_yaml_config):
        test_instance = Test(self.test_yaml_no_topology, "test1")
        result = test_instance.load_topology("/fake/path")

        self.assertIsNone(result)
        mock_load_yaml_config.assert_not_called()

    @patch('src.core.config.IConfig.load_yaml_config')
    def test_load_topology_invalid_topology(self, mock_load_yaml_config):
        mock_load_yaml_config.return_value = None

        test_instance = Test(self.test_yaml_active, "test1")
        result = test_instance.load_topology("/fake/path")

        self.assertIsNone(result)
        mock_load_yaml_config.assert_called_once_with(
            "/fake/path", self.test_yaml_active["topology"], 'topology')

    @patch('src.core.config.IConfig.load_yaml_config')
    def test_load_topology_unsupported_type(self, mock_load_yaml_config):
        mock_load_yaml_config.return_value = TopologyConfig(
            topology_type=TopologyType.butterfly, name="test_topology", nodes=5)

        test_instance = Test(self.test_yaml_active, "test1")
        result = test_instance.load_topology("/fake/path")

        self.assertIsNone(result)
        mock_load_yaml_config.assert_called_once_with(
            "/fake/path", self.test_yaml_active["topology"], 'topology')


if __name__ == '__main__':
    unittest.main()
