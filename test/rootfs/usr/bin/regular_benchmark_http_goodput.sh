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
    exec python3 /usr/bin/http_benchmark.py server --server-app-bin app_server --server-app-args "" --large-files "20M" --result-dir "$result_dir"
elif [ "$1" = "client" ]; then
    exec python3 /usr/bin/http_benchmark.py client --client-app-bin app_client --server-app-log "$2/server/server_app.log" --test-category goodput --result-dir "$result_dir"
else
    echo "Invalid argument: $1" >&2
    exit 2
fi
