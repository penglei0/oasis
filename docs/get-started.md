# Get Started

This guide walks through the quickest way to run an Oasis test and explains the YAML structure used by the current test files.

- [Get Started](#get-started)
  - [1. Prerequisites](#1-prerequisites)
    - [Clone the repository](#clone-the-repository)
    - [Prepare the Python environment](#prepare-the-python-environment)
    - [For Linux: build the Docker images locally](#for-linux-build-the-docker-images-locally)
    - [For Linux: pull prebuilt images from GHCR](#for-linux-pull-prebuilt-images-from-ghcr)
    - [For Windows: rebuild the WSL kernel with `tc` support](#for-windows-rebuild-the-wsl-kernel-with-tc-support)
  - [2. Understand the current test YAML layout](#2-understand-the-current-test-yaml-layout)
  - [3. Run a test](#3-run-a-test)
  - [4. Customize a test](#4-customize-a-test)
    - [4.1 Change topology parameters](#41-change-topology-parameters)
    - [4.2 Change test-tool parameters](#42-change-test-tool-parameters)
    - [4.3 Change target protocols](#43-change-target-protocols)
    - [4.4 Built-in routing strategies](#44-built-in-routing-strategies)
  - [5. Test results](#5-test-results)
  - [6. Advanced configuration](#6-advanced-configuration)
    - [6.1 Topology parameter sweeping via `array_description`](#61-topology-parameter-sweeping-via-array_description)
    - [6.2 Parallel execution](#62-parallel-execution)
    - [6.3 Update files for each Docker container](#63-update-files-for-each-docker-container)
    - [6.4 Initialization script for each Docker container](#64-initialization-script-for-each-docker-container)
    - [6.5 Set environment variables for each Docker container](#65-set-environment-variables-for-each-docker-container)
    - [6.6 Customize protocol definitions](#66-customize-protocol-definitions)

## 1. Prerequisites

> Note: Oasis currently supports Ubuntu 22.04 and Ubuntu 24.04 for both the nested Containernet image and the host-node images.

### Clone the repository

```bash
git clone https://github.com/penglei0/oasis.git
cd oasis
git lfs fetch --all
git submodule update --init --recursive
```

### Prepare the Python environment

Install Python 3 and the repository requirements:

```bash
sudo apt install python3 python3-pip
python3 -m pip install -r requirements.txt
```

### For Linux: build the Docker images locally

Oasis uses two kinds of Docker images:

- **Nested Containernet images**, defined in `test/nested-containernet-config.yaml`
- **Host-node image presets**, defined in `test/predefined.node_config.yaml`

`src/start.py --containernet=<name>` selects the nested Containernet configuration. Inside the test YAML, `host.image.name` selects the preset used for the host containers created in that nested environment.

| Image tag | Usage | Description | Build command |
| --- | --- | --- | --- |
| `containernet:22.04` | Nested Containernet (`--containernet=default` / `--containernet=ubuntu-22.04`) | Builds Containernet from the local `containernet/` git submodule on Ubuntu 22.04. | `sudo docker build -t containernet:22.04 --build-arg UBUNTU_VERSION=22.04 -f Dockerfile.containernet .` |
| `containernet:24.04` | Nested Containernet (`--containernet=ubuntu-24.04`) | Builds Containernet from the local `containernet/` git submodule on Ubuntu 24.04. | `sudo docker build -t containernet:24.04 --build-arg UBUNTU_VERSION=24.04 -f Dockerfile.containernet .` |
| `ubuntu-generic:22.04` | Host nodes (`host.image.name: default` / `ubuntu-22.04`) | General-purpose Oasis host image for Ubuntu 22.04. | `sudo docker build -t ubuntu-generic:22.04 --build-arg UBUNTU_VERSION=22.04 -f Dockerfile.ubuntu-generic .` |
| `ubuntu-generic:24.04` | Host nodes (`host.image.name: ubuntu-24.04`) | General-purpose Oasis host image for Ubuntu 24.04. | `sudo docker build -t ubuntu-generic:24.04 --build-arg UBUNTU_VERSION=24.04 -f Dockerfile.ubuntu-generic .` |
| `ubuntu-generic-lttng:22.04` | Host nodes with LTTng (`host.image.name: ubuntu-22.04-lttng`) | Extends the Ubuntu 22.04 host image with LTTng tooling. | `sudo docker build -t ubuntu-generic-lttng:22.04 --build-arg UBUNTU_VERSION=22.04 -f Dockerfile.ubuntu-generic-lttng .` |
| `ubuntu-generic-lttng:24.04` | Host nodes with LTTng (`host.image.name: ubuntu-24.04-lttng`) | Extends the Ubuntu 24.04 host image with LTTng tooling. | `sudo docker build -t ubuntu-generic-lttng:24.04 --build-arg UBUNTU_VERSION=24.04 -f Dockerfile.ubuntu-generic-lttng .` |

The nested Containernet image is built from the bundled upstream source tree in `containernet/`. If you cloned Oasis without submodules, run `git submodule update --init --recursive` before building.

### For Linux: pull prebuilt images from GHCR

Prebuilt images are published to the GitHub Container Registry at <https://github.com/penglei0/oasis/pkgs/container/oasis%2Fcontainernet>. The published image matrix is defined in `.github/workflows/.github.publish-docker.yml`.

The workflow currently publishes the following images:

| Image | Available tags | Example pull command |
| --- | --- | --- |
| `ghcr.io/penglei0/oasis/containernet` | `22.04`, `24.04`, `vX.Y.Z-22.04`, `vX.Y.Z-24.04` | `sudo docker pull ghcr.io/penglei0/oasis/containernet:24.04` |
| `ghcr.io/penglei0/oasis/ubuntu-generic` | `22.04`, `24.04`, `vX.Y.Z-22.04`, `vX.Y.Z-24.04` | `sudo docker pull ghcr.io/penglei0/oasis/ubuntu-generic:24.04` |

Use the Ubuntu-version tags when you want the latest published image for a supported base OS, or use `vX.Y.Z-<ubuntu-version>` when you want a release-pinned image.

```bash
# pull the nested Containernet image
sudo docker pull ghcr.io/penglei0/oasis/containernet:24.04

# pull the default host-node image used by Oasis tests
sudo docker pull ghcr.io/penglei0/oasis/ubuntu-generic:24.04
```

If you prefer published images over local builds, update your local image names or presets so they point to the pulled tags.

### For Windows: rebuild the WSL kernel with `tc` support

When using WSL on Windows, `tc` is not enabled in the default WSL kernel. Oasis therefore requires a WSL kernel rebuilt with `tc` support. A helper script is available at `bin/wsl_kernel_support/kernel_tc.sh`.

First open Windows PowerShell:

```bash
wsl --unregister Ubuntu-22.04
wsl --install Ubuntu-22.04
```

After you finish the initial Ubuntu setup, copy `kernel_tc.sh` to your home directory and run:

```bash
sudo CUR_USER=$USER ./kernel_tc.sh
```

After the kernel is rebuilt, open Windows PowerShell again and restart WSL:

```bash
wsl --shutdown
```

Open a new WSL terminal and verify that `tc` works:

```bash
sudo tc q
sudo tc qdisc add dev eth0 root netem loss 10%
```

## 2. Understand the current test YAML layout

The current test files use a top-level `host:` section and a top-level `tests:` section. This is the main breaking change compared with older examples that used `containernet.node_config`.

```yaml
host:
  image:
    name: default
    presets: predefined.node_config.yaml
  init_script: init_node.sh
  env:
    - ENV_BATS_XXX_INTERVAL: "100"

tests:
  test2:
    description: "Test protocol throughput/rtt on single hop"
    topology:
      config_name: linear_network_1
      config_file: predefined.topology.yaml
    target_protocols: [btp, tcp-bbr, kcp]
    route: static_route
    test_tools:
      iperf:
        interval: 1
        interval_num: 10
        packet_type: tcp
        client_host: 0
        server_host: 1
    execution_mode: parallel
```

Key fields:

- `host.image.name`: selects a host-node preset by name, usually from `test/predefined.node_config.yaml`
- `host.image.presets`: points to the YAML file that contains those presets
- `host.init_script`: optional startup script copied into each host container
- `host.env`: optional environment variables passed to each host container
- `tests.<test_name>`: one or more named test cases in the file

For example, the following preset names are already available in `test/predefined.node_config.yaml`:

- `default`
- `ubuntu-22.04`
- `ubuntu-24.04`
- `ubuntu-22.04-lttng`
- `ubuntu-24.04-lttng`

If you want to keep the same YAML file but switch host presets at runtime, `src/start.py` also supports `--host=<preset-name>`.

## 3. Run a test

The following command starts a nested Containernet environment and runs `test/protocol-ci-test.yaml:test2`:

```bash
# from the Oasis repository root
sudo python3 src/start.py --containernet=default -t protocol-ci-test.yaml:test2

# or use the helper script
./src/tools/run_test.sh protocol-ci-test.yaml:test2 --cleanup

# when Oasis is imported as a git submodule in another project
./oasis_src/src/tools/run_test.sh protocol-ci-test.yaml:test2 --cleanup
```

By default, Oasis looks for YAML files under `test/`. You can change that base directory with `-p`:

```bash
sudo python3 src/start.py --containernet=default -p test -t protocol-ci-test.yaml:test2
```

Common command-line options:

- `--containernet=<name>`: selects the nested Containernet definition from `nested-containernet-config.yaml`
- `-t <file>` or `-t <file:test_name>`: selects a YAML file and optionally a single test case from that file
- `-p <path>`: sets the directory containing the YAML configuration files
- `--host=<preset-name>`: overrides `host.image.name` for the run

## 4. Customize a test

### 4.1 Change topology parameters

In `protocol-ci-test.yaml`, the network topology of `test2` is defined in the `topology` section:

```yaml
tests:
  test2:
    topology:
      config_name: linear_network_1
      config_file: predefined.topology.yaml
```

`test2` uses the `linear_network_1` topology defined in `predefined.topology.yaml`:

```yaml
- name: linear_network_1
  topology_type: linear
  nodes: 2
  array_description:
    - link_loss:
      init_value: [5]
    - link_latency:
      init_value: [10]
    - link_jitter:
      init_value: [0]
    - link_bandwidth_forward:
      init_value: [100]
    - link_bandwidth_backward:
      init_value: [100]
```

This topology represents:

```text
[host0]<------(100Mbps, 10ms, 5%)------>[host1]
```

If `nodes` is `N`, the linear topology contains `N - 1` hops. The editable parameters are `link_loss`, `link_latency`, `link_jitter`, `link_bandwidth_forward`, and `link_bandwidth_backward`.

For more complex layouts, use `json_description`. The following example defines a 4-hop linear network:

```yaml
- name: 4-hops-linear-network
  topology_type: linear
  nodes: 5
  json_description: 4-hops-linear-network.json
```

### 4.2 Change test-tool parameters

Throughput tests are configured under `test_tools`. Example `iperf` configuration:

```yaml
tests:
  test2:
    test_tools:
      iperf:
        interval: 1
        interval_num: 40
        client_host: 0
        server_host: 1
        packet_type: tcp
        bitrate: 10
```

TCP RTT tests can use `tcp_message_endpoint`:

```yaml
tests:
  test2:
    test_tools:
      tcp_message_endpoint:
        interval: 0.01
        packet_count: 100
        packet_size: 100
        client_host: 0
        server_host: 3
```

If you only care about the RTT of the first message, set `packet_count` to `1`.

### 4.3 Change target protocols

Each test case can choose the protocols to evaluate:

```yaml
tests:
  test3:
    description: "Compare the performance of kcp and tcp-bbr on a linear network"
    target_protocols: [kcp, tcp-bbr]
```

Oasis runs the selected test tools against the target protocols one by one unless `execution_mode: parallel` is enabled.

### 4.4 Built-in routing strategies

The routing strategy is set with `route`:

```yaml
tests:
  test001:
    route: static_route
```

Currently supported routing strategies:

- `static_route`: static routes configured with `ip route add`; best for chain networks
- `static_bfs`: static routes configured with `ip route add`; works for mesh networks, including chain networks
- `olsr_route`: dynamic routing configured by the OLSR daemon; works for chain networks
- `openr_route`: dynamic routing configured by the Open/R daemon; works for mesh and chain networks

## 5. Test results

Test results are saved under `{oasis_workspace}/test_results/{test_case_name}`. This folder usually contains:

- `iperf3_throughput.svg`
- `rtt.svg`
- `rtt_cdf.svg`

`{oasis_workspace}` is the base directory of the Oasis repository.

## 6. Advanced configuration

### 6.1 Topology parameter sweeping via `array_description`

The following example defines a 2-node linear network and sweeps link loss and latency:

```yaml
- name: topology_loss_rtt_matrix
  topology_type: linear
  nodes: 2
  array_description:
    - link_loss:
      init_value: [2]
      step_len: 2
      step_num: 3
    - link_latency:
      init_value: [10]
      step_len: 20
      step_num: 3
    - link_jitter:
      init_value: [0]
    - link_bandwidth_forward:
      init_value: [1000]
    - link_bandwidth_backward:
      init_value: [1000]
```

`step_num: 3` means the initial value plus three additional steps. As a result, `link_loss` takes values `[2, 4, 6, 8]`, and `link_latency` takes values `[10, 30, 50, 70]`. That produces 16 different topology variants.

After the run, the results are stored in a structure similar to:

```bash
oasis_src/test_results/test2
├── index.html
├── throughput_latency_loss.csv
├── throughput_latency_loss.md
├── topology-0/
├── topology-1/
├── topology-2/
...
├── topology-15/
```

### 6.2 Parallel execution

When evaluating multiple target protocols, set `execution_mode: parallel` to run them simultaneously:

```yaml
tests:
  test2:
    description: "Oasis parallel execution example"
    topology:
      config_name: linear_network_1
      config_file: predefined.topology.yaml
    target_protocols: [btp, tcp-bbr, kcp]
    route: static_route
    test_tools:
      iperf:
        interval: 1
        interval_num: 10
        packet_type: tcp
        client_host: 0
        server_host: 1
    execution_mode: parallel
```

Oasis creates isolated network namespaces so these protocol runs do not interfere with each other.

### 6.3 Update files for each Docker container

Either `test/rootfs/` or `{config_folder}/rootfs/` (when using `-p {config_folder}` with `src/run_test.py`) can contain files that should be copied into the root filesystem of each host container at startup. This is useful for custom tools or configuration files.

### 6.4 Initialization script for each Docker container

Use `host.init_script` to run a script when each host container starts:

```yaml
host:
  image:
    name: default
    presets: predefined.node_config.yaml
  init_script: init_node.sh

tests:
  test2:
    description: "Test"
    ...
```

Usually, `init_node.sh` is placed in either `{config_folder}/rootfs/usr/sbin/` or `test/rootfs/usr/sbin/`.

### 6.5 Set environment variables for each Docker container

Use `host.env` to pass environment variables to each host container:

```yaml
host:
  image:
    name: default
    presets: predefined.node_config.yaml
  init_script: init_node.sh
  env:
    - ENV_EXAMPLE1: "2000"
    - ENV_EXAMPLE2: "0.5"
    - ENV_EXAMPLE3: "1"

tests:
  test0:
    description: "test"
```

### 6.6 Customize protocol definitions

Oasis supports iterative protocol definitions for client/server mode protocols. Example:

```yaml
- name: btp
  type: none_distributed
  args:
    - "--daemon_enabled=true"
  protocols:
    - name: btp_client
      args:
        - "--tun_protocol=BTP"
      config_file: cfg-template/bats-quic-client.ini
      version: latest
    - name: btp_server
      args:
        - "--tun_protocol=BRTP"
      config_file: cfg-template/bats-quic-server.ini
      version: latest
```

The protocol `btp` has two iterations, `btp_client` and `btp_server`, which share the top-level `type` and `args`.
