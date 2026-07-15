"""Unit tests for ITestSuite refactoring: registry, resolve_receiver, from_tool_dict."""

import os
import shutil
import sys
import tempfile
import threading
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from testsuites.test import (
    TestConfig, TestType, ITestSuite, PROXY_PROTOCOLS,
    decode_subprocess_output,
    register_test_suite, get_test_suite_registry,
    load_test_suite_from_registry, _TEST_SUITE_REGISTRY,
)

# Force registration of all built-in test suites by importing them
from testsuites.test_iperf import IperfTest
from testsuites.test_iperf_bats import IperfBatsTest
from testsuites.test_rtt import RTTTest
from testsuites.test_ping import PingTest
from testsuites.test_scp import ScpTest
from testsuites.test_sshping import SSHPingTest
from testsuites.test_quic_perf import QuicPerfTest
from testsuites.test_regular import RegularTest
from testsuites.test_regular_benchmark import RegularBenchmarkTest

_MP_BENCHMARK_PATH = Path(__file__).resolve().parents[3] / 'src' / 'tools' / 'http_benchmark.py'
_MP_BENCHMARK_SPEC = importlib.util.spec_from_file_location('http_benchmark_under_test', _MP_BENCHMARK_PATH)
mp_benchmark = importlib.util.module_from_spec(_MP_BENCHMARK_SPEC)
sys.modules[_MP_BENCHMARK_SPEC.name] = mp_benchmark
_MP_BENCHMARK_SPEC.loader.exec_module(mp_benchmark)


# ---------------------------------------------------------------------------
# Lightweight stubs for INetwork / IProtoInfo to test resolve_receiver and
# _default_client_server without requiring containernet.
# ---------------------------------------------------------------------------

class _StubHost:
    """Minimal host stub returned by _StubNetwork."""

    def __init__(self, name, ip):
        self._name = name
        self._ip = ip

    def name(self):
        return self._name

    def IP(self):
        return self._ip


class _StubNetwork:
    """Minimal network stub that exposes get_hosts()."""

    def __init__(self, hosts):
        self._hosts = hosts

    def get_hosts(self):
        return self._hosts


class _StubProtoInfo:
    """Minimal IProtoInfo stub."""

    def __init__(self, name='tcp', tun_ips=None, forward_port=0,
                 distributed=True, version='', args=''):
        self._name = name
        self._tun_ips = tun_ips or {}
        self._forward_port = forward_port
        self._distributed = distributed
        self._version = version
        self._args = args

    def get_protocol_name(self):
        return self._name

    def get_tun_ip(self, network, host_id):
        return self._tun_ips.get(host_id, '')

    def get_forward_port(self):
        return self._forward_port

    def is_distributed(self):
        return self._distributed

    def get_protocol_version(self):
        return self._version

    def get_protocol_args(self, network):
        return self._args


# ---------------------------------------------------------------------------
# A concrete dummy ITestSuite subclass for testing the base class helpers
# ---------------------------------------------------------------------------

class _DummyTestSuite(ITestSuite):
    """Concrete no-op subclass used to exercise ITestSuite helpers."""

    def pre_process(self):
        return True

    def post_process(self):
        return True

    def _run_test(self, network, proto_info):
        return True


def _make_dummy(tmp_dir, client_host=0, server_host=1):
    """Helper to build a _DummyTestSuite in a temp directory."""
    config = TestConfig(
        name='dummy',
        test_name='test',
        test_type=TestType.throughput,
        client_host=client_host,
        server_host=server_host,
        root_path=tmp_dir + '/',
    )
    return _DummyTestSuite(config)


# ======================================================================
# Test cases
# ======================================================================

class TestProxyProtocolsConstant(unittest.TestCase):
    """PROXY_PROTOCOLS should contain KCP and QUIC."""

    def test_kcp_in_set(self):
        self.assertIn("KCP", PROXY_PROTOCOLS)

    def test_quic_in_set(self):
        self.assertIn("QUIC", PROXY_PROTOCOLS)

    def test_tcp_not_in_set(self):
        self.assertNotIn("TCP", PROXY_PROTOCOLS)


