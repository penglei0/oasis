import logging

from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('ping', test_type=TestType.latency)
class PingTest(ITestSuite):
    """ICMP ping latency test.

    When ``client_host`` / ``server_host`` are not specified, pings from
    every host (except host 0) *to* host 0.
    """

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'PingTest':
        """Build a :class:`PingTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            test_type=TestType.latency,
            root_path=root_path,
        )
        return cls(config)
    def post_process(self):
        return True

    def pre_process(self):
        return True

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        hosts_num = len(hosts)
        if self.config.client_host is None or self.config.server_host is None:
            for i in range(hosts_num):
                if i == 0:
                    continue
                logging.info(
                    f"############### Oasis PingTest from "
                    "%s to %s ###############", hosts[i].name(), hosts[0].name())
                res = hosts[i].cmd(f'ping -W 1 -c {self.config.interval_num} -i {self.config.interval} '
                                   f'{hosts[i].IP()}'
                                   f' > {self.result.record}')
                logging.info('host %s', res)
                if "100% packet loss" in res:
                    logging.error("Ping test failed")
                    return False
            return True
        # Run ping test from client to server
        logging.info(
            f"############### Oasis PingTest from "
            "%s to %s ###############",
            hosts[self.config.client_host].name(),
            hosts[self.config.server_host].name())
        res = hosts[self.config.client_host].popen(
            f'ping -W 1 -c {self.config.interval_num} -i {self.config.interval} '
            f'{hosts[self.config.server_host].IP()}').stdout.read().decode('utf-8')
        logging.info('host %s', res)
        if "100% packet loss" in res:
            logging.error("Ping test failed")
            return False
        return True
