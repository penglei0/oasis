#!/usr/bin/env python3
"""Generic HTTP goodput and latency benchmark helper."""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import os
import re
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin


DEFAULT_LARGE_FILES = ("100M", "50M", "10M")
DEFAULT_SMALL_FILES = ("10K", "20K", "50K")
DEFAULT_TRANSFER_ITERATIONS = 20
DEFAULT_HTTP_REQUEST_COUNT = 1000
DEFAULT_HTTP_REQUEST_RATE = 10.0
DEFAULT_TCP_REQUEST_COUNT = 1000
DEFAULT_TCP_REQUEST_RATE = 100.0
DEFAULT_TCP_PING_PAYLOAD_SIZE = 1000
DEFAULT_HTTP_PORT = 9443
DEFAULT_DUFS_PORT = 9999
DEFAULT_ECHO_PORT = 9091
DEFAULT_SERVER_SHARE_DIR = "/tmp"
DEFAULT_SERVER_WORK_DIR = "/tmp/http_benchmark-server"
DEFAULT_CLIENT_RESULT_BASE = "/root/http_benchmark-results"
DEFAULT_SERVER_RESULT_BASE = "/root/http_benchmark-server-results"
DEFAULT_SERVER_APP_ARGS = ""
DEFAULT_CLIENT_APP_LOG = "/root/log"
DEFAULT_SERVER_APP_LOG = "/root/log/server_app.log"
DEFAULT_BENCHMARK_LOG = "/root/http_benchmark.log"
DEFAULT_PATH_SETUP_DELAY = 1.5
DEFAULT_PROXY_READY_TIMEOUT = 5.0

TEST_CATEGORY_ALL = "all"
TEST_CATEGORY_GOODPUT = "goodput"
TEST_CATEGORY_LATENCY = "latency"
TEST_CATEGORY_HTTP_LATENCY = "http-latency"
TEST_CATEGORY_TCP_LATENCY = "tcp-latency"

HTTP_METRIC_RE = re.compile(r"^(?P<speed>[0-9.]+)\s+(?P<time>[0-9.]+)\s+(?P<code>\d{3})$")
PATH_SHARE_RE = re.compile(
    r"\[(?P<kind>[A-Z][A-Z0-9_-]*)\]\[[^\]]+\]Path ID:\s*(?P<id>\d+),"
    r"CID:\s*(?P<cid>[0-9a-fA-F]+),.*PCT\(s\):\s*(?P<pct>[0-9.]+)%"
)


def configure_logging(verbose: bool) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()
    for handler in (logging.StreamHandler(), logging.FileHandler(DEFAULT_BENCHMARK_LOG, encoding="utf-8")):
        handler.setFormatter(formatter)
        root.addHandler(handler)


def _handle_shutdown_signal(_signum: int, _frame: Any) -> None:
    """Route SIGTERM through main() so runner.stop() releases child processes."""
    raise KeyboardInterrupt


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(to_jsonable(payload), indent=2), encoding="utf-8")
    temporary.replace(path)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_size(label: str) -> int:
    token = label.strip().upper()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3}
    if not token:
        raise ValueError("file size must not be empty")
    return int(float(token[:-1]) * units[token[-1]]) if token[-1] in units else int(token)


def filename(label: str) -> str:
    return f"testfile_{label.upper()}"


def display_size_label(label: str) -> str:
    token = label.strip().upper()
    if token.endswith(("K", "M", "G")):
        return f"{token}B"
    return token


def percentile(values: list[float], percent: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile from no samples")
    position = (len(values) - 1) * percent / 100.0
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize no samples")
    return {"count": len(ordered), "min": ordered[0], "max": ordered[-1], "avg": sum(ordered) / len(ordered),
            "p50": percentile(ordered, 50), "p95": percentile(ordered, 95), "p99": percentile(ordered, 99)}


def summarize_ms(seconds: list[float]) -> dict[str, float | int | str]:
    result = summarize([sample * 1000.0 for sample in seconds])
    result["unit"] = "ms"
    return result


def require_executable(value: str) -> str:
    found = shutil.which(value)
    if found:
        return found
    path = Path(value)
    if path.exists() and os.access(path, os.X_OK):
        return str(path)
    raise FileNotFoundError(f"required executable not found: {value}")


def run_command(argv: list[str], timeout: float | None) -> subprocess.CompletedProcess[str]:
    logging.debug("Running command: %s", shlex.join(argv))
    return subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)


def sleep_for_rate(started: float, rate: float) -> None:
    if rate > 0:
        remaining = 1.0 / rate - (time.perf_counter() - started)
        if remaining > 0:
            time.sleep(remaining)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    parts: list[bytes] = []
    while size:
        part = sock.recv(size)
        if not part:
            raise ConnectionError("socket closed before receiving expected payload")
        parts.append(part)
        size -= len(part)
    return b"".join(parts)


