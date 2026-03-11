import os
import sys
import logging
import platform
import yaml

from mininet.log import setLogLevel

from tools.util import (
    is_base_path,
    merge_env_values,
    parse_test_file_name,
    resolve_host_image_reference,
)
from tools.log_setup import configure_run_logging
from var.settings import OasisSettings
from core.config import (IConfig, NodeConfig)


def containernet_node_config(file_path, host_override: str = "") -> NodeConfig:
    """Load node related configuration from the yaml file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as stream:
            yaml_content = yaml.safe_load(stream)
    except FileNotFoundError:
        logging.error(
            "YAML file '%s' not found.", file_path)
        return NodeConfig(name="", img="")
    except yaml.YAMLError as exc:
        logging.error("Error parsing YAML file: %s", exc)
        return NodeConfig(name="", img="")

    if not yaml_content:
        logging.error("YAML file is empty or could not be parsed.")
        return NodeConfig(name="", img="")

    host_yaml = yaml_content.get("host")
    if not isinstance(host_yaml, dict):
        logging.error("No valid host configuration found. Expected host section in YAML.")
        return NodeConfig(name="", img="")
    if "image" not in host_yaml:
        logging.error(
            "No valid host configuration found. "
            "Expected host.image in YAML.")
        return NodeConfig(name="", img="")
    host_image_yaml = host_yaml.get("image", {})
    node_config_yaml = resolve_host_image_reference(host_image_yaml, host_override)
    node_config_yaml["init_script"] = host_yaml.get("init_script", "")

    merged_env = merge_env_values(
        host_yaml.get("env", {}),
        node_config_yaml.get("env", {}),
    )
    if merged_env:
        node_config_yaml["env"] = merged_env
    config_dir = os.path.dirname(file_path) + os.sep
    loaded_conf = IConfig.load_yaml_config(config_dir,
                                           node_config_yaml, 'node_config')
    if isinstance(loaded_conf, NodeConfig):
        # Ensure the loaded configuration is a NodeConfig
        return loaded_conf
    logging.error("Loaded configuration is not a NodeConfig.")
    return NodeConfig(name="", img="")


def load_containernet_config(yaml_test_file,
                             source_workspace,
                             settings=None,
                             host_override: str = ""):
    if settings is None:
        settings = OasisSettings()
    node_config = containernet_node_config(yaml_test_file, host_override)
    if node_config is None or node_config.name == "":
        logging.error("No containernet node config is available.")
        sys.exit(1)
    # mount the workspace to collect the test results from hosts.
    node_config.vols.append(f'{source_workspace}:{settings.root_path}')
    return node_config


def load_testbed_config(name, yaml_base_path_input):
    absolute_path_of_testbed_config_file = os.path.join(
        yaml_base_path_input + "/", 'testbed/predefined.testbed.yaml')
    if not os.path.exists(f'{absolute_path_of_testbed_config_file}'):
        logging.info("%s does not exist.", absolute_path_of_testbed_config_file)
        return None
    all_testbeds = None
    with open(absolute_path_of_testbed_config_file, 'r', encoding='utf-8') as stream:
        try:
            all_testbeds = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            logging.error(exc)
            return None
    logging.debug("all_testbeds: %s", all_testbeds)
    for testbed in all_testbeds.keys():
        if name == testbed:
            logging.info("found the testbed: %s", all_testbeds[testbed])
            return all_testbeds[testbed]
    logging.error("Testbed %s is not found.", name)
    logging.info("The supported testbeds are: %s",
                 all_testbeds.keys())
    return None


if __name__ == '__main__':
    from core.test_execution_service import (
        TestExecutionService, resolve_config_path)

    to_halt = 'False'
    debug_log = 'False'
    if len(sys.argv) >= 5:
        debug_log = sys.argv[4]
    if len(sys.argv) >= 6:
        to_halt = sys.argv[5]
    selected_host = ""
    if len(sys.argv) >= 7:
        selected_host = sys.argv[6]
    if debug_log == 'True':
        setLogLevel('debug')
    else:
        setLogLevel('warning')
    configure_run_logging(debug_log == 'True', OasisSettings().root_path)
    # @note: there are cases `original_yaml_config_path` is not the subfolder of `original_oasis_path`
    original_yaml_config_path = sys.argv[1]
    original_oasis_path = sys.argv[2]
    logging.info("Platform: %s", platform.platform())
    logging.info("Python version: %s", platform.python_version())
    logging.info("Yaml config path: %s", original_yaml_config_path)
    logging.info("Oasis workspace: %s", original_oasis_path)
    oasis_settings = OasisSettings()
    nested_config_path = resolve_config_path(
        original_yaml_config_path, original_oasis_path, oasis_settings)
    running_in_nested = not is_base_path(os.getcwd(), original_oasis_path)
    if not running_in_nested:
        logging.info("Nested containernet environment is required.")
        sys.exit(1)

    cur_test_file = sys.argv[3]
    cur_selected_test = "all"
    cur_test_file, cur_selected_test = parse_test_file_name(cur_test_file)
    if not cur_test_file:
        logging.info("Invalid test file name.")
        sys.exit(1)
    if not cur_selected_test:
        cur_selected_test = "all"
    nested_yaml_test_file_path = f'{nested_config_path}/{cur_test_file}'
    if not os.path.exists(nested_yaml_test_file_path):
        logging.info("%s does not exist.", nested_yaml_test_file_path)
        sys.exit(1)
    service = TestExecutionService(
        nested_yaml_test_file_path=nested_yaml_test_file_path,
        original_oasis_path=original_oasis_path,
        settings=oasis_settings,
        host_override=selected_host,
        halt=(to_halt == 'True'),
    )
    if not service.prepare(load_containernet_config):
        sys.exit(1)
    if not service.run(cur_selected_test):
        sys.exit(1)
    sys.exit(0)
