import unittest
from src.tools.util import is_same_path
from src.tools.util import is_base_path
from src.tools.util import str_to_mbps
from src.tools.util import parse_test_file_name
from src.tools.util import normalize_env_map
from src.tools.util import merge_env_values
from src.tools.util import resolve_node_config_reference
from src.tools.util import resolve_node_image
from src.tools.util import resolve_host_image_reference


class TestIsSamePath(unittest.TestCase):

    def test_is_same_path_identical_paths(self):
        self.assertTrue(is_same_path(
            '/home/user/file.txt', '/home/user/file.txt'))

    def test_is_same_path_different_paths(self):
        self.assertFalse(is_same_path(
            '/home/user/file1.txt', '/home/user/file2.txt'))

    def test_is_same_path_with_double_slashes(self):
        self.assertTrue(is_same_path(
            '/home//user//file.txt', '/home/user/file.txt'))

    def test_is_same_path_with_trailing_slash(self):
        self.assertTrue(is_same_path(
            '/home/user/file.txt/', '/home/user/file.txt'))

    def test_is_same_path_with_mixed_slashes(self):
        self.assertTrue(is_same_path(
            '/home/user//file.txt/', '/home//user/file.txt'))


class TestIsSameBase(unittest.TestCase):

    def test_is_base_path_base_path(self):
        self.assertTrue(is_base_path(
            '/home/user', '/home/user/file.txt'))

    def test_is_base_path_not_base_path(self):
        self.assertFalse(is_base_path(
            '/home/user/docs', '/home/user/file.txt'))

    def test_is_base_path_identical_paths(self):
        self.assertTrue(is_base_path(
            '/home/user', '/home/user'))

    def test_is_base_path_with_double_slashes(self):
        self.assertTrue(is_base_path(
            '/home//user', '/home/user/file.txt'))

    def test_is_base_path_with_trailing_slash(self):
        self.assertTrue(is_base_path(
            '/home/user/', '/home/user/file.txt'))

    def test_is_base_path_with_mixed_slashes(self):
        self.assertTrue(is_base_path(
            '/home/user//', '/home//user/file.txt'))


class TestStrToMbps(unittest.TestCase):

    def test_str_to_mbps_kilobits(self):
        self.assertEqual(str_to_mbps(1000, "K"), 1.00)

    def test_str_to_mbps_megabits(self):
        self.assertEqual(str_to_mbps(1, "M"), 1.00)

    def test_str_to_mbps_gigabits(self):
        self.assertEqual(str_to_mbps(1, "G"), 1000.00)

    def test_str_to_mbps_no_unit(self):
        self.assertEqual(str_to_mbps(1000000, ""), 1.00)

    def test_str_to_mbps_invalid_unit(self):
        self.assertEqual(str_to_mbps(1000, "X"), 0.00)

    def test_parse_test_file_name_with_test_name(self):
        self.assertEqual(parse_test_file_name(
            'test.yaml:test1'), ('test.yaml', 'test1'))

    def test_parse_test_file_name_without_test_name(self):
        self.assertEqual(parse_test_file_name(
            'test.yaml'), ('test.yaml', None))

    def test_parse_test_file_name_with_multiple_colons(self):
        self.assertEqual(parse_test_file_name(
            'test.yaml:test1:test2'), (None, None))

    def test_parse_test_file_name_empty_string(self):
        self.assertEqual(parse_test_file_name(''), (None, None))

    def test_parse_test_file_name_only_colon(self):
        self.assertEqual(parse_test_file_name(':'), (None, None))

    def test_resolve_node_config_reference_without_override(self):
        node_config = {
            'config_name': 'default',
            'config_file': 'predefined.node_config.yaml'
        }
        self.assertEqual(resolve_node_config_reference(node_config, ''),
                         node_config)

    def test_resolve_node_config_reference_with_override(self):
        node_config = {
            'config_name': 'default',
            'config_file': 'predefined.node_config.yaml'
        }
        self.assertEqual(
            resolve_node_config_reference(node_config, 'ubuntu-24.04'),
            {
                'config_name': 'ubuntu-24.04',
                'config_file': 'predefined.node_config.yaml'
            })

    def test_normalize_env_map_from_list(self):
        envs = [{"A": "1"}, {"B": 2}]
        self.assertEqual(normalize_env_map(envs), {"A": "1", "B": "2"})

    def test_merge_env_values_node_takes_precedence(self):
        host_env = [{"A": "1"}, {"B": "2"}]
        node_env = {"B": "22", "C": "3"}
        self.assertEqual(merge_env_values(host_env, node_env),
                         {"A": "1", "B": "22", "C": "3"})

    def test_resolve_node_image_with_override(self):
        self.assertEqual(resolve_node_image("ubuntu-generic:22.04",
                                            "ubuntu-generic:24.04"),
                         "ubuntu-generic:24.04")

    def test_resolve_node_image_without_override(self):
        self.assertEqual(resolve_node_image("ubuntu-generic:22.04", " "),
                         "ubuntu-generic:22.04")

    def test_resolve_host_image_reference_from_yaml(self):
        self.assertEqual(
            resolve_host_image_reference(
                {"name": "ubuntu-24.04", "presets": "predefined.node_config.yaml"},
                "",
            ),
            {"config_name": "ubuntu-24.04", "config_file": "predefined.node_config.yaml"},
        )

    def test_resolve_host_image_reference_cli_override(self):
        self.assertEqual(
            resolve_host_image_reference(
                {"name": "ubuntu-24.04", "presets": "custom.yaml"},
                "default",
            ),
            {"config_name": "default", "config_file": "predefined.node_config.yaml"},
        )


if __name__ == '__main__':
    unittest.main()
