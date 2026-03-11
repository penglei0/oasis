import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.var.settings import OasisSettings
from src.core.test_execution_service import TestExecutionService, resolve_config_path


class TestTestExecutionServiceInit(unittest.TestCase):
    """Test that the service stores all constructor arguments."""

    def test_default_settings(self):
        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
        )
        self.assertEqual(svc.nested_yaml_test_file_path, "/cfg/test.yaml")
        self.assertEqual(svc.original_oasis_path, "/ws")
        self.assertEqual(svc.config_path, "/cfg/")
        self.assertEqual(svc.host_override, "")
        self.assertFalse(svc.halt)
        self.assertFalse(svc.is_using_testbed)

    def test_custom_settings(self):
        settings = OasisSettings(root_path="/custom/")
        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            settings=settings,
            host_override="myhost",
            halt=True,
            is_using_testbed=True,
        )
        self.assertEqual(svc.settings.root_path, "/custom/")
        self.assertEqual(svc.host_override, "myhost")
        self.assertTrue(svc.halt)
        self.assertTrue(svc.is_using_testbed)


class TestPrepare(unittest.TestCase):
    """Test TestExecutionService.prepare()."""

    def test_prepare_containernet(self):
        mock_mgr = MagicMock()
        factory = MagicMock(return_value=mock_mgr)
        load_fn = MagicMock(return_value="node_cfg")

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_fn)

        self.assertTrue(result)
        self.assertIs(svc.network_manager, mock_mgr)
        self.assertEqual(svc.hosts_config, "node_cfg")
        factory.assert_called_once()
        load_fn.assert_called_once_with(
            "/cfg/test.yaml", "/ws",
            svc.settings, "",
        )
        mock_mgr.enable_halt.assert_not_called()

    def test_prepare_with_halt(self):
        mock_mgr = MagicMock()
        factory = MagicMock(return_value=mock_mgr)
        load_fn = MagicMock(return_value="node_cfg")

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            halt=True,
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_fn)

        self.assertTrue(result)
        mock_mgr.enable_halt.assert_called_once()

    def test_prepare_returns_false_when_no_manager(self):
        factory = MagicMock(return_value=None)
        load_fn = MagicMock(return_value="node_cfg")

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_fn)

        self.assertFalse(result)

    def test_prepare_testbed(self):
        mock_mgr = MagicMock()
        factory = MagicMock(return_value=mock_mgr)
        load_hosts_fn = MagicMock()
        load_testbed_fn = MagicMock(return_value="testbed_cfg")

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            is_using_testbed=True,
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_hosts_fn, load_testbed_fn)

        self.assertTrue(result)
        load_hosts_fn.assert_not_called()
        load_testbed_fn.assert_called_once_with(
            'testbed_nhop_shenzhen', "/cfg/")
        self.assertEqual(svc.hosts_config, "testbed_cfg")

    def test_prepare_testbed_requires_loader(self):
        factory = MagicMock(return_value=MagicMock())
        load_hosts_fn = MagicMock()

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            is_using_testbed=True,
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_hosts_fn, None)

        self.assertFalse(result)

    def test_prepare_testbed_returns_false_when_config_none(self):
        factory = MagicMock(return_value=MagicMock())
        load_hosts_fn = MagicMock()
        load_testbed_fn = MagicMock(return_value=None)

        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            is_using_testbed=True,
            network_mgr_factory=factory,
        )
        result = svc.prepare(load_hosts_fn, load_testbed_fn)

        self.assertFalse(result)


