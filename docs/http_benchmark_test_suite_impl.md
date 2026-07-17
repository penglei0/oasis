# Benchmark Test Suite

`benchmark` is a role-based Oasis suite.
It does not resolve peer IP addresses or forwarded ports. Oasis only selects
the two nodes, invokes `/usr/bin/regular_test.sh server` on the server node,
then invokes `/usr/bin/regular_test.sh client` on the client node.

## Benchmark profile call chain

Node initialization and benchmark profile installation are separate phases.
The node initializer performs common setup once and selects which profile
installer is exposed through the stable
`/usr/sbin/install_benchmark_profile.sh` path. It does not install an
individual HTTP benchmark profile.

### Node initialization

For a regular node, `init_node.sh` selects the regular installer:

```text
init_node.sh
  |
  +-- install_benchmark_profile.sh
        -> install_regular_benchmark_profile.sh
```

The common initializer uses `/run/oasis/node_initialized` only to prevent
duplicate node setup such as SSH initialization. Benchmark variant state is
not stored in this marker.

The relevant scripts are:

| Script                                           | Responsibility                                              |
| ------------------------------------------------ | ----------------------------------------------------------- |
| `/usr/sbin/init_node.sh`                         | Perform common node setup and select the regular installer. |
| `/usr/sbin/install_benchmark_profile.sh`         | Stable symlink used by the test suite.                      |
| `/usr/sbin/install_regular_benchmark_profile.sh` | Install a regular profile template.                         |

### Profile installation and test execution

The YAML `benchmark.profile` value is parsed by `RegularBenchmarkTest`. Before
starting either role, the suite invokes the stable installer on both nodes:

```sh
/usr/sbin/install_benchmark_profile.sh http_latency
/usr/sbin/install_benchmark_profile.sh http_goodput
```

The selected installer validates the profile and atomically copies the
matching template to `/usr/bin/regular_test.sh`:

| Node type | Profile        | Selected template                               |
| --------- | -------------- | ----------------------------------------------- |
| Regular   | `http_latency` | `/usr/bin/regular_benchmark_http_latency.sh`    |
| Regular   | `http_goodput` | `/usr/bin/regular_benchmark_http_goodput.sh`    |

The complete runtime call chain is:

```text
test YAML: test_tools.benchmark.profile
  -> RegularBenchmarkTest._install_profile()
  -> /usr/sbin/install_benchmark_profile.sh PROFILE
  -> regular or other profile installer
  -> /usr/bin/regular_test.sh
       +-- server RESULT_DIR -> http_benchmark.py server ...
       +-- client RESULT_DIR -> http_benchmark.py client ...
```

Profile templates are stored under `test/rootfs/usr/bin/`. The resulting
wrapper requires `/usr/bin/http_benchmark.py` in the same rootfs. When Oasis
is used as the `oasis_src` submodule, `src/tools/run_test.sh` automatically
copies the parent repository's `src/tools/http_benchmark.py` into the rootfs.
Set `HTTP_BENCHMARK_SOURCE=/path/to/http_benchmark.py` to use another source.

Run the supplied definitions with:

```sh
./src/tools/run_test.sh benchmark-test-example.yaml:http_latency --cleanup
./src/tools/run_test.sh benchmark-test-example.yaml:http_goodput --cleanup
``` 