def wait_for_http(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        result = run_command(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url], 2.0)
        if result.returncode == 0 and result.stdout.strip().startswith("2"):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for HTTP endpoint {url}: {result.stderr.strip()}")
        time.sleep(1.0)


def wait_for_tcp_echo(host: str, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    frame = struct.pack("!I", 5) + b"probe"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0) as sock:
                sock.settimeout(1.0)
                sock.sendall(frame)
                if recv_exact(sock, len(frame)) == frame:
                    return
                raise ConnectionError("endpoint did not return the TCP echo probe")
        except OSError as exc:
            last_error = exc
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for TCP echo endpoint {host}:{port}; last error={last_error}")


@dataclass
class ManagedProcess:
    name: str
    argv: list[str]
    log_path: Path
    process: subprocess.Popen[str] | None = None
    handle: Any = None

    def start(self) -> None:
        ensure_dir(self.log_path.parent)
        self.handle = self.log_path.open("a", encoding="utf-8")  # pylint: disable=consider-using-with
        logging.info("Starting %s: %s", self.name, shlex.join(self.argv))
        self.process = subprocess.Popen(  # pylint: disable=consider-using-with
            self.argv, stdout=self.handle, stderr=subprocess.STDOUT, text=True)

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            logging.info("Stopping %s (pid=%s)", self.name, self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.handle:
            self.handle.close()
            self.handle = None


class LogCursor:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _files(self) -> list[Path]:
        if self.root.is_dir():
            return sorted(item for item in self.root.rglob("*") if item.is_file())
        if self.root.exists():
            return [self.root]
        return []

    def mark(self) -> dict[Path, int]:
        return {item: item.stat().st_size for item in self._files()}

    def read_since(self, marks: dict[Path, int]) -> list[str]:
        lines: list[str] = []
        for item in self._files():
            with item.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(marks.get(item, 0))
                lines.extend(handle.readlines())
        return lines


def path_distribution(lines: list[str]) -> dict[str, Any]:
    samples: dict[str, list[float]] = defaultdict(list)
    latest: dict[str, float] = {}
    for line in lines:
        match = PATH_SHARE_RE.search(line)
        if match:
            kind, value = match.group("kind"), float(match.group("pct"))
            samples[kind].append(value)
            latest[kind] = value
    return {"latest_share_by_type": latest,
            "average_share_by_type": {key: sum(values) / len(values) for key, values in samples.items()},
            "snapshot_count": sum(len(values) for values in samples.values())}


class TcpEchoServer:
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.stop_event = threading.Event()
        self.socket: socket.socket | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        self.socket.settimeout(1.0)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        logging.info("TCP echo server listening on %s:%d", self.host, self.port)

    def _serve(self) -> None:
        assert self.socket is not None
        while not self.stop_event.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(connection,), daemon=True).start()

    def _client(self, connection: socket.socket) -> None:
        with connection:
            while not self.stop_event.is_set():
                try:
                    header = recv_exact(connection, 4)
                    size = struct.unpack("!I", header)[0]
                    payload = recv_exact(connection, size)
                    connection.sendall(header + payload)
                except (OSError, ConnectionError):
                    return

    def stop(self) -> None:
        self.stop_event.set()
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=2)


@dataclass
class ServerConfig:
    server_app_bin: str
    server_app_args: str
    dufs_bin: str
    listen_host: str
    share_dir: Path
    result_dir: Path
    dufs_port: int
    echo_port: int
    large_files: list[str]
    small_files: list[str]
    run_seconds: float


@dataclass
class ClientConfig:
    client_app_bin: str
    client_app_args: str
    launch_client_app: bool
    client_app_log: Path
    server_app_log: Path
    result_dir: Path
    http_base_url: str
    tcp_proxy_host: str
    tcp_proxy_port: int
    transfer_iterations: int
    http_request_rate: float
    http_request_count: int
    tcp_request_rate: float
    tcp_request_count: int
    tcp_ping_payload_size: int
    test_category: str
    large_files: list[str]
    small_files: list[str]
    startup_timeout: float
    path_setup_delay: float
    command_timeout: float


