[![Oasis CI](https://github.com/penglei0/oasis/actions/workflows/.github.oasis-ci.yml/badge.svg)](https://github.com/penglei0/oasis/actions/workflows/.github.oasis-ci.yml)
[![CodeQL Pylint Unittest](https://github.com/penglei0/oasis/actions/workflows/.github.ci.yml/badge.svg)](https://github.com/penglei0/oasis/actions/workflows/.github.ci.yml)

-----

# Oasis

Oasis is a Containernet-based network emulation platform for validating transport protocols across diverse topologies, link qualities, and routing strategies.
> Oasis is built on [Containernet](https://github.com/containernet/containernet/), a fork of [Mininet](http://mininet.org/), and [Docker](https://www.docker.com/).

See [docs/arch.md](docs/arch.md) for the architecture overview and implementation details.

## Capabilities

- Compose multi-hop network topologies with customizable latency, bandwidth, and loss.
- Launch built-in protocol suites (BATS™ variants, TCP, KCP, etc.) and plug in your own protocol binaries.
- Run throughput, latency, RTT, SCP transfer, and flow-competition tests using reusable YAML definitions.
- Collect logs plus analyzer outputs (SVG charts, stats) through the integrated data pipeline.

See getting started guide in [docs/get-started.md](docs/get-started.md) for more details.

## Using Oasis

1. **Prepare dependencies** — initialize Git LFS and the bundled Containernet submodule, then follow the prerequisites (WSL kernel TC support, Docker, Python) listed in [docs/get-started.md](docs/get-started.md#1-prerequisites).

   ```bash
   git lfs fetch --all
   git submodule update --init --recursive
   ```
2. **Launch a test**:

   ```bash
   ./src/tools/run_test.sh protocol-ci-test.yaml:test1 --cleanup
   ```

3. **Inspect results** — Oasis writes analyzer artifacts per test suite; see [docs/get-started.md](docs/get-started.md#3-test-results) for paths and sample outputs.

## Container images

Oasis now builds the nested Containernet image from the bundled `containernet/` git submodule instead of relying on `containernet/containernet:latest`. The supported image variants are documented in [docs/get-started.md](docs/get-started.md#for-linux-platform-build-docker-image), including their usage, tags, and build commands for Ubuntu 22.04 and Ubuntu 24.04.

## Import Oasis to your project

1. **import it as git-submodule**:

   ```bash
   git submodule add https://github.com/penglei0/oasis.git oasis_src
   ```

2. **define custom YAML descriptions**:
   - 2.1 Target protocols definition, see example in `test/predefined.protocols.yaml`.
   - 2.2 Network topology definition, see example in `test/predefined.topologies.yaml`.
   - 2.3 Containernet image definition and its configuration, see example in `test/nested-containernet-config.yaml`.
   - 2.4 The docker images definition and its configuration for the host nodes in Containernet, see example in `test/predefined.node_config.yaml`.

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

3. **run tests with the helper script**:

   ```bash
   ./oasis_src/src/tools/run_test.sh your_test_cases.yaml:test198964 --cleanup
   ```

   `run_test.sh` assumes your custom config files are in the `test/` folder. The `--cleanup` flag will remove all the generated logs after the test is done.

4. **check results**

   Oasis will create a folder `oasis_src/test_results/` in your current working directory to store all the test results based the name of your test case.

## Additional docs

- Architecture deep dive: [docs/arch.md](docs/arch.md)
- Supported protocols and tools: [docs/protocols_and_tools.md](docs/protocols_and_tools.md)
- Get started guide: [docs/get-started.md](docs/get-started.md)
- Flow competition tests example: [docs/flow_competition_test.md](docs/flow_competition_test.md)
- Traffic shaping strategy: [docs/tc-strategy.md](docs/tc-strategy.md)
