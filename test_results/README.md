## Deploy the HTML report with Nginx

The generated report can be served by the provided
`test_results/Dockerfile.nginx`. Generate the report first, then
build the image with `test_results` as the Docker build context:

```bash
cd test_results
docker build -f /Dockerfile.nginx \
  -t http-benchmark-report-nginx .
```

Run Nginx on host port `9991`:

```bash
docker run -d --name http-benchmark-report \
  -p 9991:80 \
  -v http-benchmark-visitors:/var/lib/http-benchmark \
  http-benchmark-report-nginx
```

Open `http://127.0.0.1:9991/`. To replace the report after another test run,
regenerate `test_results/http_benchmark_report`, rebuild the image, and replace
the container:

```bash
docker rm -f http-benchmark-report
docker build -f test_results/Dockerfile.nginx \
  -t http-benchmark-report-nginx test_results
docker run -d --name http-benchmark-report \
  -p 9991:80 \
  -v http-benchmark-visitors:/var/lib/http-benchmark \
  http-benchmark-report-nginx
```

The report calls `/visitor-count?increment=1` once when `index.html` opens.
The Nginx container proxies this endpoint to the local counter service, which
stores the server-local count in `/var/lib/http-benchmark/visitor_count.json`.
The Docker volume preserves the count when the report container is replaced.

Each report generation also copies `test_results/oasis.log` into the report
directory and adds an `Oasis execution log (oasis.log)` link at the bottom of
`index.html`. Since `Dockerfile.nginx` copies the complete
`http_benchmark_report` directory, rebuilding the image packages the latest log.
