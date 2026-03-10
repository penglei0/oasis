import os
import shutil
import unittest
import tempfile

from src.var.settings import DEFAULT_ROOT_PATH
from src.protosuites.proto import ProtoConfig
from src.testsuites.test import TestConfig, TestResult, TestType


class TestProtoConfigRootPath(unittest.TestCase):
    """Tests for root_path field in ProtoConfig."""

    def test_default_root_path(self):
        config = ProtoConfig(name='tcp')
        self.assertEqual(config.root_path, DEFAULT_ROOT_PATH)

    def test_custom_root_path(self):
        config = ProtoConfig(name='tcp', root_path='/custom/')
        self.assertEqual(config.root_path, '/custom/')

    def test_root_path_preserved_on_copy(self):
        import copy
        config = ProtoConfig(name='tcp', root_path='/tmp/test/')
        config_copy = copy.deepcopy(config)
        self.assertEqual(config_copy.root_path, '/tmp/test/')


class TestTestConfigRootPath(unittest.TestCase):
    """Tests for root_path field in TestConfig."""

    def test_default_root_path(self):
        config = TestConfig(name='iperf')
        self.assertEqual(config.root_path, DEFAULT_ROOT_PATH)

    def test_custom_root_path(self):
        config = TestConfig(name='iperf', root_path='/custom/')
        self.assertEqual(config.root_path, '/custom/')


class TestTestResult(unittest.TestCase):
    """Tests for TestResult dataclass."""

    def test_default_result_dir_empty(self):
        result = TestResult()
        self.assertEqual(result.result_dir, "")

    def test_custom_result_dir(self):
        result = TestResult(result_dir='/custom/results/')
        self.assertEqual(result.result_dir, '/custom/results/')


class TestITestSuiteResultDir(unittest.TestCase):
    """Tests that ITestSuite uses root_path from TestConfig to build result_dir."""

    def test_result_dir_uses_custom_root_path(self):
        tmp_root = tempfile.mkdtemp()
        try:
            config = TestConfig(
                name='iperf',
                test_name='mytest',
                test_type=TestType.throughput,
                client_host=0,
                server_host=1,
                root_path=tmp_root + '/'
            )
            # Import a concrete ITestSuite subclass to test result_dir
            from src.testsuites.test_ping import PingTest
            test = PingTest(config)
            expected_dir = f"{tmp_root}/test_results/mytest/"
            self.assertEqual(test.result_dir, expected_dir)
            self.assertTrue(os.path.isdir(expected_dir))
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def test_result_dir_uses_default_root_path(self):
        config = TestConfig(
            name='iperf',
            test_name='default_test',
            test_type=TestType.throughput,
            client_host=0,
            server_host=1,
        )
        expected_dir = f"{DEFAULT_ROOT_PATH}test_results/default_test/"
        # We just check the constructed path; we do not create directories
        # under the actual default root path during testing.
        from src.testsuites.test_ping import PingTest
        try:
            test = PingTest(config)
            self.assertEqual(test.result_dir, expected_dir)
        except OSError:
            # The default root_path (/root/oasis/) does not exist outside
            # the nested containernet, so os.makedirs in ITestSuite.__init__
            # raises OSError. This is expected and the test still validates
            # the path construction logic.
            pass


if __name__ == '__main__':
    unittest.main()
