"""Oasis wrapper for the role-based multipath benchmark scripts."""

import logging
import os
import shlex
import threading
import time

from interfaces.network import INetwork
from protosuites.proto_info import IProtoInfo
from .test import ITestSuite, TestConfig, TestType, register_test_suite


PROFILES = frozenset({"http_latency", "http_goodput"})
PROFILE_INSTALLER = "/usr/sbin/install_benchmark_profile.sh"


@register_test_suite("benchmark", test_type=TestType.regular_benchmark)
class RegularBenchmarkTest(ITestSuite):
    """Run ``regular_test.sh`` roles without resolving tunnel IPs or ports."""

    def __init__(self, config: TestConfig, profile: str, server_start_delay: float) -> None:
        super().__init__(config)
        self.profile = profile
        self.server_start_delay = server_start_delay

    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str, root_path: str) -> "RegularBenchmarkTest":
        profile = tool.get("profile", "http_latency")
        if profile not in PROFILES:
            raise ValueError(f"unsupported regular benchmark profile: {profile}")
        config = TestConfig(
            name=tool["name"],
            test_name=test_name,
            client_host=tool.get("client_host"),
            server_host=tool.get("server_host"),
            test_type=TestType.regular_benchmark,
            root_path=root_path,
        )
        return cls(config, profile, float(tool.get("server_start_delay", 2.0)))

    def pre_process(self) -> bool:
        return True

    def post_process(self) -> bool:
        return True

    def _install_profile(self, host) -> None:
        host.cmd(f"{PROFILE_INSTALLER} {shlex.quote(self.profile)}")

    @staticmethod
    def _read_exit_status(status_path: str):
        """Read a role status file; return ``None`` while the role is running."""
        try:
            with open(status_path, encoding="utf-8") as status_file:
                output = status_file.read()
        except OSError:
            return None
        try:
            return int(output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _stream_log_to_console(host, log_path: str, stop_event: threading.Event) -> None:
        offset = 0
        logging.info("Streaming benchmark log from %s:%s", host.name(), log_path)
        while True:
            if os.path.exists(log_path):
                with open(log_path, "rb") as log_file:
                    log_file.seek(offset)
                    output = log_file.read()
                if output:
                    offset += len(output)
                    for line in output.decode("utf-8", errors="replace").rstrip().splitlines():
                        logging.info("[benchmark log] %s", line)
            if stop_event.wait(1.0):
                if os.path.exists(log_path):
                    with open(log_path, "rb") as log_file:
                        log_file.seek(offset)
                        output = log_file.read()
                    if output:
                        for line in output.decode("utf-8", errors="replace").rstrip().splitlines():
                            logging.info("[benchmark log] %s", line)
                break

    def _run_test(self, network: INetwork, _proto_info: IProtoInfo) -> bool:
        hosts = network.get_hosts()
        if not hosts:
            logging.error("Regular benchmark requires at least two hosts")
            return False
        self._default_client_server(network)
        client = hosts[self.config.client_host]
        server = hosts[self.config.server_host]
        artifact_dir = f"{os.path.splitext(self.result.record)[0]}"
        result_base_path = os.path.dirname(artifact_dir)
        quoted_result_base_path = shlex.quote(result_base_path)
        logging.info("Oasis regular benchmark profile=%s client=%s server=%s",
                     self.profile, client.name(), server.name())
        logging.info("Oasis regular benchmark result dir=%s", result_base_path)
        self._install_profile(server)
        self._install_profile(client)
        server_log_path = f"{result_base_path}/server_wrapper.log"
        server_pid_path = f"{result_base_path}/server_wrapper.pid"
        server_status_path = f"{result_base_path}/server_wrapper.status"
        client_log_path = f"{result_base_path}/client_wrapper.log"
        client_status_path = f"{result_base_path}/client_wrapper.status"
        server_command = (
            f"/usr/bin/regular_test.sh server {quoted_result_base_path} "
            f"> {shlex.quote(server_log_path)} 2>&1; "
            f"status=$?; printf '%s\\n' \"$status\" > "
            f"{shlex.quote(server_status_path)}")
        server.cmd(
            f"mkdir -p {quoted_result_base_path} && "
            f"rm -f {shlex.quote(server_status_path)} {shlex.quote(server_pid_path)} && "
            f"setsid sh -c {shlex.quote(server_command)} & "
            f"echo $! > {shlex.quote(server_pid_path)}")
        time.sleep(self.server_start_delay)
        stop_log_stream = threading.Event()
        log_thread = threading.Thread(
            target=self._stream_log_to_console,
            args=(client, client_log_path, stop_log_stream),
            daemon=True,
        )
        log_thread.start()
        try:
            client.cmd(
                f"mkdir -p {quoted_result_base_path} && "
                f"rm -f {shlex.quote(client_status_path)} && "
                f"/usr/bin/regular_test.sh client {quoted_result_base_path} "
                f"> {shlex.quote(client_log_path)} 2>&1; "
                f"status=$?; printf '%s\\n' \"$status\" > "
                f"{shlex.quote(client_status_path)}")
        finally:
            stop_log_stream.set()
            log_thread.join(timeout=2.0)
            server_status = self._read_exit_status(server_status_path)
            server.cmd(
                f"if [ -s {shlex.quote(server_pid_path)} ]; then "
                f"pid=$(cat {shlex.quote(server_pid_path)}); "
                f"kill -TERM \"$pid\" 2>/dev/null || true; "
                f"for _ in 1 2 3 4 5 6 7 8 9 10; do "
                f"kill -0 \"$pid\" 2>/dev/null || break; sleep 1; "
                f"done; "
                f"if kill -0 \"$pid\" 2>/dev/null; then "
                f"kill -KILL -- \"-$pid\" 2>/dev/null || true; fi; "
                f"fi")
        client_status = self._read_exit_status(client_status_path)
        if client_status != 0:
            logging.error("Regular benchmark client failed with exit status %s", client_status)
            return False
        if server_status not in (None, 0):
            logging.error("Regular benchmark server failed with exit status %s", server_status)
            return False
        return True
