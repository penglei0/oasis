#!/bin/sh
set -eu

[ "${1:-}" = "server" ] || [ "${1:-}" = "client" ] || {
    echo "usage: regular_test.sh {server|client} RESULT_DIR" >&2
    exit 2
}
[ -n "${2:-}" ] || { echo "RESULT_DIR is required" >&2; exit 2; }

result_dir="$2/$1"
mkdir -p "$result_dir"

if [ "$1" = "server" ]; then
    echo "Starting HTTP latency benchmark server..."
    exec python3 /usr/bin/http_benchmark.py server --server-app-bin app_server --server-app-args "" --result-dir "$result_dir"
elif [ "$1" = "client" ]; then
    echo "Starting HTTP latency benchmark client..."
    exec python3 /usr/bin/http_benchmark.py client --client-app-bin app_client --test-category http-latency --small-files "10K,50K" --http-request-count 100 --result-dir "$result_dir"
else
    echo "Invalid argument: $1" >&2
    exit 2
fi