class ServerRunner:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.echo = TcpEchoServer(config.listen_host, config.echo_port)
        self.processes: list[ManagedProcess] = []

    def run(self) -> dict[str, Any]:
        ensure_dir(self.config.share_dir)
        for label in [*self.config.large_files, *self.config.small_files]:
            path = self.config.share_dir / filename(label)
            size = parse_size(label)
            if not path.exists() or path.stat().st_size != size:
                logging.info("Preparing %s (%d bytes)", path, size)
                path.write_bytes(b"")
                with path.open("r+b") as handle:
                    handle.truncate(size)
        self.echo.start()
        server_app = ManagedProcess("server_app",
                                    [require_executable(self.config.server_app_bin),
                                     *shlex.split(self.config.server_app_args)],
                                    self.config.result_dir / "server_app.log")
        dufs = ManagedProcess("dufs",
                              [require_executable(self.config.dufs_bin),
                               "--bind",
                               self.config.listen_host,
                               "--port",
                               str(self.config.dufs_port),
                                  "--allow-upload",
                                  str(self.config.share_dir)],
                              self.config.result_dir / "dufs.log")
        self.processes = [server_app, dufs]
        for process in self.processes:
            process.start()
        result = {
            "mode": "server",
            "started_at": utc_now(),
            "result_dir": str(
                self.config.result_dir),
            "share_dir": str(
                self.config.share_dir),
            "dufs_port": self.config.dufs_port,
            "echo_port": self.config.echo_port}
        write_json(self.config.result_dir / "server_metadata.json", result)
        logging.info("Server mode ready: %s", json.dumps(result, indent=2))
        try:
            if self.config.run_seconds:
                time.sleep(self.config.run_seconds)
            else:
                while all(process.running() for process in self.processes):
                    time.sleep(1)
        finally:
            result["stopped_at"] = utc_now()
            write_json(self.config.result_dir / "server_metadata.json", result)
        return result

    def stop(self) -> None:
        self.echo.stop()
        for process in reversed(self.processes):
            process.stop()