class TestDecodeSubprocessOutput(unittest.TestCase):
    """decode_subprocess_output should tolerate invalid bytes."""

    def test_invalid_utf8_bytes_are_replaced(self):
        decoded = decode_subprocess_output(
            b'iperf output line\xff\xfe with invalid bytes')
        self.assertEqual(
            decoded, 'iperf output line\ufffd\ufffd with invalid bytes')


class TestDefaultClientServer(unittest.TestCase):
    """_default_client_server should set defaults only when needed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_applied_when_both_none(self):
        suite = _make_dummy(self.tmp, client_host=None, server_host=None)
        hosts = [_StubHost(f'h{i}', f'10.0.0.{i+1}') for i in range(4)]
        network = _StubNetwork(hosts)
        suite._default_client_server(network)
        self.assertEqual(suite.config.client_host, 0)
        self.assertEqual(suite.config.server_host, 3)

    def test_defaults_applied_when_client_none(self):
        """When *either* client or server is None, *both* are defaulted.

        This matches the original if/elif logic in all four test suites that
        contained the inline version of this helper (IperfTest, IperfBatsTest,
        RTTTest, PingTest).
        """
        suite = _make_dummy(self.tmp, client_host=None, server_host=2)
        hosts = [_StubHost(f'h{i}', f'10.0.0.{i+1}') for i in range(4)]
        network = _StubNetwork(hosts)
        suite._default_client_server(network)
        self.assertEqual(suite.config.client_host, 0)
        self.assertEqual(suite.config.server_host, 3)

    def test_no_change_when_both_set(self):
        suite = _make_dummy(self.tmp, client_host=1, server_host=2)
        hosts = [_StubHost(f'h{i}', f'10.0.0.{i+1}') for i in range(4)]
        network = _StubNetwork(hosts)
        suite._default_client_server(network)
        self.assertEqual(suite.config.client_host, 1)
        self.assertEqual(suite.config.server_host, 2)


class TestResolveReceiver(unittest.TestCase):
    """resolve_receiver should route to client tun for proxy, server tun otherwise."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_network(self, num_hosts=2):
        hosts = [_StubHost(f'h{i}', f'10.0.0.{i+1}') for i in range(num_hosts)]
        return _StubNetwork(hosts)

    def test_direct_protocol_uses_server_ip(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='tcp')
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '10.0.0.2')
        self.assertEqual(port, 0)

    def test_kcp_proxy_uses_client_tun(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='kcp', tun_ips={0: '192.168.1.1'}, forward_port=10100)
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '192.168.1.1')
        self.assertEqual(port, 10100)

    def test_kcp_proxy_fallback_to_client_ip(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='kcp', tun_ips={})
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '10.0.0.1')

    def test_quic_proxy_uses_client_tun(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='quic', tun_ips={0: '192.168.2.1'}, forward_port=443)
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '192.168.2.1')
        self.assertEqual(port, 443)

    def test_btp_tunnel_uses_server_tun(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='btp', tun_ips={1: '1.0.0.2'})
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '1.0.0.2')
        self.assertEqual(port, 0)

    def test_tunnel_fallback_to_server_ip(self):
        suite = _make_dummy(self.tmp, client_host=0, server_host=1)
        proto = _StubProtoInfo(name='btp', tun_ips={})
        network = self._make_network()
        ip, port = suite.resolve_receiver(network, proto)
        self.assertEqual(ip, '10.0.0.2')


class TestRegistry(unittest.TestCase):
    """Test suite registry operations."""

    def test_builtin_tools_registered(self):
        reg = get_test_suite_registry()
        self.assertIn('iperf', reg)
        self.assertIn('bats_iperf', reg)
        self.assertIn('rtt', reg)
        self.assertIn('ping', reg)
        self.assertIn('scp', reg)
        self.assertIn('quic_perf', reg)

    def test_iperf_uses_contains_match(self):
        reg = get_test_suite_registry()
        self.assertEqual(reg['iperf']['match'], 'contains')

    def test_exact_match_entries(self):
        reg = get_test_suite_registry()
        for name in ('bats_iperf', 'rtt', 'ping', 'scp', 'quic_perf'):
            self.assertEqual(reg[name]['match'], 'exact', f'{name} should be exact match')

    def test_registry_classes(self):
        reg = get_test_suite_registry()
        self.assertEqual(reg['iperf']['class'], IperfTest)
        self.assertEqual(reg['bats_iperf']['class'], IperfBatsTest)
        self.assertEqual(reg['rtt']['class'], RTTTest)
        self.assertEqual(reg['ping']['class'], PingTest)
        self.assertEqual(reg['scp']['class'], ScpTest)
        self.assertEqual(reg['quic_perf']['class'], QuicPerfTest)


