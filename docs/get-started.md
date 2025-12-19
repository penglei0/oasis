# Get Started

This guide provides simple steps to getting started with Oasis.

- [Get Started](#get-started)
  - [1. Prerequisites](#1-prerequisites)
    - [prepare python environment](#prepare-python-environment)
    - [For Linux platform: Build docker image](#for-linux-platform-build-docker-image)
    - [For windows platform: WSL kernel recompile](#for-windows-platform-wsl-kernel-recompile)
  - [2. Run test](#2-run-test)
    - [2.1 Change topology parameters](#21-change-topology-parameters)
    - [2.2 Change test tools parameters](#22-change-test-tools-parameters)
    - [2.3 Change target protocols](#23-change-target-protocols)
    - [2.4 Built-in routing strategies](#24-built-in-routing-strategies)
  - [3. Test results](#3-test-results)
  - [4 Advanced configuration](#4-advanced-configuration)
    - [4.1 Topology parameter sweeping via array\_description](#41-topology-parameter-sweeping-via-array_description)
    - [4.2 Parallel execution](#42-parallel-execution)
    - [4.3 Update files of each docker container](#43-update-files-of-each-docker-container)
    - [4.4 Initialization script for each docker container](#44-initialization-script-for-each-docker-container)
    - [4.5 Set environment variables for each docker container](#45-set-environment-variables-for-each-docker-container)
    - [4.6 Customize protocol definition](#46-customize-protocol-definition)

## 1. Prerequisites

First step is to get the source code of Oasis from GitHub:

```bash
git clone https://github.com/penglei0/oasis.git
git lfs fetch --all
```

> Note: Highly recommend to use Oasis with Ubuntu 22.04.

### prepare python environment

Install python3:

```bash
# prepare python environment
sudo apt install python3 python3-pip

# install python packages.
python3 -m pip install PyYAML==6.0.1
```


### For Linux platform: Build docker image

The required docker images are defined in `test/predefined.node_config.yaml` and `test/nested-containernet-config.yaml`.

`test/nested-containernet-config.yaml` lists the available Containernet images and its configuration; `test/predefined.node_config.yaml` lists the available docker images for the host nodes in Containernet and its configuration.

```bash
# To build the official Containernet image
sudo docker build -t  containernet:latest -f Dockerfile.containernet .

# To build the ubuntu 22.04 image for host nodes in Containernet
sudo docker build -t ubuntu-generic:latest -f Dockerfile.ubuntu-generic .
```

when using `src/start.py` to lunch a test, the option `--containernet=default` specifies the image to use and `node_config` section in the test case YAML (e.g., `test/protocol-ci-test.yaml`)    specifies the docker images for host nodes in Containernet.

### For windows platform: WSL kernel recompile

When using WSL in windows, tc is not default compiled to WSL kernel, so WSL kernel recompilation with tc support is needed, script is provided in {project_dir}/bin/wsl_kernel_support/kernel_tc.sh

First open Windows PowerShell

```bash

wsl --unregister Ubuntu-22.04   # unregister any installed wsl
wsl --install Ubuntu-22.04      # reinstall wsl Ubuntu-22.04
```

After setup username and password, copy kernel_tc.sh to home directory (~)

```bash
sudo CUR_USER=$USER ./kernel_tc.sh
```

After kernel recompiled, open Windows Powershell

```bash
wsl --shutdown      # reset wsl
```

Open new wsl terminal and check if wsl support tc

```bash
sudo tc q                                       # check existing tc rules
sudo tc qdisc add dev eth0 root netem loss 10%  # add 10% packet drop rate to eth0 interface
```

## 2. Run test

The following command will run `src/run_test.py` in a nested containernet environment, and `run_test.py` will execute the test case defined in `protocol-ci-test.yaml`.

```bash
# in the root directory of oasis project
sudo python3 src/start.py --containernet=default -t protocol-ci-test.yaml:test2

# Or use the helper script
./src/tools/run_test.sh protocol-ci-test.yaml:test2 --cleanup

# when Oasis is imported as a git submodule in your project, use the following command
./oasis_src/src/tools/run_test.sh protocol-ci-test.yaml:test2 --cleanup
```

`test/` is the directory containing all the YAML configuration files. Oasis will search for `nested-containernet-config.yaml`, `protocol-ci-test.yaml` in this folder. This folder can be customized according to the location of Oasis repository.

`--containernet=default` specifies the official Containernet configuration which is defined in `nested-containernet-config.yaml`.

`-t protocol-ci-test.yaml` specifies the test case file, which is a YAML file defining the test case. By default, it tries to execute all     the test cases in that file. To execute a specific test case, use `-t protocol-ci-test.yaml:test_name`.

### 2.1 Change topology parameters

In `protocol-ci-test.yaml`, the network topology of the case `test2` is defined in the `topology` section:

```yaml
   test2:
    topology:
      config_name: linear_network_1
      config_file: predefined.topology.yaml
```

The case `test2` will use the `linear_network_1` topology defined in `predefined.topology.yaml`. And `linear_network_1` is defined as follows:

```yaml
- name: linear_network_1
    topology_type: linear
    nodes: 2
    array_description: # only suitable for linear topology. 
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

The `linear_network_1` defines a network topology like below:

```text
  [host0]<------(100Mbps, 10ms, 5%)------>[host1]
```

To change the network topology, we can change the value of `nodes`. If value of `nodes` is `N`, it is a `N-1` hops of chain network. Other editable parameters are `link_loss`, `link_latency`, `link_jitter`, `link_bandwidth_forward`, and `link_bandwidth_backward`. Those arrays are used to define the link attributes of the network link by link from the node 0 to node N-1.

For other complex topologies, we should use `json_description` to define the topology. The following is an example of 4-hops linear network defined in `predefined.topology.yaml`:

```yaml
  - name: 4-hops-linear-network
    topology_type: linear
    nodes: 5
    json_description: 4-hops-linear-network.json
```

"json_description" of `4-hops-linear-network.json` uses adjacent matrices to describe the network topology and its link attributions which is quite easy to understand.

### 2.2 Change test tools parameters

Iperf throughput test tool is defined in the `test_tools` section of the test case file. The following is an example of `iperf` tool configuration in the test case `test2`:

```yaml
   test2:
    test_tools:
      iperf:
        interval: 1       # iperf test interval in seconds
        interval_num: 40  # iperf test duration in seconds
        client_host: 0    # iperf client host id
        server_host: 1    # iperf server host id
        packet_type: tcp  # tcp/udp, tcp is default
        bitrate: 10       # 10Mps, valid when packet_type is udp
```

TCP RTT test tool is defined in the `test_tools` section of the test case file. The following is an example of `tcp_message_endpoint` tool configuration in the test case `test2`:

```yaml
   test2:
    test_tools:
      tcp_message_endpoint:
        interval: 0.01      # interval between two packets in seconds
        packet_count: 100   # number of packets to be sent
        packet_size: 100    # size of each packet in bytes
        client_host: 0      # tcp_message_endpoint client host id
        server_host: 3      # tcp_message_endpoint server host id
```

If you only care about the RTT of the first message, set `packet_count` to 1.

### 2.3 Change target protocols

For each test case, we can define the target protocols to be evaluated. The following is an example:

```yaml
  test3:
    description: "Compare the performance of kcp, tcp-bbr with a linear network"
    target_protocols: [kcp, tcp-bbr]
```

Oasis will uses selected test tools to measure the performance of the target protocols one by one.

### 2.4 Built-in routing strategies

In the test case, the applied routing strategy of current test is specified by `route`:

```yaml
  - name: test001
    route: static_route
```

Currently supported route strategies are:

- `static_route`, static routing which are configured with `ip route add` command. This works for the chain network.
- `static_bfs`, static routing which are configured with `ip route add` command. This works for the mesh network, including the chain one.
- `olsr`, dynamic routing configuration which are done by `OSLR` protocol daemon. This works for the chain network.

## 3. Test results

The test results will be saved to `{oasis_workspace}/test_results/{test_case_name}`, where `{test_case_name}` is defined in the test case YAML file. This folder contains following SVG files to show throughput and RTT performance:

- `iperf3_throughput.svg`
- `rtt.svg`,
- `rtt_cdf.svg`

`{oasis_workspace}` is the base directory of Oasis.


## 4 Advanced configuration

### 4.1 Topology parameter sweeping via array_description

The following example `topology_loss_rtt_matrix` defines a 2-hops linear network with parameter sweeping on link loss and link latency:

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

The `link_loss` will take values from `[2,4,6,8]`, and `link_latency` will take values from `[10,30,50,70]`. Therefore, totally 16 different network topologies will be generated for test.

After the test is done, the test results will be stored in the following folder structure:

```bash
  oasis_src/test_results/test2
  ├── index.html                    # index file for easy navigation(generated by `src/tools/generate_index.py`)
  ├── throughput_latency_loss.csv   # summary of throughput and latency under different loss and latency(generated by `src/tools/extract_data.py`)
  ├── throughput_latency_loss.md    # summary of throughput and latency under different loss and latency(generated by `src/tools/extract_data.py`)
  ├── topology-0/                   # detailed test results and logs for link_loss=2%, link_latency=10ms
  ├── topology-1/                   # detailed test results and logs for link_loss=2%, link_latency=30ms
  ├── topology-2/
  ......
  ├── topology-16/                  # detailed test results and logs for link_loss=8%, link_latency=70ms
```

### 4.2 Parallel execution

When evaluating multiple target protocols, we can set `execution_mode` to `parallel` to run those protocols simultaneously to speed up the test. The following is an example:

```yaml
  test2:
    description: "Oasis Parallel execution example"
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
    execution_mode: parallel # Oasis will create three isolated network namespaces to run those three protocols simultaneously.
```

### 4.3 Update files of each docker container

Either `test/rootfs/` or `{config_folder}/rootfs/`(specified by `-p {config_folder}` in the `src/run_test.py` command) folder contains the necessary files which will be copied to the root file system of the docker container when starting the container. This is useful when we want to update some configuration files or add some custom tools to the docker container.

### 4.4 Initialization script for each docker container

When `init_script` is specified in `containernet.node_config` section of test case YAML file, Oasis will run the specified script to initialize each docker container when starting the container. The following is an example:

```yaml
containernet:
  node_config:
    config_name: default
    config_file: predefined.node_config.yaml
    init_script: init_node.sh # specify the init script to be run when starting each docker container

tests:
  test2:
    description: "Test"
    ...
```

Usually, `init_node.sh` is placed in either `{config_folder}/rootfs/usr/sbin/` or `test/rootfs/usr/sbin/` folder.

### 4.5 Set environment variables for each docker container

In Oasis test case YAML file, we can pass environment variables to each docker container by specifying `env` in `containernet.node_config` section. The following is an example:

```yaml
containernet:
  node_config:
    config_name: default
    config_file: predefined.node_config.yaml
    init_script: init_node.sh
    env:
      - ENV_EXAMPLE1: "2000" # environment variable key-value pair, will take effect in each docker container
      - ENV_EXAMPLE2: "0.5"  # environment variable key-value pair, will take effect in each docker container
      - ENV_EXAMPLE3: "1"    # environment variable key-value pair, will take effect in each docker container

tests:
  test0:
    description: "test"
  ...
```

### 4.6 Customize protocol definition

Oasis supports iteration description for client/server mode protocols. The following is an example:

```yaml
  - name: btp
    type: none_distributed
    args:
      - "--daemon_enabled=true"
    protocols: # iterative
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

The protocol `btp` has two iterations: `btp_client` and `btp_server`. Those two iterations share the same `type` and `args` parameters in top-level.