class TestRun(unittest.TestCase):
    """Test TestExecutionService.run()."""

    def _make_service(self, tmp, load_tests_fn, runner_cls=None):
        settings = OasisSettings(root_path=tmp + '/')
        return TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            settings=settings,
            load_tests_fn=load_tests_fn,
            runner_cls=runner_cls,
        )

    def test_run_returns_false_when_no_tests(self):
        load_fn = MagicMock(return_value=[])
        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
            load_tests_fn=load_fn,
        )
        svc.network_manager = MagicMock()
        result = svc.run("all")
        self.assertFalse(result)

    def test_run_returns_false_without_prepare(self):
        svc = TestExecutionService(
            nested_yaml_test_file_path="/cfg/test.yaml",
            original_oasis_path="/ws",
        )
        result = svc.run("all")
        self.assertFalse(result)

    def test_run_success_writes_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_topology = MagicMock()
            mock_test.load_topology.return_value = [mock_topology]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = True
            mock_runner.execute_tests.return_value = True
            mock_runner.handle_test_results.return_value = True
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertTrue(result)
            marker = os.path.join(tmp, "test_results", "test.success")
            self.assertTrue(os.path.exists(marker))

    def test_run_calls_runner_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_topo = MagicMock()
            mock_test.load_topology.return_value = [mock_topo]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = True
            mock_runner.execute_tests.return_value = True
            mock_runner.handle_test_results.return_value = True
            runner_cls = MagicMock(return_value=mock_runner)

            net_mgr = MagicMock()
            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = net_mgr
            svc.hosts_config = "hosts"

            svc.run("all")

            runner_cls.assert_called_once_with(
                {"name": "t1"}, "/cfg/", net_mgr, tmp + '/')
            mock_runner.init.assert_called_once_with("hosts", mock_topo)
            mock_runner.is_ready.assert_called_once()
            mock_runner.setup_tests.assert_called_once()
            mock_runner.execute_tests.assert_called_once()
            mock_runner.handle_test_results.assert_called_once_with(0)

    def test_run_returns_false_on_setup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_test.load_topology.return_value = [MagicMock()]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = False
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertFalse(result)
            mock_runner.handle_failure.assert_called()

    def test_run_returns_false_on_topology_load_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.load_topology.return_value = None
            load_fn = MagicMock(return_value=[mock_test])

            svc = self._make_service(tmp, load_fn)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertFalse(result)

    def test_run_returns_false_on_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_test.load_topology.return_value = [MagicMock()]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = False
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertFalse(result)
            mock_runner.handle_failure.assert_called()

    def test_run_returns_false_on_execute_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_test.load_topology.return_value = [MagicMock()]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = True
            mock_runner.execute_tests.return_value = False
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertFalse(result)
            mock_runner.handle_failure.assert_called()

    def test_run_returns_false_on_handle_results_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_test.load_topology.return_value = [MagicMock()]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = True
            mock_runner.execute_tests.return_value = True
            mock_runner.handle_test_results.return_value = False
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertFalse(result)
            mock_runner.handle_failure.assert_called()

    def test_run_multiple_topologies(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock_test = MagicMock()
            mock_test.name = "t1"
            mock_test.yaml.return_value = {"name": "t1"}
            mock_test.load_topology.return_value = [MagicMock(), MagicMock()]
            load_fn = MagicMock(return_value=[mock_test])

            mock_runner = MagicMock()
            mock_runner.is_ready.return_value = True
            mock_runner.setup_tests.return_value = True
            mock_runner.execute_tests.return_value = True
            mock_runner.handle_test_results.return_value = True
            runner_cls = MagicMock(return_value=mock_runner)

            svc = self._make_service(tmp, load_fn, runner_cls)
            svc.network_manager = MagicMock()
            result = svc.run("all")

            self.assertTrue(result)
            self.assertEqual(runner_cls.call_count, 2)
            calls = mock_runner.handle_test_results.call_args_list
            self.assertEqual(calls[0].args[0], 0)
            self.assertEqual(calls[1].args[0], 1)


class TestResolveConfigPath(unittest.TestCase):
    """Test the resolve_config_path helper."""

    def test_same_path_returns_test_dir(self):
        settings = OasisSettings(root_path="/root/oasis/")
        result = resolve_config_path("/ws/test/", "/ws", settings)
        self.assertEqual(result, "/root/oasis/test/")

    def test_different_path_returns_user_dir(self):
        settings = OasisSettings(root_path="/root/oasis/")
        result = resolve_config_path("/somewhere/else", "/ws", settings)
        self.assertEqual(result, "/root/oasis/user/")


if __name__ == '__main__':
    unittest.main()