class TestLoadTestSuiteFromRegistry(unittest.TestCase):
    """load_test_suite_from_registry should dispatch to the correct class."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root_path = self.tmp + '/'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exact_match_bats_iperf(self):
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfBatsTest)

    def test_exact_match_ping(self):
        tool = {'name': 'ping', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, PingTest)

    def test_exact_match_rtt(self):
        tool = {'name': 'rtt', 'client_host': 0, 'server_host': 1,
                'packet_count': 100, 'packet_size': 512}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RTTTest)

    def test_exact_match_scp(self):
        tool = {'name': 'scp', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, ScpTest)

    def test_contains_match_iperf(self):
        tool = {'name': 'iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfTest)

    def test_contains_match_iperf3(self):
        tool = {'name': 'iperf3', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfTest)

    def test_exact_match_quic_perf(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, QuicPerfTest)

    def test_bats_iperf_exact_beats_iperf_contains(self):
        """bats_iperf should match the exact entry, not the 'contains' iperf entry."""
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfBatsTest)

    def test_unknown_tool_returns_none(self):
        tool = {'name': 'unknown_tool_xyz', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsNone(suite)

    def test_missing_from_tool_dict_logs_warning(self):
        """Registered class without from_tool_dict() should log a warning."""
        # Register a dummy class without from_tool_dict
        class _IncompleteTest(ITestSuite):
            def pre_process(self):
                return True
            def post_process(self):
                return True
            def _run_test(self, network, proto_info):
                return True

        _TEST_SUITE_REGISTRY['_incomplete'] = {
            'class': _IncompleteTest,
            'match': 'exact',
            'test_type': None,
        }
        try:
            tool = {'name': '_incomplete', 'client_host': 0, 'server_host': 1}
            with self.assertLogs(level='WARNING') as cm:
                suite = load_test_suite_from_registry(
                    tool, 'test1', self.root_path)
            self.assertIsNone(suite)
            self.assertTrue(any(
                '_IncompleteTest' in msg and 'from_tool_dict' in msg
                for msg in cm.output))
        finally:
            del _TEST_SUITE_REGISTRY['_incomplete']


class TestFromToolDict(unittest.TestCase):
    """from_tool_dict() should correctly populate TestConfig."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root_path = self.tmp + '/'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_iperf_from_tool_dict(self):
        tool = {'name': 'iperf', 'client_host': 0, 'server_host': 1,
                'interval': 2.0, 'interval_num': 20, 'parallel': 4,
                'packet_type': 'udp', 'bitrate': 50}
        suite = IperfTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfTest)
        self.assertEqual(suite.config.test_type, TestType.throughput)
        self.assertEqual(suite.config.parallel, 4)
        self.assertEqual(suite.config.packet_type, 'udp')
        self.assertEqual(suite.config.bitrate, 50)
        self.assertEqual(suite.config.interval, 2.0)
        self.assertEqual(suite.config.interval_num, 20)

    def test_iperf_from_tool_dict_defaults(self):
        tool = {'name': 'iperf', 'client_host': 0, 'server_host': 1}
        suite = IperfTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertEqual(suite.config.parallel, 1)
        self.assertEqual(suite.config.packet_type, 'tcp')
        self.assertEqual(suite.config.bitrate, 0)

    @patch('testsuites.test_iperf.time.sleep', return_value=None)
    def test_iperf_run_tolerates_non_utf8_output(self, _sleep):
        tool = {'name': 'iperf', 'client_host': 0, 'server_host': 1}
        suite = IperfTest.from_tool_dict(tool, 'test1', self.root_path)
        suite.result.record = os.path.join(self.root_path, 'iperf.log')

        client = MagicMock()
        client.name.return_value = 'h0'
        client.popen.return_value.stdout.read.return_value = (
            b'iperf output line\xff\xfe with invalid bytes')
        server = MagicMock()
        server.name.return_value = 'h1'

        with self.assertLogs(level='INFO') as cm:
            self.assertTrue(suite._run_iperf(client, server, 5201, '10.0.0.2'))
        self.assertIn('iperf3 -c 10.0.0.2 -p 5201', client.popen.call_args.args[0])
        self.assertTrue(any('iperf output line\ufffd\ufffd with invalid bytes' in msg
                            for msg in cm.output))
        client.cmd.assert_called_once_with('pkill -9 -f iperf3')
        server.cmd.assert_any_call('iperf3 -s -p 5201 -i 1 -V --forceflush'
                                   f' --logfile {suite.result.record} &')
        server.cmd.assert_any_call('pkill -9 -f iperf3')

    @patch('testsuites.test_iperf_bats.time.sleep', return_value=None)
    def test_bats_iperf_run_tolerates_non_utf8_output(self, _sleep):
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 1}
        suite = IperfBatsTest.from_tool_dict(tool, 'test1', self.root_path)
        suite.result.record = os.path.join(self.root_path, 'bats_iperf.log')

        client = MagicMock()
        client.name.return_value = 'h0'
        client.popen.return_value.stdout.read.return_value = (
            b'bats iperf output\xff\xfe')
        server = MagicMock()
        server.name.return_value = 'h1'
        server.IP.return_value = '10.0.0.2'
        server.getIntfs.return_value = ['eth0']

        with self.assertLogs(level='INFO') as cm:
            self.assertTrue(
                suite._run_iperf(client, server, '-m 0', 'btp'))
        self.assertIn('bats_iperf -c 10.0.0.2 -m 0 -p 5201',
                      client.popen.call_args.args[0])
        self.assertTrue(any('bats iperf output\ufffd\ufffd' in msg
                            for msg in cm.output))
        client.cmd.assert_called_once_with('pkill -9 -f bats_iperf')
        server.cmd.assert_any_call('pkill -9 -f bats_iperf')

    def test_bats_iperf_from_tool_dict(self):
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 3}
        suite = IperfBatsTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfBatsTest)
        self.assertEqual(suite.config.test_type, TestType.throughput)
        self.assertEqual(suite.config.server_host, 3)

    def test_rtt_from_tool_dict(self):
        tool = {'name': 'rtt', 'client_host': 0, 'server_host': 1,
                'packet_count': 2000, 'packet_size': 512}
        suite = RTTTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RTTTest)
        self.assertEqual(suite.config.test_type, TestType.rtt)
        self.assertEqual(suite.config.packet_count, 2000)
        self.assertEqual(suite.config.packet_size, 512)

    def test_ping_from_tool_dict(self):
        tool = {'name': 'ping', 'client_host': 0, 'server_host': 1}
        suite = PingTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, PingTest)
        self.assertEqual(suite.config.test_type, TestType.latency)

    def test_scp_from_tool_dict(self):
        tool = {'name': 'scp', 'client_host': 0, 'server_host': 1,
                'file_size': 10}
        suite = ScpTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, ScpTest)
        self.assertEqual(suite.config.test_type, TestType.scp)
        self.assertEqual(suite.config.file_size, 10)

    def test_scp_from_tool_dict_default_file_size(self):
        tool = {'name': 'scp', 'client_host': 0, 'server_host': 1}
        suite = ScpTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertEqual(suite.config.file_size, 1)

    def test_sshping_from_tool_dict(self):
        tool = {'name': 'sshping', 'client_host': 0, 'server_host': 1}
        suite = SSHPingTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, SSHPingTest)
        self.assertEqual(suite.config.test_type, TestType.sshping)

    def test_regular_from_tool_dict(self):
        tool = {'name': 'custom_tool', 'client_host': 0, 'server_host': 1,
                'args': '-v %s'}
        suite = RegularTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RegularTest)
        self.assertEqual(suite.config.args, '-v %s')

    def test_quic_perf_from_tool_dict(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1,
                'interval': 2.0, 'interval_num': 20, 'multipath': True,
                'args': '--loop 5'}
        suite = QuicPerfTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, QuicPerfTest)
        self.assertEqual(suite.config.test_type, TestType.throughput)
        self.assertEqual(suite.config.interval, 2.0)
        self.assertEqual(suite.config.interval_num, 20)
        self.assertEqual(suite.cert, '/etc/cfg/server.crt')
        self.assertEqual(suite.key, '/etc/cfg/server.key')
        self.assertEqual(suite.config.args, '--loop 5')
        self.assertTrue(suite.config.multipath)

    def test_quic_perf_from_tool_dict_defaults(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1}
        suite = QuicPerfTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, QuicPerfTest)
        self.assertEqual(suite.cert, '/etc/cfg/server.crt')
        self.assertEqual(suite.key, '/etc/cfg/server.key')
        self.assertEqual(suite.config.args, '')
        self.assertFalse(suite.config.multipath)

    def test_regular_benchmark_from_tool_dict(self):
        tool = {
            'name': 'benchmark',
            'profile': 'http_goodput',
            'client_host': 0,
            'server_host': 1,
        }
        suite = RegularBenchmarkTest.from_tool_dict(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RegularBenchmarkTest)
        self.assertEqual(suite.profile, 'http_goodput')
        self.assertEqual(suite.config.test_type, TestType.regular_benchmark)

    def test_regular_benchmark_rejects_unknown_profile(self):
        with self.assertRaises(ValueError):
            RegularBenchmarkTest.from_tool_dict(
                {'name': 'benchmark', 'profile': 'unknown'},
                'test1', self.root_path)

    @patch('testsuites.test_regular_benchmark.time.sleep', return_value=None)
    @patch.object(RegularBenchmarkTest, '_read_exit_status', return_value=0)
    def test_regular_benchmark_passes_result_directory_to_roles(self, _status, _sleep):
        tool = {
            'name': 'benchmark',
            'profile': 'http_latency',
            'client_host': 0,
            'server_host': 1,
        }
        suite = RegularBenchmarkTest.from_tool_dict(tool, 'test1', self.root_path)
        suite.result.record = os.path.join(self.root_path, 'regular_benchmark.log')
        client = MagicMock()
        client.name.return_value = 'h0'
        server = MagicMock()
        server.name.return_value = 'h1'

        self.assertTrue(suite._run_test(_StubNetwork([client, server]), None))

        result_base_path = os.path.dirname(os.path.splitext(suite.result.record)[0])
        self.assertIn(f'/usr/bin/regular_test.sh server {result_base_path}',
                      server.cmd.call_args_list[1].args[0])
        self.assertIn('setsid', server.cmd.call_args_list[1].args[0])
        self.assertIn('server_wrapper.pid', server.cmd.call_args_list[1].args[0])
        self.assertIn('kill -TERM', server.cmd.call_args_list[2].args[0])
        self.assertIn('kill -KILL --', server.cmd.call_args_list[2].args[0])
        self.assertIn(f'/usr/bin/regular_test.sh client {result_base_path}',
                      client.cmd.call_args.args[0])

    @patch.object(RegularBenchmarkTest, '_read_exit_status', return_value=0)
    def test_regular_benchmark_streams_client_wrapper_log(self, _status):
        tool = {
            'name': 'benchmark',
            'profile': 'http_latency',
            'client_host': 0,
            'server_host': 1,
        }
        suite = RegularBenchmarkTest.from_tool_dict(tool, 'test1', self.root_path)
        suite.result.record = os.path.join(self.root_path, 'regular_benchmark.log')
        client = MagicMock()
        client.name.return_value = 'h0'
        server = MagicMock()
        server.name.return_value = 'h1'

        with patch('testsuites.test_regular_benchmark.time.sleep'), \
                patch('testsuites.test_regular_benchmark.threading.Thread') as thread:
            self.assertTrue(suite._run_test(_StubNetwork([client, server]), None))

        stream_args = thread.call_args.kwargs['args']
        self.assertIs(stream_args[0], client)
        self.assertTrue(stream_args[1].endswith('/client_wrapper.log'))

    def test_regular_benchmark_stream_log_reads_shared_file_without_host_shell(self):
        log_path = os.path.join(self.root_path, 'client_wrapper.log')
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write('line one\nline two\n')
        host = MagicMock()
        host.name.return_value = 'h0'
        stop_event = threading.Event()
        stop_event.set()

        with self.assertLogs(level='INFO') as logs:
            RegularBenchmarkTest._stream_log_to_console(host, log_path, stop_event)

        host.cmd.assert_not_called()
        self.assertIn('[benchmark log] line one', '\n'.join(logs.output))
        self.assertIn('[benchmark log] line two', '\n'.join(logs.output))

    @patch.object(mp_benchmark.time, 'sleep', return_value=None)
    @patch.object(mp_benchmark, 'require_executable', return_value='/usr/bin/client_app')
    @patch.object(mp_benchmark, 'ManagedProcess')
    def test_mp_benchmark_redirects_nas_app_console_to_result_dir(
            self, managed_process, _require_executable, _sleep):
        config = mp_benchmark.ClientConfig(
            client_app_bin='client_app',
            client_app_args='',
            launch_client_app=True,
            client_app_log=Path(self.root_path) / 'root_log',
            server_app_log=Path(self.root_path) / 'server' / 'server_app.log',
            result_dir=Path(self.root_path) / 'client',
            http_base_url='http://localhost:9443',
            tcp_proxy_host='localhost',
            tcp_proxy_port=9443,
            transfer_iterations=20,
            http_request_rate=10.0,
            http_request_count=100,
            tcp_request_rate=100.0,
            tcp_request_count=100,
            tcp_ping_payload_size=1000,
            test_category='http-latency',
            large_files=['10M'],
            small_files=['10K'],
            startup_timeout=60.0,
            path_setup_delay=2.0,
            command_timeout=300.0,
        )
        managed_process.return_value.running.return_value = True

        runner = mp_benchmark.ClientRunner(config)
        runner._start_client_app()

        self.assertEqual(
            managed_process.call_args.args[2],
            Path(self.root_path) / 'client' / 'client_app.log')
        self.assertEqual(
            runner.server_app_log_cursor.root,
            Path(self.root_path) / 'server' / 'server_app.log')

    def test_mp_benchmark_download_uses_sender_nas_srv_path_pct(self):
        server_log = Path(self.root_path) / 'server' / 'server_app.log'
        receiver_log = Path(self.root_path) / 'client' / 'client_app.log'
        server_log.parent.mkdir(parents=True)
        receiver_log.parent.mkdir(parents=True)
        server_log.write_text('', encoding='utf-8')
        receiver_log.write_text(
            '[D][receiver]Path ID: 1,CID: a, PCT(s): 99.00%\n',
            encoding='utf-8')
        config = mp_benchmark.ClientConfig(
            'client_app', '', False, receiver_log, server_log,
            Path(self.root_path) / 'client', 'http://localhost:9443',
            'localhost', 9443, 1, 10.0, 1, 100.0, 1, 1000,
            'goodput', ['10M'], ['10K'], 60.0, 2.0, 300.0)

        def download(_argv, _timeout):
            with server_log.open('a', encoding='utf-8') as log_file:
                log_file.write('[D][sender]Path ID: 1,CID: a, PCT(s): 75.00%\n')
            return SimpleNamespace(returncode=0, stdout='1048576 1.0 200', stderr='')

        with patch.object(mp_benchmark, 'run_command', side_effect=download), \
                patch.object(mp_benchmark, 'write_goodput_summary_svg'):
            result = mp_benchmark.ClientRunner(config)._downloads()

        self.assertEqual(
            result['testfile_10M']['path_distribution']['latest_share_by_type'],
            {'D': 75.0})

    def test_mp_benchmark_goodput_summary_svg_includes_average_completion_time(self):
        svg_path = Path(self.root_path) / 'http_10M_goodput_summary.svg'

        mp_benchmark.write_goodput_summary_svg(
            svg_path,
            '10MB',
            12.5,
            20,
            {'D': 80.0, 'R': 20.0},
            [1.0, 2.0, 3.0],
            {'count': 3, 'avg': 2.0, 'min': 1.0, 'max': 3.0,
             'p50': 2.0, 'p95': 2.9, 'p99': 2.98},
        )

        svg = svg_path.read_text(encoding='utf-8')
        self.assertIn('Average completion time', svg)
        self.assertIn('>2.000<', svg)

    def test_mp_benchmark_sigterm_uses_graceful_shutdown_path(self):
        with self.assertRaises(KeyboardInterrupt):
            mp_benchmark._handle_shutdown_signal(15, None)

    def test_mp_benchmark_display_size_label_uses_byte_suffix(self):
        self.assertEqual(mp_benchmark.display_size_label('10K'), '10KB')
        self.assertEqual(mp_benchmark.display_size_label('20k'), '20KB')
        self.assertEqual(mp_benchmark.display_size_label('10M'), '10MB')

    @patch.object(mp_benchmark, 'wait_for_http')
    def test_mp_benchmark_http_proxy_ready_timeout_is_fixed(self, wait_for_http):
        result_dir = Path(self.root_path) / 'client'
        config = mp_benchmark.ClientConfig(
            'client_app', '', False, Path(self.root_path) / 'client_app.log',
            Path(self.root_path) / 'server' / 'server_app.log',
            result_dir, 'http://localhost:9443', 'localhost', 9443,
            1, 10.0, 1, 100.0, 1, 1000, 'readiness-only',
            ['10M'], ['10K'], 60.0, 0.0, 300.0)

        mp_benchmark.ClientRunner(config).run()

        wait_for_http.assert_called_once_with(
            'http://localhost:9443/testfile_10K',
            mp_benchmark.DEFAULT_PROXY_READY_TIMEOUT)
        self.assertEqual(mp_benchmark.DEFAULT_PROXY_READY_TIMEOUT, 5.0)

    @patch.object(mp_benchmark, 'sleep_for_rate')
    @patch.object(mp_benchmark, 'write_latency_svg')
    @patch.object(mp_benchmark, 'run_command')
    def test_mp_benchmark_http_latency_title_uses_display_size_label(
            self, run_command, write_latency_svg, _sleep_for_rate):
        run_command.return_value = SimpleNamespace(
            returncode=0, stdout='0.001 200', stderr='')
        config = mp_benchmark.ClientConfig(
            'client_app', '', False, Path(self.root_path) / 'client_app.log',
            Path(self.root_path) / 'server' / 'server_app.log',
            Path(self.root_path) / 'client', 'http://localhost:9443',
            'localhost', 9443, 1, 10.0, 1, 100.0, 1, 1000,
            'http-latency', ['10M'], ['10K'], 60.0, 0.0, 300.0)

        mp_benchmark.ClientRunner(config)._http_latency()

        self.assertEqual(write_latency_svg.call_args.args[1],
                         'HTTP request latency 10KB')

    @patch('testsuites.test_quic_perf.time.sleep', return_value=None)
    def test_quic_perf_multipath_flag_is_forwarded(self, _sleep):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1,
                'interval': 2.0, 'interval_num': 3, 'multipath': True}
        suite = QuicPerfTest.from_tool_dict(tool, 'test1', self.root_path)
        suite.result.record = os.path.join(self.root_path, 'quic_perf.log')

        client = MagicMock()
        server = MagicMock()
        server.getIntfs.return_value = [
            SimpleNamespace(name='eth0', ip='10.0.0.2'),
        ]

        self.assertTrue(suite._run_quic_perf(
            client, server, None, ('--dgram', 'quic-datagram')))

        server_cmd = server.cmd.call_args_list[0].args[0]
        client_cmd = client.popen.call_args.args[0]
        self.assertIn('--multipath', server_cmd)
        self.assertIn('--server-list', client_cmd)


