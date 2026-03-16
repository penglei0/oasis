import logging
import time
import os
from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('bats_iperf', test_type=TestType.throughput)
class IperfBatsTest(ITestSuite):
    """Throughput test using the BATS-specific ``bats_iperf`` binary.

    Unlike :class:`IperfTest`, ``bats_iperf`` always sends to the server's
    direct IP (protocol-level routing is handled by the BATS stack).
    Protocol-specific arguments (e.g. ``-m 0`` for BTP) are obtained via
    ``proto_info.get_protocol_args()``.
    """

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'IperfBatsTest':
        """Build an :class:`IperfBatsTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            parallel=tool.get('parallel', 1),
            packet_type=tool.get('packet_type', 'tcp'),
            bitrate=tool.get('bitrate', 0),
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            test_type=TestType.throughput,
            root_path=root_path,
        )
        return cls(config)

    def post_process(self):
        return True

    def pre_process(self):
        return True

    def _run_iperf(self, client, server, args_from_proto: str, proto_name: str):
        if self.config is None:
            logging.error("IperfBatsTest config is None.")
            return False
        receiver_ip = server.IP()
        receiver_port = 5201
        parallel = self.config.parallel or 1
        if parallel > 1:
            logging.info(
                "IperfBatsTest is running with parallel streams: %d", parallel)
        interval_num = self.config.interval_num or 10
        interval = self.config.interval or 1
        base_path = os.path.dirname(os.path.abspath(self.result.record))
        for intf in server.getIntfs():
            server_log_path = os.path.join(
                base_path, f"{proto_name}/log/{server.name()}/")
            bats_iperf_server_cmd = f'bats_iperf -s -p {receiver_port} -i {float(interval)} -I {intf}' \
                f' -l {self.result.record}  -L {server_log_path} &'
            logging.info(
                'bats_iperf server cmd: %s', bats_iperf_server_cmd)
            server.cmd(f'{bats_iperf_server_cmd}')

        client_log_path = os.path.join(
            base_path, f"{proto_name}/log/{client.name()}/")
        bats_iperf_client_cmd = f'bats_iperf -c {receiver_ip} {args_from_proto} -p {receiver_port} -P {parallel}' \
            f' -i {float(interval)} -t {int(interval_num)} -L {client_log_path}'
        logging.info('bats_iperf client cmd: %s', bats_iperf_client_cmd)
        res = client.popen(
            f'{bats_iperf_client_cmd}').stdout.read().decode('utf-8')
        logging.info('bats_iperf client output: %s', res)
        logging.info('bats_iperf test result save to %s', self.result.record)
        time.sleep(1)
        client.cmd('pkill -9 -f bats_iperf')
        server.cmd('pkill -9 -f bats_iperf')
        return True

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        if hosts is None:
            return False
        self._default_client_server(network)
        client = hosts[self.config.client_host]
        server = hosts[self.config.server_host]
        logging.info(
            "############### Oasis IperfBatsTest from %s to %s ###############", client.name(), server.name())
        return self._run_iperf(client, server, proto_info.get_protocol_args(network), proto_info.get_protocol_name())
