import logging
import time
from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import (ITestSuite, TestConfig, TestType)


class RegularTest(ITestSuite):
    """Fallback test tool for arbitrary binaries.

    ``RegularTest`` runs a user-supplied binary with configurable arguments.
    The placeholder ``%s`` in *args* is replaced with the target IP.  The
    process is killed after ``interval × interval_num + 1`` seconds.

    This class is **not** registered in the test-suite registry — it serves
    as the default when no registered tool matches the YAML tool name.
    """

    def __init__(self, config: TestConfig) -> None:
        super().__init__(config)
        self.binary_path = config.name
        if config.name == "sshping":
            self.config.test_type = TestType.sshping
        else:
            self.config.test_type = TestType.throughput

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str,
                       root_path: str) -> 'RegularTest':
        """Build a :class:`RegularTest` from a YAML tool dictionary."""
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            client_host=tool.get('client_host'),
            server_host=tool.get('server_host'),
            args=tool.get('args', ''),
            root_path=root_path,
        )
        return cls(config)

    def post_process(self):
        return True

    def pre_process(self):
        return True

    def _get_format_args(self, ip: str):
        formatted_args = self.config.args if self.config.args else ""
        if isinstance(formatted_args, list):
            formatted_args = " ".join(formatted_args)
        if "%s" in formatted_args:
            formatted_args = formatted_args % ip
        return formatted_args

    def _wait_timeout_or_finish(self, hosts):
        interval_num = self.config.interval_num or 10
        interval = self.config.interval or 1
        max_wait_time = interval_num * interval + 1
        # wait for the test to finish in max_wait_time seconds
        wait_time = 0
        while wait_time < max_wait_time:
            wait_time += 1
            time.sleep(1)
        for h in hosts:
            if h is None:
                continue
            logging.info("RegularTest %s timeout", self.config.name)
            h.cmd(
                f'pkill -9 -f {self.binary_path}')
            logging.info("RegularTest %s killed", self.config.name)

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
                    f"############### Oasis RegularTest %s from "
                    "%s to %s ###############",
                    self.config.name, hosts[i].name(), hosts[0].name())
                formatted_args = self._get_format_args(receiver_ip)
                hosts[i].cmd(
                    f'{self.binary_path} {formatted_args} > {self.result.record} &')
            self._wait_timeout_or_finish(hosts)
            return True
        # Single-pair mode: use resolve_receiver for tunnel/proxy awareness
        receiver_ip, _ = self.resolve_receiver(network, proto_info)
        logging.info(
            f"############### Oasis RegularTest %s from "
            "%s to %s ###############",
            self.config.name,
            hosts[self.config.client_host].name(),
            hosts[self.config.server_host].name())
        formatted_args = self._get_format_args(receiver_ip)
        logging.info("formatted_args: %s", formatted_args)
        hosts[self.config.client_host].cmd(
            f'{self.binary_path} {formatted_args} > {self.result.record} &')
        self._wait_timeout_or_finish([hosts[self.config.client_host]])
        return True
