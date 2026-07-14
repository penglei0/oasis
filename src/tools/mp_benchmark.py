#!/usr/bin/env python3
"""Multipath HTTP goodput and latency benchmark helper."""

from __future__ import annotations

import logging
import signal
import argparse
import os
from datetime import datetime
from typing import Any


DEFAULT_BENCHMARK_LOG = "/root/mp_benchmark.log"
DEFAULT_CLIENT_RESULT_BASE = "/root/mp_benchmark-results"
DEFAULT_SERVER_RESULT_BASE = "/root/mp_benchmark-server-results"

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

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Multipath benchmark helper")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="mode")
    server = commands.add_parser("server")
    server.add_argument("--result-dir", 
                        default=os.path.join(DEFAULT_SERVER_RESULT_BASE, 
                                             datetime.now().strftime("%Y%m%d-%H%M%S")))
    client = commands.add_parser("client")
    client.add_argument("--result-dir", 
                        default=os.path.join(DEFAULT_CLIENT_RESULT_BASE, 
                                             datetime.now().strftime("%Y%m%d-%H%M%S")))
    return root


def main(argv: list[str] | None = None) -> int:
    logging.info("Benchmark tool started")
    args = parser().parse_args(argv)
    if not args.mode:
        return 2
    configure_logging(args.verbose)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    try:
        if args.mode == "server":
            logging.info("Starting benchmark server, results will be saved under %s", args.result_dir)
        else:
            logging.info("Starting benchmark client, results will be saved under %s", args.result_dir)
    except KeyboardInterrupt:
        logging.info("mp_benchmark interrupted")
        return 130
    except Exception as exc:
        logging.error("mp_benchmark failed: %s", exc)
        return 1
    logging.info("Benchmark result saved under %s", args.result_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
