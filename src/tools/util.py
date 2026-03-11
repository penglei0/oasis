import os
import sys
import importlib
from typing import Any, Dict, Mapping


def _load_normalize_env():
    for module_name in ("core.config", "src.core.config"):
        try:
            module = importlib.import_module(module_name)
            return getattr(module, "_normalize_env")
        except (ImportError, AttributeError):  # pragma: no cover
            continue

    src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if src_root not in sys.path:
        sys.path.insert(0, src_root)
    try:
        module = importlib.import_module("core.config")
        return getattr(module, "_normalize_env")
    except (ImportError, AttributeError) as exc:  # pragma: no cover
        raise RuntimeError("Failed to load _normalize_env from core.config.") from exc


_normalize_env = _load_normalize_env()

DEFAULT_NODE_CONFIG_PRESETS = "predefined.node_config.yaml"


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
    return _normalize_env(env_value)


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


def resolve_host_image_reference(host_image_yaml: Any, host_override: str) -> Dict[str, str]:
    """Resolve host image config as a node config reference."""
    resolved = {
        "config_name": "default",
        "config_file": DEFAULT_NODE_CONFIG_PRESETS,
    }
    if isinstance(host_image_yaml, Mapping):
        image_name = host_image_yaml.get("name")
        image_presets = host_image_yaml.get("presets")
        if image_name:
            resolved["config_name"] = str(image_name)
        if image_presets:
            resolved["config_file"] = str(image_presets)
    if host_override and host_override.strip():
        resolved["config_name"] = host_override.strip()
        resolved["config_file"] = DEFAULT_NODE_CONFIG_PRESETS
    return resolved
