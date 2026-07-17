# Benchmark Test Suite

## Benchmark Metrics
- 1. file download speed (avg) for 20MB, 20 times each
- 2. file download completion time (avg) for 20MB, 20 times each
- 3. flow distribution on different paths for 1/2.
- 4. P50/P95/P99 distribution of HTTP request time (10K, 50K, 10/s, 100 times by default)

> 1000B * 100/s = 100KB/s = 0.8Mbps
> 10KB * 10/s = 100KB/s = 0.8Mbps
> 50KB * 10/s = 500KB/s = 4Mbps

## Benchmark helper: http_benchmark.py

### Purpose

`src/tools/http_benchmark.py` is a generic HTTP goodput and latency
measurement tool. It measures HTTP file-download throughput and completion
time, HTTP request latency percentiles, and optionally TCP message latency.
It is not tied to NAS products. The current multipath and single-path Oasis
tests are one special deployment of this tool.

### Dependencies and endpoint applications

The tool does not implement the endpoint services itself. It requires:

- an HTTP file server such as `dufs`, serving the test files;
- a server-side endpoint application that forwards traffic to the client-side
  endpoint application;
- a client-side endpoint application that exposes the local HTTP/TCP proxy
  ports used by the benchmark.

`app_server` and `app_client` are the current endpoint applications used by the
Oasis profiles, but any pair of applications with the same port-forwarding
pattern can replace them. The endpoint binaries are selected with
`--server-app-bin` and `--client-app-bin`; their arguments are selected with
`--server-app-args` and `--client-app-args`.

To setup the correct endpoint applications, do changes to the following scripts:
```bash
test/rootfs/usr/bin/regular_benchmark_http_latency.sh
test/rootfs/usr/bin/regular_benchmark_http_goodput.sh
```

### Data flow

For an HTTP download, the data flow is:

```text
dufs :9999 on server
        |
server endpoint application
        |  forwarded tunnel
client endpoint application :9443 on client
        |
http_benchmark.py -> curl -> local proxy URL
```

The server mode starts the server endpoint and `dufs`. Client mode starts the
client endpoint, waits for the proxy to become ready, then issues the HTTP
requests. For a TCP latency test, the same endpoint pair forwards the local
TCP proxy port to a TCP echo service.

### Standalone usage examples

Start the endpoint applications and `dufs` according to the deployment, then
run the benchmark with the generic binary names. For HTTP latency using 10KB
and 50KB files:

```bash
python3 /usr/bin/http_benchmark.py server \
  --server-app-bin server_app \
  --dufs-port 9999 \
  --result-dir /tmp/http-benchmark/server
python3 /usr/bin/http_benchmark.py client \
  --client-app-bin client_app \
  --server-app-log /tmp/http-benchmark/server/server_app.log \
  --test-category http-latency \
  --small-files "10K,50K" \
  --http-request-count 1000 \
  --result-dir /tmp/http-benchmark/client
```

For goodput, select one or more file sizes. Each file is downloaded for the
configured number of iterations, which defaults to 20:

```bash
python3 /usr/bin/http_benchmark.py client \
  --client-app-bin client_app \
  --test-category goodput \
  --large-files "10M,20M" \
  --transfer-iterations 20 \
  --result-dir /tmp/http-benchmark/client
```

The client writes raw samples, summary JSON, and SVG charts to its result
directory. `--test-category all`, `goodput`, `http-latency`, or
`tcp-latency` selects the measurement category.

### Proxy log contract for path PCT

Path percentage analysis is optional and only applies when the sender
endpoint log is supplied with `--server-app-log`. To support final path PCT
analysis, the server-side endpoint should emit one parseable line per path
snapshot containing the path type, path ID, CID, and `PCT(s): <number>%`.
For example:

```text
[R]Path ID:0,CID:17ba78fbf10e71b1,Sent: 433,Recv: 1610,PCT(s):48.86%
[D]Path ID:1,CID:17ba78fbf10e71b1,Sent: 419,Recv: 1597,PCT(s):51.14%
```

The parser recognizes the first bracket as the path type (`R` or `D`), the
`Path ID` value, and the final `PCT(s):` value. A replacement endpoint should
keep these tokens stable, write complete lines atomically, and emit a fresh
snapshot after the transfer completes. The benchmark reads new log data after
each test, retries the final snapshot briefly, and uses the latest percentage
for the goodput summary. If the log format is not provided, throughput and
completion time still work, but the path PCT section is empty.

## Benchmark report

### Static HTML report

After the multipath and single-path benchmark runs complete, generate a
matrix index and per-setup result pages with:

```bash
python3 src/tools/generate_http_benchmark_report.py \
  --results-dir test_results \
  --output-dir test_results/http_benchmark_report
```

Open `test_results/http_benchmark_report/index.html`. Rows represent
`rpath` setups and columns represent `dpath` setups. Each selected setup page
contains the multipath HTTP goodput and latency SVGs, matching single-path
results selected by `dpath`, and category-qualified links to the client/server
logs and wrapper logs.

### Deploy the HTML report with Nginx

See details in [Deploy](../test_results/README.md);
