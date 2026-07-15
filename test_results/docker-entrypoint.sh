#!/bin/sh
set -eu

mkdir -p /var/lib/http-benchmark
python3 /opt/http-benchmark/visitor_counter.py &
exec nginx -g 'daemon off;'
