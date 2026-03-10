import os
from typing import Any, Dict, Mapping


def is_same_path(file_path1, file_path2):
    # check if file_path1 is the same as file_path2
    # return True if they are the same, otherwise False
    # file_path1 may contains `//`, remove them first
    file_path1 = os.path.normpath(file_path1)
    file_path2 = os.path.normpath(file_path2)
    if file_path1.endswith('/'):
        file_path1 = file_path1[:-1]
    if file_path2.endswith('/'):
        file_path2 = file_path2[:-1]
    return file_path1 == file_path2


def is_base_path(file_path1, file_path2):
    """
    check whether `file_path1` is the base path of `file_path2`;
    for example: /root is base path of /root/a/b/c
    """
    file_path1 = os.path.normpath(file_path1)
    file_path2 = os.path.normpath(file_path2)
    if file_path1.endswith('/'):
        file_path1 = file_path1[:-1]
    if file_path2.endswith('/'):
        file_path2 = file_path2[:-1]
    return file_path2.startswith(file_path1)


def str_to_mbps(x, unit):
    ret = 0.00
    if unit == "K":
        ret = float(x) / 1000
    elif unit == "M":
        ret = float(x)
    elif unit == "G":
        ret = float(x) * 1000
    elif unit == "":
        ret = float(x) / 1000000
    return round(ret, 2)


def parse_test_file_name(test_file_path_string):
    """
    Parse the test YAML file string to extract the file path and test name.
    for example: `test.yaml:test1` will be parsed to `test.yaml` and `test1`

    return value: test_file_path, test_name
    """
    if not test_file_path_string or test_file_path_string == ':':
        return None, None

    temp_list = test_file_path_string.split(":")
    if len(temp_list) not in [1, 2]:
        return None, None
    if len(temp_list) == 2:
        return temp_list[0], temp_list[1]
    return test_file_path_string, None


def resolve_node_config_reference(node_config_yaml, override_name):
    """Override the node config reference when requested."""
    if not override_name or not isinstance(node_config_yaml, dict):
        return node_config_yaml
    resolved_config = dict(node_config_yaml)
    resolved_config["config_name"] = override_name
    return resolved_config


def normalize_env_map(env_value: Any) -> Dict[str, str]:
    """Normalize env entries from mapping/list formats into a flat dict."""
    if env_value is None:
        return {}
    if isinstance(env_value, Mapping):
        return {str(k): str(v) for k, v in env_value.items()}
    if isinstance(env_value, list):
        normalized_env: Dict[str, str] = {}
        for env_item in env_value:
            if isinstance(env_item, Mapping):
                for key, value in env_item.items():
                    normalized_env[str(key)] = str(value)
        return normalized_env
    return {}


def merge_env_values(host_env: Any, node_env: Any) -> Dict[str, str]:
    """Merge host-wide env and node env with node values taking precedence."""
    merged_env = normalize_env_map(host_env)
    merged_env.update(normalize_env_map(node_env))
    return merged_env


def resolve_node_image(default_image: str, override_image: str) -> str:
    """Use override image when provided, otherwise keep default image."""
    if override_image and override_image.strip():
        return override_image.strip()
    return default_image
