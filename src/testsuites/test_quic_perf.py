import logging
import time
import os

from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('quic_perf', test_type=TestType.throughput)
class QuicPerfTest(ITestSuite):
    """Throughput test using the ``quic_perf`` QUIC performance tool.

    ``quic_perf`` measures QUIC protocol performance in a client/server
    model.  The server is started on one host and the client connects
    from another host.

    Supported YAML keys (in addition to the standard ones)::

        test_tools:
          quic_perf:
            interval: 1
            interval_num: 10
            args: "--loop 5"              # extra CLI arguments
            multipath: true               # enable QUIC multipath mode
    """
    DEFAULT_CERT = '/etc/cfg/server.crt'
    DEFAULT_KEY = '/etc/cfg/server.key'

    def __init__(self, config: TestConfig) -> None:
        super().__init__(config)
        self.cert = self.DEFAULT_CERT
        self.key = self.DEFAULT_KEY

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'QuicPerfTest':
        """Build a :class:`QuicPerfTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            multipath=tool.get('multipath', False),
            test_type=TestType.throughput,
            root_path=root_path,
        )
        instance = cls(config)
        instance.cert = tool.get('cert', cls.DEFAULT_CERT)
        instance.key = tool.get('key', cls.DEFAULT_KEY)
        return instance

    def pre_process(self):
        return True

    def post_process(self):
        return True

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        if hosts is None:
            return False
        self._default_client_server(network)

        client = hosts[self.config.client_host]
        server = hosts[self.config.server_host]

        logging.info(
            "############### Oasis QuicPerfTest from %s to %s ###############",
            client.name(), server.name())
        return self._run_quic_perf(
            client,
            server,
            (
                proto_info.get_protocol_args(network),
                proto_info.get_protocol_name(),
            ),
        )

    def _run_quic_perf(self, client, server, protocol):
        """Start the quic_perf server, run the client, then clean up."""
        if self.config is None:
            logging.error("QuicPerfTest config is None.")
            return False
        proto_args, proto_name = protocol
        base_path = os.path.dirname(os.path.abspath(self.result.record))
        # --- start server ---------------------------------------------------
        server_log_path = os.path.join(
            base_path, f"{proto_name}/log/{server.name()}_quic_perf.log")
        server_cmd = (
            f'quic_perf --mode server --addr 0.0.0.0'
            f' --log {server_log_path}'
            f' --log-interval {self.result.record}'
        )
        if self.config.multipath:
            server_cmd += ' --multipath'
        if proto_args:
            server_cmd += f' {proto_args}'
        logging.info('quic_perf server cmd: %s', server_cmd)
        server.cmd(f'{server_cmd} &')
        time.sleep(1)  # give the server a moment to bind

        # --- run client ------------------------------------------------------
        duration = self.config.interval * self.config.interval_num
        client_log_path = os.path.join(
            base_path, f"{proto_name}/log/{client.name()}_quic_perf.log")
        client_cmd = f'quic_perf --mode client'
        if self.config.multipath:
            client_cmd += ' --server-list'
            for intf in server.getIntfs():
                logging.info("QuicPerfTest client connect to %s intf %s IP %s",
                        server.name(), intf.name, intf.ip)
                client_cmd += f' {intf.ip}'
        else:
            client_cmd += f' --addr {server.IP()}'
        if proto_args:
            client_cmd += f' {proto_args}'
        if self.config.args:
            client_cmd += f' {self.config.args}'
        client_cmd += f' --count 0 --duration {duration}'
        client_cmd += f' --log {client_log_path}'
        logging.info('quic_perf client cmd: %s', client_cmd)

        client.popen(client_cmd)

        time.sleep(duration + 2)  # wait for the client to finish (with some buffer)
        # --- cleanup ---------------------------------------------------------
        try:
            client.cmd('pkill -9 -f quic_perf')
            server.cmd('pkill -9 -f quic_perf')
        finally:
            # Nothing additional here; `finally` ensures cleanup attempts run.
            pass
        return True
