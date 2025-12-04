[![Oasis CI](https://github.com/penglei0/oasis/actions/workflows/.github.oasis-ci.yml/badge.svg)](https://github.com/penglei0/oasis/actions/workflows/.github.oasis-ci.yml)
[![CodeQL Pylint Unittest](https://github.com/penglei0/oasis/actions/workflows/.github.ci.yml/badge.svg)](https://github.com/penglei0/oasis/actions/workflows/.github.ci.yml)

-----

# Oasis

Oasis is a Containernet-based network emulation platform for validating transport protocols across diverse topologies, link qualities, and routing strategies.
> Oasis is built on [Containernet](https://github.com/containernet/containernet/), a fork of [Mininet](http://mininet.org/), and [Docker](https://www.docker.com/).

## Architecture

<div align="center" style="text-align:center"> 
<img src="./docs/imgs/oasis_arch.svg" alt="Oasis" style="zoom:50%;"></div>
<div align="center">Fig 1.1 Oasis architecture brief view</div>

Workflow of a Oasis test is orchestrated by several key components:

- construct a `INetwork` with a given yaml configuration which describes the network topology.
- load `ITestSuite`(the test tool) from yaml configuration.
- load `IProtoSuite`(the target test protocol) from yaml configuration.
- run `IProtoSuite` on `INetwork`.
- perform the test with `ITestSuite` on `INetwork`.
- read/generate test results by `IDataAnalyzer`.

## Capabilities

- Compose multi-hop network topologies with customizable latency, bandwidth, and loss.
- Launch built-in protocol suites (BATS™ variants, TCP, KCP, etc.) and plug in your own protocol binaries.
- Run throughput, latency, RTT, SCP transfer, and flow-competition tests using reusable YAML definitions.
- Collect logs plus analyzer outputs (SVG charts, stats) through the integrated data pipeline.

See getting started guide in [docs/get-started.md](docs/get-started.md) for more details.

## Using Oasis

1. **Prepare dependencies** — follow the prerequisites (WSL kernel TC support, Docker, Python) listed in [docs/get-started.md](docs/get-started.md#1-prerequisites).
2. **Launch a test**:
   ```bash
   sudo python3 src/start.py -p test --containernet=default -t protocol-ci-test.yaml:test1
   ```
3. **Inspect results** — Oasis writes analyzer artifacts per test suite; see [docs/get-started.md](docs/get-started.md#3-test-results) for paths and sample outputs.

## Import Oasis to your project

1. **add it to your git submodule**:
   ```bash
   git submodule add https://github.com/penglei0/oasis.git oasis_src
   ```

2. **define custom YAML descriptions**:
   - 2.1 Target protocols definition, see example in `test/predefined.protocols.yaml`.
   - 2.2 Network topology definition, see example in `test/predefined.topologies.yaml`.
   - 2.3 Docker images definition, see example in `test/nested-containernet-config.yaml`.
   - 2.4 Docker node related configuration, see example in `test/predefined.node_config.yaml`.

   A recommended file structure could be like below:

   ```bash
   your_project/
   ├── oasis_src/                  # oasis git submodule
   ├── test/                       # tests related definition
       ├── nested-containernet-config.yaml  # your custom containernet docker config
       ├── predefined.node_config.yaml      # your custom node config
       ├── predefined.protocols.yaml        # your custom protocols definition
       ├── predefined.topology.yaml         # your custom topology definition
       ├── your_test_cases.yaml             # your custom test cases definition
       ├── rootfs/                          # your custom rootfs files which will be updated 
                                             # to the running containers
   ```

3. **run your tests**:

   ```bash
   sudo python3 oasis/src/start.py -p test --containernet=custom -t your_test_cases.yaml:test_1
   ```

4. **run your tests with helper script**:

   ```bash
   ./oasis_src/src/tools/run_test.sh your_test_cases.yaml:test_1 --cleanup
   ```

   `run_test.sh` assumes your custom config files are in the `test/` folder. The `--cleanup` flag will remove all the generated logs after the test is done.

5. **check results**

   Oasis will create a folder `oasis_src/test_results/` in your current working directory to store all the test results based the name of your test case.

## Additional docs

- Supported protocols and tools: [docs/protocols_and_tools.md](docs/protocols_and_tools.md)
- Get started guide: [docs/get-started.md](docs/get-started.md)
- Flow competition tests example: [docs/flow_competition_test.md](docs/flow_competition_test.md)
- Traffic shaping strategy: [docs/tc-strategy.md](docs/tc-strategy.md)