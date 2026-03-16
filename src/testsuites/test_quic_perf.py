import logging
import time
import subprocess
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
    """

    DEFAULT_CERT = "/etc/cfg/server.crt"
    DEFAULT_KEY = "/etc/cfg/server.key"

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
            test_type=TestType.throughput,
            root_path=root_path,
        )
        instance = cls(config)
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

        receiver_ip, receiver_port = self.resolve_receiver(network, proto_info)

        logging.info(
            "############### Oasis QuicPerfTest from %s to %s ###############",
            client.name(), server.name())
        return self._run_quic_perf(client, server, receiver_ip, receiver_port)

    def _run_quic_perf(self, client, server, recv_ip, recv_port, proto_args=None):
        """Start the quic_perf server, run the client, then clean up."""
        if self.config is None:
            logging.error("QuicPerfTest config is None.")
            return False

        # --- start server ---------------------------------------------------
        server_cmd = (
            f'quic_perf --mode server'
            f' --cert {self.cert} --key {self.key}'
        )
        if recv_port:
            server_cmd += f' --port {recv_port}'
        if proto_args:
            server_cmd += f' {proto_args}'
        logging.info('quic_perf server cmd: %s', server_cmd)
        server.cmd(f'{server_cmd} &')
        time.sleep(1)  # give the server a moment to bind

        # --- run client ------------------------------------------------------
        duration = self.config.interval * self.config.interval_num
        client_cmd = f'quic_perf --mode client --addr {recv_ip}'
        if recv_port:
            client_cmd += f' --port {recv_port}'
        if proto_args:
            client_cmd += f' {proto_args}'
        if self.config.args:
            client_cmd += f' {self.config.args}'
        client_cmd += f' --count 0 --duration {duration}'
        logging.info('quic_perf client cmd: %s', client_cmd)

        proc = client.popen(client_cmd)

        # Derive a timeout from interval * interval_num, if possible.
        timeout_seconds = None
        try:
            if self.config.interval is not None and self.config.interval_num is not None:
                timeout_seconds = float(self.config.interval) * float(self.config.interval_num)
                if timeout_seconds <= 0:
                    timeout_seconds = None
        except (TypeError, ValueError):
            timeout_seconds = None

        res = ""
        test_success = True
        try:
            if timeout_seconds is not None:
                stdout_data, _ = proc.communicate(timeout=timeout_seconds)
            else:
                stdout_data, _ = proc.communicate()
            res = stdout_data.decode('utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            logging.error(
                "quic_perf client timed out after %.2f seconds; terminating process",
                timeout_seconds,
            )
            test_success = False
            proc.kill()
            try:
                stdout_data, _ = proc.communicate(timeout=5)
                res = stdout_data.decode('utf-8', errors='replace')
            except subprocess.TimeoutExpired:
                logging.error("Failed to terminate quic_perf client process cleanly")
                res = ""
        logging.info('quic_perf client output: %s', res)

        # write result to the record file
        with open(self.result.record, 'w', encoding='utf-8') as fout:
            fout.write(res)
        logging.info('quic_perf test result saved to %s', self.result.record)

        # --- cleanup ---------------------------------------------------------
        try:
            time.sleep(1)
            client.cmd('pkill -9 -f quic_perf')
            server.cmd('pkill -9 -f quic_perf')
        finally:
            # Nothing additional here; `finally` ensures cleanup attempts run.
            pass
        return test_success