class ClientRunner:
    def __init__(self, config: ClientConfig) -> None:
        self.config = config
        self.client_app: ManagedProcess | None = None
        self.started_at: float | None = None
        self.server_app_log_cursor = LogCursor(config.server_app_log)

    def _http_selected(self) -> bool:
        return self.config.test_category in (
            TEST_CATEGORY_ALL,
            TEST_CATEGORY_GOODPUT,
            TEST_CATEGORY_LATENCY,
            TEST_CATEGORY_HTTP_LATENCY)

    def _goodput_selected(self) -> bool:
        return self.config.test_category in (TEST_CATEGORY_ALL, TEST_CATEGORY_GOODPUT)

    def _http_latency_selected(self) -> bool:
        return self.config.test_category in (TEST_CATEGORY_ALL, TEST_CATEGORY_LATENCY, TEST_CATEGORY_HTTP_LATENCY)

    def _tcp_selected(self) -> bool:
        return self.config.test_category == TEST_CATEGORY_TCP_LATENCY

    def run(self) -> dict[str, Any]:
        ensure_dir(self.config.result_dir)
        self._start_client_app()
        self._wait_for_paths()
        if self._tcp_selected():
            logging.info(
                "Waiting for TCP ping-pong tunnel at %s:%d",
                self.config.tcp_proxy_host,
                self.config.tcp_proxy_port)
            wait_for_tcp_echo(self.config.tcp_proxy_host, self.config.tcp_proxy_port, DEFAULT_PROXY_READY_TIMEOUT)
        else:
            ready = urljoin(self.config.http_base_url.rstrip("/") + "/", filename(self.config.small_files[0]))
            logging.info("Waiting for HTTP proxy to become ready at %s", ready)
            wait_for_http(ready, DEFAULT_PROXY_READY_TIMEOUT)
        result: dict[str,
                     Any] = {"mode": "client",
                             "started_at": utc_now(),
                             "result_dir": str(self.config.result_dir),
                             "config": {"test_category": self.config.test_category,
                                        "http_base_url": self.config.http_base_url,
                                        "tcp_proxy_host": self.config.tcp_proxy_host,
                                        "tcp_proxy_port": self.config.tcp_proxy_port,
                                        "transfer_iterations": self.config.transfer_iterations,
                                        "http_request_count": self.config.http_request_count,
                                        "tcp_request_count": self.config.tcp_request_count}}
        if self._goodput_selected():
            result["goodput"] = {"http_download": self._logged("HTTP download goodput", self._downloads)}
        if self._http_latency_selected():
            result["latency"] = {"http_request": self._logged("HTTP request latency", self._http_latency)}
        if self._tcp_selected():
            result["tcp_latency"] = {"tcp_ping": self._logged("TCP ping-pong/message latency", self._tcp_ping)}
        result["finished_at"] = utc_now()
        write_json(self.config.result_dir / "summary.json", result)
        logging.info("Wrote benchmark summary to %s", self.config.result_dir / "summary.json")
        return result

    def _start_client_app(self) -> None:
        if not self.config.launch_client_app:
            return
        output = self.config.result_dir / "client_app.log"
        argv = [require_executable(self.config.client_app_bin), *shlex.split(self.config.client_app_args)]
        last_returncode: int | None = None
        for attempt in range(1, 3):
            self.client_app = ManagedProcess("client_app", argv, output)
            self.client_app.start()
            self.started_at = time.monotonic()
            time.sleep(1)
            if self.client_app.running():
                if attempt > 1:
                    logging.info("client_app started successfully after retry")
                return

            last_returncode = self.client_app.process.returncode if self.client_app.process else None
            self.client_app.stop()
            if attempt == 1:
                logging.warning("client_app exited immediately after startup, retrying once")
                time.sleep(1)

        raise RuntimeError(f"client_app exited immediately after startup after retry, returncode={last_returncode}")

    def _wait_for_paths(self) -> None:
        if self.started_at is not None:
            remaining = self.config.path_setup_delay - (time.monotonic() - self.started_at)
            if remaining > 0:
                logging.info("Waiting %.1fs before starting client tests to allow paths to settle", remaining)
                time.sleep(remaining)

    def _logged(self, name: str, callback: Callable[[], Any]) -> Any:
        started = time.perf_counter()
        logging.info("Starting test: %s", name)
        try:
            result = callback()
        except Exception as exc:
            logging.exception("Failed test: %s in %.3fs", name, time.perf_counter() - started)
            return {"status": "failed", "duration_seconds": time.perf_counter() - started, "error": str(exc),
                    "error_type": type(exc).__name__}
        if isinstance(result, dict):
            result["status"] = "passed"
            result["duration_seconds"] = time.perf_counter() - started
        logging.info("Finished test: %s in %.3fs", name, time.perf_counter() - started)
        return result

    def _progress(self, name: str, iteration: int, total: int) -> None:
        step = 1 if total <= 20 else max(1, total // 10)
        if iteration == 1 or iteration == total or iteration % step == 0:
            logging.info("Testing progress: %s %d/%d", name, iteration, total)

    def _downloads(self) -> dict[str, Any]:
        if not self.config.server_app_log.exists():
            logging.warning(
                "server endpoint log %s is unavailable; HTTP-download path PCT will be empty. "
                "Set --server-app-log to the sender log path.",
                self.config.server_app_log,
            )
        suite: dict[str, Any] = {}
        for label in self.config.large_files:
            display_label = display_size_label(label)
            rows: list[dict[str, Any]] = []
            # HTTP downloads flow from dufs through the server endpoint to the
            # client endpoint. Path PCT belongs to the sender endpoint.
            mark = self.server_app_log_cursor.mark()
            for iteration in range(1, self.config.transfer_iterations + 1):
                self._progress(f"HTTP download {display_label}", iteration, self.config.transfer_iterations)
                response = run_command(["curl",
                                        "-sS",
                                        "-o",
                                        "/dev/null",
                                        "-w",
                                        "%{speed_download} %{time_total} %{http_code}",
                                        urljoin(self.config.http_base_url.rstrip("/") + "/",
                                                filename(label))],
                                       None)
                if response.returncode:
                    raise RuntimeError(f"download {display_label} iteration {iteration}: {response.stderr.strip()}")
                match = HTTP_METRIC_RE.match(response.stdout.strip())
                if not match or int(match.group("code")) >= 400:
                    raise RuntimeError(f"invalid download response: {response.stdout!r}")
                rows.append({"iteration": iteration,
                             "speed_bytes_per_sec": float(match.group("speed")),
                             "duration_seconds": float(match.group("time")),
                             "http_status": int(match.group("code"))})
            speeds, durations = [row["speed_bytes_per_sec"] for row in rows], [row["duration_seconds"] for row in rows]
            duration_summary = summarize(durations)
            goodput_svg = self.config.result_dir / f"http_{label}_goodput_summary.svg"
            paths = path_distribution(self.server_app_log_cursor.read_since(mark))
            write_goodput_summary_svg(
                goodput_svg,
                display_label,
                sum(speeds) / len(speeds) / 1024 / 1024,
                len(rows),
                paths["latest_share_by_type"],
                durations,
                duration_summary,
            )
            suite[filename(label)] = {
                "iterations": rows,
                "average_speed_bytes_per_sec": sum(speeds) / len(speeds),
                "average_duration_seconds": sum(durations) / len(durations),
                "speed_summary": summarize(speeds),
                "duration_summary": duration_summary,
                "path_distribution": paths,
                "goodput_summary_svg": str(goodput_svg),
            }
        return suite

    def _http_latency(self) -> dict[str, Any]:
        suite: dict[str, Any] = {}
        for label in self.config.small_files:
            display_label = display_size_label(label)
            rows: list[dict[str, Any]] = []
            for iteration in range(1, self.config.http_request_count + 1):
                self._progress(f"HTTP request latency {display_label}", iteration, self.config.http_request_count)
                started = time.perf_counter()
                response = run_command(["curl",
                                        "-sS",
                                        "-o",
                                        "/dev/null",
                                        "-w",
                                        "%{time_total} %{http_code}",
                                        urljoin(self.config.http_base_url.rstrip("/") + "/",
                                                filename(label))],
                                       self.config.command_timeout)
                if response.returncode:
                    raise RuntimeError(f"HTTP latency {display_label} iteration {iteration}: {response.stderr.strip()}")
                parts = response.stdout.split()
                if len(parts) != 2 or int(parts[1]) >= 400:
                    raise RuntimeError(f"invalid HTTP latency response: {response.stdout!r}")
                rows.append({"iteration": iteration, "duration_seconds": float(parts[0]), "http_status": int(parts[1])})
                sleep_for_rate(started, self.config.http_request_rate)
            suite[filename(label)] = self._latency_result(
                f"http_{label}_latency", f"HTTP request latency {display_label}", rows)
        return suite

    def _tcp_proxy(self) -> socket.socket:
        sock = socket.create_connection(
            (self.config.tcp_proxy_host,
             self.config.tcp_proxy_port),
            timeout=self.config.command_timeout)
        sock.settimeout(self.config.command_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    def _tcp_ping(self) -> dict[str, Any]:
        payload = b"x" * self.config.tcp_ping_payload_size
        frame = struct.pack("!I", len(payload)) + payload
        rows: list[dict[str, Any]] = []
        with self._tcp_proxy() as sock:
            for iteration in range(1, self.config.tcp_request_count + 1):
                self._progress("TCP ping-pong", iteration, self.config.tcp_request_count)
                started = time.perf_counter()
                sock.sendall(frame)
                if recv_exact(sock, len(frame)) != frame:
                    raise ConnectionError("TCP echo response did not match request")
                rows.append({"iteration": iteration, "duration_seconds": time.perf_counter() - started})
                sleep_for_rate(started, self.config.tcp_request_rate)
        result = self._latency_result("tcp_ping_pong_latency", "TCP ping-pong/message latency", rows)
        result["payload_size_bytes"] = self.config.tcp_ping_payload_size
        return result

    def _latency_result(self, stem: str, title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary = summarize_ms([float(row["duration_seconds"]) for row in rows])
        raw = self.config.result_dir / f"{stem}_raw.json"
        svg = self.config.result_dir / f"{stem}_distribution.svg"
        write_json(raw, {"title": title, "unit": "ms", "samples": rows})
        write_latency_svg(svg, title, [float(row["duration_seconds"]) * 1000 for row in rows], summary)
        logging.info("%s result: avg %.3fms p95 %.3fms p99 %.3fms", title,
                     summary["avg"], summary["p95"], summary["p99"])
        return {"iterations": rows, "summary": summary, "duration_summary_seconds": summarize(
            [float(row["duration_seconds"]) for row in rows]), "raw_data_file": str(raw), "distribution_svg": str(svg)}

    def stop(self) -> None:
        if self.client_app:
            self.client_app.stop()


def write_latency_svg(
    path: Path,
    title: str,
    samples: list[float],
    summary: dict[str, Any],
    *,
    x_label: str = "Latency (ms)",
    unit: str = "ms",
) -> None:
    values = sorted(samples)
    minimum, maximum = values[0], values[-1]
    padding = max((maximum - minimum) * 0.05, 0.001)
    x_min, x_max = minimum - padding, maximum + padding
    width, height, left, right, top, bottom = 960, 520, 86, 28, 72, 76
    chart_width, chart_height = width - left - right, height - top - bottom
    def x(value):
        return left + (value - x_min) / (x_max - x_min) * chart_width

    def y(percent):
        return top + chart_height - percent / 100 * chart_height
    points = [f"{x(values[0]):.2f},{y(0):.2f}"] + \
        [f"{x(value):.2f},{y(index * 100 / len(values)):.2f}" for index, value in enumerate(values, 1)]
    colours = {"p50": "#2f855a", "p95": "#d97706", "p99": "#c53030"}
    marks = []
    for name in ("p50", "p95", "p99"):
        value, percent, colour = float(summary[name]), float(name[1:]), colours[name]
        x_value = f"{x(value):.2f}"
        y_value = f"{y(percent):.2f}"
        marks.append(
            f'<circle cx="{x_value}" cy="{y_value}" r="5" '
            f'fill="{colour}" stroke="white" stroke-width="2"/>')
        label_y = f"{y(percent) - 10:.2f}"
        marks.append(
            f'<text x="{x_value}" y="{label_y}" text-anchor="middle" '
            f'fill="{colour}" font-size="13">{name} {value:.3f} '
            f'{html.escape(unit)}</text>')
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}"
 height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <text x="480" y="30" text-anchor="middle" font-family="sans-serif" font-size="20">{html.escape(title)}</text>
  <text x="480" y="52" text-anchor="middle" font-family="sans-serif"
 font-size="13" fill="#52606d">{len(values)} samples; cumulative distribution</text>
  <line x1="{left}" y1="{y(50):.2f}" x2="{left + chart_width}"
 y2="{y(50):.2f}" stroke="#d9e2ec" stroke-dasharray="4 4"/>
  <line x1="{left}" y1="{y(95):.2f}" x2="{left + chart_width}"
 y2="{y(95):.2f}" stroke="#d9e2ec" stroke-dasharray="4 4"/>
  <line x1="{left}" y1="{top + chart_height}" x2="{left + chart_width}" y2="{top + chart_height}" stroke="#52606d"/>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_height}" stroke="#52606d"/>
  <polyline points="{' '.join(points)}" fill="none" stroke="#3b82b6" stroke-width="2"/>
  {''.join(marks)}
  <text x="{left}" y="{top + chart_height + 24}" font-family="sans-serif"
 font-size="13">{x_min:.3f} {html.escape(unit)}</text>
  <text x="{left + chart_width}" y="{top + chart_height + 24}"
 text-anchor="end" font-family="sans-serif" font-size="13">{x_max:.3f} {html.escape(unit)}</text>
  <text x="{left - 10}" y="{y(0):.2f}" text-anchor="end" font-family="sans-serif" font-size="13">0%</text>
  <text x="{left - 10}" y="{y(50):.2f}" text-anchor="end" font-family="sans-serif" font-size="13">50%</text>
  <text x="{left - 10}" y="{y(100):.2f}" text-anchor="end" font-family="sans-serif" font-size="13">100%</text>
  <text x="480" y="502" text-anchor="middle" font-family="sans-serif" font-size="14">{html.escape(x_label)}</text>
  <text x="22" y="258" transform="rotate(-90 22 258)" text-anchor="middle" font-family="sans-serif" font-size="14">Accumulated samples (%)</text>
</svg>\n'''
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


# pylint: disable=too-many-positional-arguments
def write_goodput_summary_svg(
    path: Path,
    label: str,
    average_mb_per_sec: float,
    repeats: int,
    latest_path_pct: dict[str, float],
    completion_times: list[float],
    completion_summary: dict[str, float | int],
) -> None:
    width, height = 960, 720
    bars: list[str] = []
    labels: list[str] = []
    path_items = sorted(latest_path_pct.items())
    if path_items:
        max_bar_width = 350.0
        for index, (path_type, percent) in enumerate(path_items):
            bar_y = 160 + index * 52
            bar_width = max(0.0, min(100.0, percent)) / 100.0 * max_bar_width
            colour = ("#2f855a" if path_type.upper().startswith("D") else
                      "#c53030" if path_type.upper().startswith("R") else "#3b82b6")
            bars.append(f'<rect x="550" y="{bar_y}" width="{bar_width:.2f}" height="28" fill="{colour}"/>')
            labels.append(
                f'<text x="540" y="{bar_y + 20}" text-anchor="end" font-size="14">{html.escape(path_type)}</text>'
                f'<text x="{560 + bar_width:.2f}" y="{bar_y + 20}" font-size="14">{percent:.2f}%</text>'
            )
    else:
        labels.append(
            '<text x="720" y="210" text-anchor="middle" font-size="14" '
            'fill="#52606d">No final path PCT found in server endpoint logs</text>')
    durations = sorted(completion_times)
    minimum, maximum = durations[0], durations[-1]
    padding = max((maximum - minimum) * 0.05, 0.001)
    x_min, x_max = minimum - padding, maximum + padding
    chart_left, chart_right, chart_top, chart_bottom = 92, 900, 460, 650
    chart_width, chart_height = chart_right - chart_left, chart_bottom - chart_top
    def x(value):
        return chart_left + (value - x_min) / (x_max - x_min) * chart_width

    def y(percent):
        return chart_bottom - percent / 100.0 * chart_height
    points = [f"{x(durations[0]):.2f},{y(0):.2f}"] + [
        f"{x(value):.2f},{y(index * 100.0 / len(durations)):.2f}"
        for index, value in enumerate(durations, 1)
    ]
    percentile_marks: list[str] = []
    colours = {"p50": "#2f855a", "p95": "#d97706", "p99": "#c53030"}
    for name in ("p50", "p95", "p99"):
        value, percent, colour = float(completion_summary[name]), float(name[1:]), colours[name]
        x_value = f"{x(value):.2f}"
        y_value = f"{y(percent):.2f}"
        percentile_marks.append(
            f'<circle cx="{x_value}" cy="{y_value}" r="5" '
            f'fill="{colour}" stroke="white" stroke-width="2"/>')
        label_y = f"{y(percent) - 9:.2f}"
        percentile_marks.append(
            f'<text x="{x_value}" y="{label_y}" text-anchor="middle" '
            f'fill="{colour}" font-size="12">{name} {value:.3f}s</text>')
    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}"
 height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <text x="480" y="34" text-anchor="middle" font-family="sans-serif"
 font-size="20">HTTP download {html.escape(label)}</text>
  <line x1="480" y1="74" x2="480" y2="386" stroke="#cbd5e0"/>
  <text x="240" y="122" text-anchor="middle" font-family="sans-serif"
 font-size="15" fill="#52606d">Average goodput ({repeats} downloads)</text>
  <text x="240" y="188" text-anchor="middle" font-family="sans-serif"
 font-size="40" fill="#1f2933">{average_mb_per_sec:.2f}</text>
  <text x="240" y="218" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#52606d">MB/s</text>
  <text x="240" y="286" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#52606d">Average completion time</text>
  <text x="240" y="344" text-anchor="middle" font-family="sans-serif"
 font-size="36" fill="#1f2933">{float(completion_summary["avg"]):.3f}</text>
  <text x="240" y="374" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#52606d">s</text>
  <text x="720" y="112" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#52606d">Final path PCT</text>
  <line x1="550" y1="142" x2="900" y2="142" stroke="#9fb3c8"/>
  <text x="550" y="132" font-family="sans-serif" font-size="12" fill="#52606d">0%</text>
  <text x="900" y="132" text-anchor="end" font-family="sans-serif" font-size="12" fill="#52606d">100%</text>
  {''.join(bars)}
  {''.join(labels)}
  <line x1="60" y1="410" x2="900" y2="410" stroke="#cbd5e0"/>
  <text x="480" y="442" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#1f2933">Download completion-time CDF</text>
  <line x1="{chart_left}" y1="{chart_top}" x2="{chart_left}" y2="{chart_bottom}" stroke="#52606d"/>
  <line x1="{chart_left}" y1="{chart_bottom}" x2="{chart_right}" y2="{chart_bottom}" stroke="#52606d"/>
  <line x1="{chart_left}" y1="{y(50):.2f}" x2="{chart_right}" y2="{y(50):.2f}" stroke="#d9e2ec" stroke-dasharray="4 4"/>
  <line x1="{chart_left}" y1="{y(95):.2f}" x2="{chart_right}" y2="{y(95):.2f}" stroke="#d9e2ec" stroke-dasharray="4 4"/>
  <polyline points="{' '.join(points)}" fill="none" stroke="#3b82b6" stroke-width="2"/>
  {''.join(percentile_marks)}
  <text x="{chart_left}" y="{chart_bottom + 24}" font-family="sans-serif" font-size="12">{x_min:.3f}s</text>
  <text x="{chart_right}" y="{chart_bottom + 24}" text-anchor="end"
 font-family="sans-serif" font-size="12">{x_max:.3f}s</text>
  <text x="{chart_left - 10}" y="{y(0):.2f}" text-anchor="end" font-family="sans-serif" font-size="12">0%</text>
  <text x="{chart_left - 10}" y="{y(50):.2f}" text-anchor="end" font-family="sans-serif" font-size="12">50%</text>
  <text x="{chart_left - 10}" y="{y(100):.2f}" text-anchor="end" font-family="sans-serif" font-size="12">100%</text>
  <text x="480" y="690" text-anchor="middle" font-family="sans-serif" font-size="13">Download completion time (s)</text>
  <text x="22" y="555" transform="rotate(-90 22 555)" text-anchor="middle" font-family="sans-serif" font-size="13">Accumulated samples (%)</text>
</svg>\n'''
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Generic HTTP benchmark helper")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="mode")
    server = commands.add_parser("server")
    server.add_argument("--server-app-bin", default="server_app")
    server.add_argument("--server-app-args", default=DEFAULT_SERVER_APP_ARGS)
    server.add_argument("--dufs-bin", default="dufs")
    server.add_argument("--listen-host", default="0.0.0.0")
    server.add_argument("--share-dir", default=DEFAULT_SERVER_SHARE_DIR)
    server.add_argument("--dufs-port", type=int, default=DEFAULT_DUFS_PORT)
    server.add_argument("--echo-port", type=int, default=DEFAULT_ECHO_PORT)
    server.add_argument("--large-files", default=",".join(DEFAULT_LARGE_FILES))
    server.add_argument("--small-files", default=",".join(DEFAULT_SMALL_FILES))
    server.add_argument("--run-seconds", type=float, default=0.0)
    server.add_argument(
        "--result-dir",
        default=os.path.join(
            DEFAULT_SERVER_RESULT_BASE,
            datetime.now().strftime("%Y%m%d-%H%M%S")))
    client = commands.add_parser("client")
    client.add_argument("--client-app-bin", default="client_app")
    client.add_argument("--client-app-args", default="")
    client.add_argument("--reuse-existing-client-app", action="store_true")
    client.add_argument("--client-app-log", default=DEFAULT_CLIENT_APP_LOG)
    client.add_argument("--server-app-log", default=DEFAULT_SERVER_APP_LOG,
                        help="sender endpoint log used to collect HTTP-download path PCT")
    client.add_argument(
        "--result-dir",
        default=os.path.join(
            DEFAULT_CLIENT_RESULT_BASE,
            datetime.now().strftime("%Y%m%d-%H%M%S")))
    client.add_argument("--http-base-url", default=f"http://localhost:{DEFAULT_HTTP_PORT}")
    client.add_argument("--tcp-proxy-host", "--echo-host", dest="tcp_proxy_host", default="localhost")
    client.add_argument("--tcp-proxy-port", "--echo-port", dest="tcp_proxy_port", type=int, default=DEFAULT_HTTP_PORT)
    client.add_argument("--transfer-iterations", type=int, default=DEFAULT_TRANSFER_ITERATIONS)
    client.add_argument("--http-request-rate", type=float, default=DEFAULT_HTTP_REQUEST_RATE)
    client.add_argument("--http-request-count", type=int, default=DEFAULT_HTTP_REQUEST_COUNT)
    client.add_argument("--tcp-request-rate", type=float, default=DEFAULT_TCP_REQUEST_RATE)
    client.add_argument("--tcp-request-count", type=int, default=DEFAULT_TCP_REQUEST_COUNT)
    client.add_argument("--tcp-ping-payload-size", type=int, default=DEFAULT_TCP_PING_PAYLOAD_SIZE)
    client.add_argument(
        "--test-category",
        choices=(
            TEST_CATEGORY_ALL,
            TEST_CATEGORY_GOODPUT,
            TEST_CATEGORY_LATENCY,
            TEST_CATEGORY_HTTP_LATENCY,
            TEST_CATEGORY_TCP_LATENCY),
        default=TEST_CATEGORY_ALL)
    client.add_argument("--large-files", default=",".join(DEFAULT_LARGE_FILES))
    client.add_argument("--small-files", default=",".join(DEFAULT_SMALL_FILES))
    client.add_argument("--startup-timeout", type=float, default=60.0)
    client.add_argument("--path-setup-delay", type=float, default=DEFAULT_PATH_SETUP_DELAY)
    client.add_argument("--command-timeout", type=float, default=300.0)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.mode:
        return 2
    configure_logging(args.verbose)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    benchmark_started = time.perf_counter()
    try:
        if args.mode == "server":
            runner: ServerRunner | ClientRunner = ServerRunner(
                ServerConfig(
                    args.server_app_bin, args.server_app_args, args.dufs_bin, args.listen_host, Path(
                        args.share_dir), Path(
                        args.result_dir), args.dufs_port, args.echo_port, split_csv(
                        args.large_files), split_csv(
                        args.small_files), args.run_seconds))
        else:
            runner = ClientRunner(
                ClientConfig(
                    args.client_app_bin,
                    args.client_app_args,
                    not args.reuse_existing_client_app,
                    Path(
                        args.client_app_log),
                    Path(
                        args.server_app_log),
                    Path(
                        args.result_dir),
                    args.http_base_url,
                    args.tcp_proxy_host,
                    args.tcp_proxy_port,
                    args.transfer_iterations,
                    args.http_request_rate,
                    args.http_request_count,
                    args.tcp_request_rate,
                    args.tcp_request_count,
                    args.tcp_ping_payload_size,
                    args.test_category,
                    split_csv(
                        args.large_files),
                    split_csv(
                        args.small_files),
                    args.startup_timeout,
                    args.path_setup_delay,
                    args.command_timeout))
        try:
            result = runner.run()
        finally:
            runner.stop()
    except KeyboardInterrupt:
        logging.info("http_benchmark interrupted")
        return 130
    except Exception as exc:
        logging.error("http_benchmark failed: %s", exc)
        return 1
    logging.info("Benchmark result saved under %s", result.get("result_dir"))
    logging.info("Benchmark completed in %.3fs", time.perf_counter() - benchmark_started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
