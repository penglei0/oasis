"""
TestExecutionService encapsulates the orchestration workflow
that was previously embedded in run_test.py's __main__ block.

It resolves configuration, creates network managers, loads tests,
and drives TestRunner through the full lifecycle.  Both the CLI
adapter (run_test.py) and any future API adapter can call this
service without duplicating orchestration logic.
"""
# pylint: disable=import-outside-toplevel
import logging
import os

try:
    from var.settings import OasisSettings
except ImportError:
    from src.var.settings import OasisSettings


def resolve_config_path(original_yaml_config_path, original_oasis_path, settings):
    """Determine the mapped config path for use inside nested containernet."""
    try:
        from tools.util import is_same_path
    except ImportError:
        from src.tools.util import is_same_path

    if is_same_path(original_yaml_config_path, f"{original_oasis_path}/test/"):
        logging.info("No config path mapping is needed.")
        return f'{settings.root_path}test/'
    logging.info(
        "Oasis YAML config files `%s` mapped to `%s`.",
        original_yaml_config_path, f'{settings.root_path}user/')
    return f'{settings.root_path}user/'


class TestExecutionService:
    """Reusable service that orchestrates end-to-end test execution.

    All heavy-weight dependencies (network factory, test loader,
    runner class) are injected through the constructor so the service
    can be unit-tested without importing mininet or other infrastructure.
    When the caller omits them, the production defaults are resolved
    lazily at first use.
    """

    def __init__(self,
                 nested_yaml_test_file_path,
                 original_oasis_path,
                 settings=None,
                 host_override="",
                 halt=False,
                 is_using_testbed=False,
                 network_mgr_factory=None,
                 load_tests_fn=None,
                 runner_cls=None):
        """Initialise the service with paths, settings and optional DI overrides.

        Parameters
        ----------
        nested_yaml_test_file_path : str
            Absolute path to the test YAML file **inside** the nested
            containernet environment (e.g. ``/root/oasis/test/my-test.yaml``).
            ``config_path`` is derived automatically as its parent directory.
        original_oasis_path : str
            The host-side Oasis workspace directory that is bind-mounted
            into the containernet container (e.g. ``/home/user/oasis``).
        settings : OasisSettings, optional
            Runtime settings; defaults to ``OasisSettings()``.
        host_override : str, optional
            Docker image override for the host node (passed via ``--node``).
        halt : bool, optional
            When *True* the network manager pauses after test execution.
        is_using_testbed : bool, optional
            Select testbed mode instead of containernet mode.
        network_mgr_factory : callable, optional
            ``(NetworkType) -> NetworkManager``; production default is
            ``core.network_factory.create_network_mgr``.
        load_tests_fn : callable, optional
            ``(yaml_path, selected_test) -> list[Test]``; production default
            is ``core.config.load_all_tests``.
        runner_cls : type, optional
            Class used to run individual tests; production default is
            ``core.runner.TestRunner``.
        """
        self.nested_yaml_test_file_path = nested_yaml_test_file_path
        self.original_oasis_path = original_oasis_path
        self.settings = settings or OasisSettings()
        self.host_override = host_override
        self.halt = halt
        self.is_using_testbed = is_using_testbed
        self.network_manager = None
        self.hosts_config = None
        self._network_mgr_factory = network_mgr_factory
        self._load_tests_fn = load_tests_fn
        self._runner_cls = runner_cls
        # Derived: directory containing the test YAML (used as config base).
        self.config_path = os.path.dirname(self.nested_yaml_test_file_path) + os.sep

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(self, load_hosts_config_fn, load_testbed_config_fn=None):
        """Create the network manager and load host/testbed config.

        *load_hosts_config_fn* and *load_testbed_config_fn* are callables
        that return the appropriate configuration objects.  Accepting them
        as parameters keeps infrastructure concerns (YAML loading, Docker
        setup) outside this service, which simplifies unit testing.
        """
        factory = self._resolve_network_mgr_factory()

        if not self.is_using_testbed:
            logging.info("Running tests on containernet.")
            self.network_manager = factory(self._net_type_containernet())
            self.hosts_config = load_hosts_config_fn(
                self.nested_yaml_test_file_path,
                self.original_oasis_path,
                self.settings,
                self.host_override,
            )
        else:
            logging.info("Running tests on testbed.")
            self.network_manager = factory(self._net_type_testbed())
            if load_testbed_config_fn is None:
                logging.error(
                    "load_testbed_config_fn must be provided when is_using_testbed is True.")
                return False
            self.hosts_config = load_testbed_config_fn(
                'testbed_nhop_shenzhen', self.config_path)
            if self.hosts_config is None:
                logging.error(
                    "Failed to load testbed hosts configuration; hosts_config is None.")
                return False

        if self.network_manager is None:
            logging.error("Failed to load the appropriate network manager.")
            return False

        if self.halt:
            logging.info(
                "Halt mode is enabled. The script will halt after the test is done.")
            self.network_manager.enable_halt()

        return True

    def run(self, selected_test="all"):
        """Load tests from the YAML file and execute them.

        Returns ``True`` when every test passes, ``False`` otherwise.
        ``prepare()`` **must** be called before ``run()``.
        """
        if self.network_manager is None:
            logging.error(
                "run() called before prepare(). "
                "Call prepare() first to initialise the network manager.")
            return False
        load_fn = self._resolve_load_tests_fn()
        loaded_tests = load_fn(self.nested_yaml_test_file_path, selected_test)
        if not loaded_tests:
            logging.error("No test case was found.")
            return False

        for test in loaded_tests:
            success = self._run_single_test(test)
            if not success:
                return False

        self._write_success_marker()
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_single_test(self, test):
        loaded_topologies = test.load_topology(self.config_path)
        if not loaded_topologies:
            logging.error(
                "Failed to load a topology for test %s.", test.name)
            return False

        runner_cls = self._resolve_runner_cls()

        for index, cur_top_ins in enumerate(loaded_topologies):
            test_runner = runner_cls(
                test.yaml(), self.config_path,
                self.network_manager, self.settings.root_path)
            test_runner.init(self.hosts_config, cur_top_ins)
            if not test_runner.is_ready():
                test_runner.handle_failure()
                return False
            if test_runner.setup_tests() is False:
                test_runner.handle_failure()
                return False
            if test_runner.execute_tests() is False:
                test_runner.handle_failure()
                return False
            if test_runner.handle_test_results(index) is False:
                test_runner.handle_failure()
                return False
        return True

    def _write_success_marker(self):
        results_dir = self.settings.test_results_path
        os.makedirs(results_dir, exist_ok=True)
        marker = os.path.join(results_dir, "test.success")
        with open(marker, 'w', encoding='utf-8') as f_success:
            f_success.write("test.success")

    def _resolve_network_mgr_factory(self):
        if self._network_mgr_factory is not None:
            return self._network_mgr_factory
        from core.network_factory import create_network_mgr
        return create_network_mgr

    def _resolve_load_tests_fn(self):
        if self._load_tests_fn is not None:
            return self._load_tests_fn
        from core.config import load_all_tests
        return load_all_tests

    def _resolve_runner_cls(self):
        if self._runner_cls is not None:
            return self._runner_cls
        from core.runner import TestRunner
        return TestRunner

    @staticmethod
    def _net_type_containernet():
        from interfaces.network_mgr import NetworkType
        return NetworkType.containernet

    @staticmethod
    def _net_type_testbed():
        from interfaces.network_mgr import NetworkType
        return NetworkType.testbed
