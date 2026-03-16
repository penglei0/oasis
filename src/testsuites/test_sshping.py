import logging
import time
from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType, register_test_suite)


@register_test_suite('sshping', test_type=TestType.sshping)
class SSHPingTest(ITestSuite):
    """Measures the RTT of ssh ping message between two hosts in the network.

    Uses the `sshping <https://github.com/spook/sshping>`_ binary.
    When ``client_host`` / ``server_host`` are not specified, tests from
    every host (except host 0) *to* host 0.
    """

    def __init__(self, config: TestConfig) -> None:
        super().__init__(config)
        self.binary_path = "sshping"

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'SSHPingTest':
        """Build a :class:`SSHPingTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            test_type=TestType.sshping,
            root_path=root_path,
        )
        return cls(config)

    def post_process(self):
        return True

    def pre_process(self):
        return True

    def _max_wait_time(self):
        interval_num = self.config.interval_num or 10
        interval = self.config.interval or 1
        return int(interval_num * interval) + 1

    def _wait_and_kill(self, hosts_to_kill):
        """Wait for sshping to finish, then forcibly stop it on all given hosts."""
        time.sleep(self._max_wait_time())
        for h in hosts_to_kill:
            h.cmd(f'pkill -9 -f {self.binary_path}')

    def _run_test(self, network: INetwork, proto_info: IProtoInfo):
        hosts = network.get_hosts()
        if hosts is None:
            logging.error("No host found in the network")
            return False
        hosts_num = len(hosts)
        if self.config.client_host is None or self.config.server_host is None:
            for i in range(hosts_num):
                if i == 0:
                    continue
                tun_ip = proto_info.get_tun_ip(
                    network, 0)
                if tun_ip == "":
                    tun_ip = hosts[0].IP()
                receiver_ip = tun_ip
                logging.info(
                    f"############### Oasis SSHPingTest from "
                    "%s to %s ###############", hosts[i].name(), hosts[0].name())
                hosts[i].cmd(
                    f'{self.binary_path} -i /root/.ssh/id_rsa'
                    f' -H root@{receiver_ip} > {self.result.record} &')
            self._wait_and_kill(hosts[1:])
            return True
        # Run sshping test from client to server
        receiver_ip, _ = self.resolve_receiver(network, proto_info)
        client = hosts[self.config.client_host]
        logging.info(
            f"############### Oasis SSHPingTest from "
            "%s to %s ###############",
            client.name(),
            hosts[self.config.server_host].name())
        client.cmd(
            f'{self.binary_path} -i /root/.ssh/id_rsa'
            f' -H root@{receiver_ip} > {self.result.record} &')
        self._wait_and_kill([client])
        return True
