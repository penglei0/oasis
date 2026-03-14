"""Unit tests for ITestSuite refactoring: registry, resolve_receiver, from_tool_dict."""

import os
import shutil
import tempfile
import unittest

from testsuites.test import (
    TestConfig, TestType, ITestSuite, PROXY_PROTOCOLS,
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
from testsuites.test_regular import RegularTest


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

    def test_iperf_uses_contains_match(self):
        reg = get_test_suite_registry()
        self.assertEqual(reg['iperf']['match'], 'contains')

    def test_exact_match_entries(self):
        reg = get_test_suite_registry()
        for name in ('bats_iperf', 'rtt', 'ping', 'scp'):
            self.assertEqual(reg[name]['match'], 'exact', f'{name} should be exact match')

    def test_registry_classes(self):
        reg = get_test_suite_registry()
        self.assertEqual(reg['iperf']['class'], IperfTest)
        self.assertEqual(reg['bats_iperf']['class'], IperfBatsTest)
        self.assertEqual(reg['rtt']['class'], RTTTest)
        self.assertEqual(reg['ping']['class'], PingTest)
        self.assertEqual(reg['scp']['class'], ScpTest)


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

    def test_bats_iperf_exact_beats_iperf_contains(self):
        """bats_iperf should match the exact entry, not the 'contains' iperf entry."""
        tool = {'name': 'bats_iperf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, IperfBatsTest)

    def test_unknown_tool_returns_none(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1}
        suite = load_test_suite_from_registry(tool, 'test1', self.root_path)
        self.assertIsNone(suite)


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

    def test_load_unknown_falls_back_to_regular(self):
        tool = {'name': 'quic_perf', 'client_host': 0, 'server_host': 1}
        suite = load_test_tool(tool, 'test1', self.root_path)
        self.assertIsInstance(suite, RegularTest)


if __name__ == '__main__':
    unittest.main()
