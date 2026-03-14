import time
import logging

from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('rtt', test_type=TestType.rtt)
class RTTTest(ITestSuite):
    """Measures the round trip time between two hosts in the network.

    RTTTest uses tool ``bin/tcp_message/tcp_endpoint`` to measure the RTT.
    Source of the tool is in https://github.com/n-hop/bats-documentation
    """

    def __init__(self, config: TestConfig) -> None:
        super().__init__(config)
        self.run_times = 0
        self.first_rtt_repeats = 15
        self.binary_path = "tcp_endpoint"

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'RTTTest':
        """Build an :class:`RTTTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            packet_count=tool['packet_count'],
            packet_size=tool['packet_size'],
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            test_type=TestType.rtt,
            root_path=root_path,
        )
        return cls(config)

    def post_process(self):
        return True

    def pre_process(self):
        return True

    def _run_tcp_endpoint(self, client, server, port, recv_ip):
        loop_cnt = 1
        server.cmd(f'{self.binary_path} -p {port} &')
        tcp_client_cmd = f'{self.binary_path} -c {recv_ip} -p {port}'
        tcp_client_cmd += f' -i {self.config.interval}' \
            f' -w {self.config.packet_count} -l {self.config.packet_size}'
        if self.config.packet_count == 1:
            # measure the first rtt, repeat 10 times
            loop_cnt = self.first_rtt_repeats
            tcp_client_cmd += f' >> {self.result.record}'
        else:
            tcp_client_cmd += f' > {self.result.record}'
        for _ in range(loop_cnt):
            client.cmd(f'{tcp_client_cmd}')
            client.cmd('pkill -9 -f tcp_endpoint')
        logging.info('rtt test result save to %s', self.result.record)
        time.sleep(1)
        server.cmd('pkill -9 -f tcp_endpoint')
        return True

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        self._default_client_server(network)

        client = hosts[self.config.client_host]
        server = hosts[self.config.server_host]

        receiver_ip, receiver_port = self.resolve_receiver(network, proto_info)

        if receiver_port == 0:
            # if no forward port defined, use random port start from 30011
            # for port conflict, use different port for each test
            receiver_port = 30011 + self.run_times
            self.run_times += 1
        logging.info(
            "############### Oasis RTTTest from %s to %s with forward port %s ###############",
            client.name(), server.name(), receiver_port)
        return self._run_tcp_endpoint(client, server, receiver_port, receiver_ip)
