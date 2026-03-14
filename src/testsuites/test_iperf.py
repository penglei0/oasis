import logging
import time
from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('iperf', match='contains', test_type=TestType.throughput)
class IperfTest(ITestSuite):
    """Throughput test using ``iperf3``.

    Supports TCP and UDP modes, parallel streams, and custom bitrate.
    Receiver IP/port is resolved via :meth:`resolve_receiver` so that
    proxy protocols (KCP, QUIC) and tunnel protocols (BTP, BRTP) are
    handled transparently.
    """

    def __init__(self, config: TestConfig) -> None:
        super().__init__(config)
        self.is_udp_mode = False
        self.is_port_forward = False
        if self.config.packet_type == "udp":
            self.is_udp_mode = True
            if self.config.bitrate == 0:
                self.config.bitrate = 10
            logging.info("IperfTest is in UDP mode, bitrate: %d Mbps",
                         self.config.bitrate)

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'IperfTest':
        """Build an :class:`IperfTest` from a YAML tool dictionary."""
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

    def _run_iperf(self, client, server, recv_port, recv_ip):
        if self.config is None:
            logging.error("IperfTest config is None.")
            return False
        parallel = self.config.parallel or 1
        if parallel > 1:
            logging.info(
                "IperfTest is running with parallel streams: %d", parallel)
        interval_num = self.config.interval_num or 10
        interval = self.config.interval or 1
        server.cmd(f'iperf3 -s -p {recv_port} -i {int(interval)} -V --forceflush'
                   f' --logfile {self.result.record} &')
        iperf3_client_cmd = f'iperf3 -c {recv_ip} -p {recv_port} -P {parallel} -i {int(interval)}' \
            f' -t {int(interval_num * interval)}'
        if self.is_udp_mode:
            iperf3_client_cmd += f' -u -b {self.config.bitrate}M'
        else:
            iperf3_client_cmd += f' --connect-timeout 5000'
            if self.config.bitrate != 0:
                iperf3_client_cmd += f' -b {self.config.bitrate}M'
        logging.info('iperf client cmd: %s', iperf3_client_cmd)
        res = client.popen(
            f'{iperf3_client_cmd}').stdout.read().decode('utf-8')
        logging.info('iperf client output: %s', res)
        logging.info('iperf test result save to %s', self.result.record)
        time.sleep(1)
        client.cmd('pkill -9 -f iperf3')
        server.cmd('pkill -9 -f iperf3')
        return True

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        if hosts is None:
            return False
        self._default_client_server(network)

        client = hosts[self.config.client_host]
        server = hosts[self.config.server_host]

        receiver_ip, receiver_port = self.resolve_receiver(network, proto_info)

        # IperfTest-specific: BTP/BRTP port-forwarding override
        upper_proto_name = proto_info.get_protocol_name().upper()
        if upper_proto_name in ["BTP", "BRTP"] and self.is_port_forward:
            receiver_ip = client.IP()
            logging.debug(
                "Test iperf3 with port forwarding from %s:5201 to %s", receiver_ip, server.IP())

        if receiver_port == 0:
            # if no forward port defined, use iperf3 default port 5201
            receiver_port = 5201

        logging.info(
            "############### Oasis IperfTest from %s to %s ###############", client.name(), server.name())
        return self._run_iperf(client, server, receiver_port, receiver_ip)