try:
    from src.core.runner import load_test_tool  # pylint: disable=ungrouped-imports
    _HAS_RUNNER = True
except ImportError:
    _HAS_RUNNER = False


@unittest.skipUnless(_HAS_RUNNER,
                     "runner.py requires matplotlib which may not be installed")
class TestLoadTestToolIntegration(unittest.TestCase):
    """Integration: load_test_tool (in runner.py) should use the registry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root_path = self.tmp + '/'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_iperf(self):
        tool = {'name': 'iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfTest)

    def test_load_bats_iperf(self):
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfBatsTest)

    def test_load_ping(self):
        tool = {'name': 'ping', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, PingTest)

    def test_load_rtt(self):
        tool = {'name': 'rtt', 'client_host': 0, 'server_host': 1,
                'packet_count': 100, 'packet_size': 512}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RTTTest)

    def test_load_scp(self):
        tool = {'name': 'scp', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, ScpTest)

    def test_load_quic_perf(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, QuicPerfTest)

    def test_load_regular_benchmark(self):
        tool = {'name': 'benchmark', 'profile': 'http_latency',
                'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RegularBenchmarkTest)

    def test_load_unknown_falls_back_to_regular(self):
        tool = {'name': 'unknown_tool_xyz', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RegularTest)


if __name__ == '__main__':
    unittest.main()
