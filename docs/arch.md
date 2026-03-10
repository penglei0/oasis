# Oasis Architecture

Oasis is a **Containernet-based network emulation platform** for validating transport protocols across configurable topologies, routing strategies, and link characteristics. At a high level, the system turns YAML definitions into one or more runtime networks, deploys protocol implementations into those networks, executes reusable test suites, and post-processes the generated logs into analyzer artifacts such as SVG charts.

This document summarizes the current architecture implemented in the repository and highlights the refactorings that would most improve maintainability and flexibility.

## 1. System view

Oasis is organized around five major responsibilities:

1. **Configuration loading**: YAML files describe the nested Containernet image, host-node image, topology, target protocols, routing strategy, and test tools.
2. **Environment bootstrapping**: `src/start.py` launches a nested Containernet container and executes the main runner inside it.
3. **Network construction**: `src/run_test.py` loads test definitions, resolves node and topology configuration, selects a network manager, and asks it to build one or more `INetwork` instances.
4. **Protocol + test execution**: each `INetwork` receives one or more `IProtoSuite` and `ITestSuite` instances and executes them in a controlled order.
5. **Analysis + artifact generation**: the test runner merges results, chooses analyzers, generates charts, and archives outputs under `test_results/`.

The existing repository diagram in `docs/imgs/oasis_arch.svg` and the implementation in `src/start.py`, `src/run_test.py`, `src/core/runner.py`, `src/interfaces/network.py`, and `src/containernet/containernet_network.py` all reflect this pipeline.

## 2. Runtime flow

The main execution path is:

```text
run_test.sh
  -> start.py
     -> NestedContainernet.start()
     -> docker exec python3 /root/src/run_test.py ...
        -> load_all_tests()
        -> load node/topology/protocol/test definitions
        -> create_network_mgr()
        -> TestRunner.init()
           -> INetworkManager.build_networks()
        -> TestRunner.setup_tests()
           -> attach IProtoSuite + ITestSuite objects to each network
        -> TestRunner.execute_tests()
           -> INetworkManager.start_networks()
           -> multiprocessing workers call INetwork.perform_test()
        -> TestRunner.handle_test_results()
           -> diagnostic_test_results()
           -> AnalyzerFactory.get_analyzer(...).visualize()/analyze()
           -> archive to test_results/<test>/topology-<index>/
```

### Step-by-step detail

- `src/tools/run_test.sh` is the user-facing helper script documented in `README.md` and `docs/get-started.md`.
- `src/start.py` parses CLI arguments, resolves the YAML base path, loads `nested-containernet-config.yaml`, starts a nested container via `NestedContainernet`, and invokes `src/run_test.py` inside that container.
- `src/run_test.py` resolves whether the config is coming from the repository `test/` directory or an external consumer project, loads the requested test YAML, chooses a network manager with `create_network_mgr()`, and iterates over every selected test case and topology instance.
- `src/core/runner.py` is the main orchestration layer. It loads target protocols, creates networks, converts YAML test-tool definitions into concrete test suite objects, executes them, and dispatches analyzers.
- `src/interfaces/network.py` defines the execution contract of a network. `INetwork.perform_test()` is the central loop: start protocol, run each test, capture result metadata, then stop the protocol.

## 3. Main modules and responsibilities

### 3.1 CLI and bootstrap layer

- `src/tools/run_test.sh`: convenience wrapper for launching tests.
- `src/start.py`: CLI entrypoint for nested execution.
- `src/containernet/containernet.py`: nested-container lifecycle, Docker mount wiring, dependency installation, and execution of the in-container runner.

This layer is operationally important because Oasis does not run directly on the host Python process during normal use; it executes inside a privileged nested Containernet container.

### 3.2 Core orchestration layer

- `src/run_test.py`: top-level script runner.
- `src/core/config.py`: YAML loading, config indirection (`config_file` + `config_name`), test-case selection, topology resolution, and dataclasses for `NodeConfig` and `NestedConfig`.
- `src/core/runner.py`: protocol loading, test loading, parallel execution, result merging, and analyzer dispatch.
- `src/core/network_factory.py`: selection of `INetworkManager` implementation.

This is the “application service” layer of Oasis. It translates declarative YAML into executable objects.

### 3.3 Network abstraction layer

- `src/interfaces/network.py`: abstract network lifecycle and test execution contract.
- `src/interfaces/network_mgr.py`: abstract manager for one or more networks.
- `src/core/network_mgr.py`: Containernet-backed implementation.
- `src/core/testbed_mgr.py`: testbed-oriented manager placeholder.
- `src/containernet/containernet_network.py`: concrete `ContainerizedNetwork` implementation.
- `src/interfaces/host.py` and `src/containernet/containernet_host.py`: host abstraction/adaptation.

This layer separates **how a network is provisioned** from **what protocol/test logic is run on top of it**.

### 3.4 Topology and routing layer

- `src/core/topology.py`: topology datamodel, matrix model, and abstract topology behavior.
- `src/core/linear_topology.py` and `src/core/mesh_topology.py`: current topology implementations.
- `src/interfaces/routing.py`: routing contract.
- `src/routing/`: route implementations such as static, BFS-based static, OLSR, and Open/R.
- `src/routing/routing_factory.py`: runtime strategy selection from YAML route strings.

A topology produces adjacency/bandwidth/loss/latency/jitter matrices. `ContainerizedNetwork` consumes those matrices to create links and apply traffic shaping with `tc`.

### 3.5 Protocol layer

- `src/protosuites/proto.py`: base protocol interface and configuration dataclass.
- `src/protosuites/std_protocol.py`: default wrapper for generic distributed protocols.
- `src/protosuites/cs_protocol.py`: wrapper for client/server style non-distributed protocols.
- `src/protosuites/noop_protocol.py`: no-op protocol used for “next”/pass-through cases.
- `src/protosuites/bats/`: BATS-specific implementations (`BTP`, `BRTP`, `BRTPProxy`).

The protocol layer is intentionally pluggable. YAML names map to concrete protocol suite classes in `src/core/runner.py`.

### 3.6 Test-suite layer

- `src/testsuites/test.py`: base `ITestSuite`, `TestConfig`, and `TestResult`.
- `src/testsuites/test_iperf.py`, `test_iperf_bats.py`, `test_rtt.py`, `test_ping.py`, `test_scp.py`, `test_sshping.py`: concrete test tools.
- `src/testsuites/test_competition.py`: flow-competition wrapper and configuration.

A test suite is responsible for pre-processing, invoking the measurement tool, and post-processing the output into a result record that analyzers can consume.

### 3.7 Analysis and storage layer

- `src/data_analyzer/`: analyzer implementations and `AnalyzerFactory`.
- `src/data_storage/`: storage-related helpers.

This layer converts raw logs into user-facing artifacts such as throughput or RTT graphs.

## 4. Configuration model

Oasis is strongly YAML-driven. The main files under `test/` illustrate the configuration domains:

- `nested-containernet-config.yaml`: nested runtime image and mount configuration.
- `predefined.node_config.yaml`: Docker image, mounts, naming, IP range, and environment for emulated hosts.
- `predefined.topology.yaml`: reusable topology definitions.
- `predefined.protocols.yaml`: reusable protocol definitions.
- `protocol-ci-test.yaml` and other test YAML files: test-case composition.

### Configuration indirection

A recurring pattern is:

```yaml
config_name: linear_network_1
config_file: predefined.topology.yaml
```

`IConfig.load_yaml_config()` and `IConfig.load_config_reference()` resolve these references and return typed dataclasses (`NodeConfig` or `TopologyConfig`). This makes the system highly reusable: many test cases can share the same topology or node definition.

### Why the YAML model matters

The configuration model is the primary extension mechanism in Oasis. Most user customization happens without changing Python code:

- swap container images,
- change link attributes,
- reuse topology templates,
- compare multiple transport protocols,
- add test-tool parameters,
- enable parallel execution per protocol.

## 5. Execution model and concurrency

### Serial vs. parallel execution

`TestRunner.init()` supports two execution modes:

- **serial**: one network instance runs all requested protocols in sequence;
- **parallel**: one network instance is created per target protocol.

In parallel mode, `TestRunner.execute_tests()` spawns one Python process per network. Each process calls `INetwork.perform_test()` and publishes its results through a `multiprocessing.Manager().dict()`.

### Result handling

After execution:

1. worker results are copied back into `self.results_dict`,
2. results from all workers are merged by test type,
3. analyzers are chosen by `AnalyzerFactory`,
4. artifacts are generated and moved into topology-specific archive folders.

This design makes protocol comparisons convenient because the same test case can target several protocols without changing the test definition itself.

## 6. Design strengths in the current architecture

Oasis already contains several good architectural decisions:

### 6.1 Clear core abstractions

The interfaces `INetwork`, `INetworkManager`, `IRoutingStrategy`, `IProtoSuite`, and `ITestSuite` give the codebase a useful separation of concerns.

### 6.2 Strong configuration reuse

The `config_file` / `config_name` indirection allows many reusable presets for topologies, protocols, node images, and nested Containernet images.

### 6.3 Protocol/tool composability

A single topology can be exercised with multiple protocol suites and multiple test tools, which is exactly the right abstraction for comparative network experimentation.

### 6.4 Analyzer decoupling

Execution and visualization are separated. Tests generate logs; analyzers interpret them later.

### 6.5 Practical runtime isolation

Running inside nested Containernet keeps Oasis close to the target environment and makes traffic shaping, routing setup, and host isolation reproducible.

## 7. Architecture constraints and current pain points

The current implementation also shows several maintainability constraints that are worth documenting explicitly.

### 7.1 Script-first orchestration

`src/start.py` and `src/run_test.py` are both script-style modules with direct `sys.argv`, `sys.exit`, filesystem access, and logging calls. This works, but it makes reuse and unit testing harder than it needs to be.

### 7.2 String-based factories and conditional chains

Several extension points are selected through long `if`/`elif` blocks or ad-hoc string matching:

- protocols in `src/core/runner.py`,
- test tools in `src/core/runner.py`,
- analyzers in `src/data_analyzer/analyzer_factory.py`,
- routing strategies in `src/routing/routing_factory.py`.

This increases coupling and makes feature growth more error-prone.

### 7.3 Global path coupling

Many classes write directly to `g_root_path`-derived locations during object construction, especially in `IProtoSuite` and `ITestSuite`. That couples domain objects to one filesystem layout and makes isolated tests harder.

### 7.4 Large orchestration surface in `TestRunner`

`TestRunner` is responsible for protocol loading, test loading, network allocation, execution, multiprocessing supervision, result merging, analyzer dispatch, and artifact archiving. That is a lot of responsibilities for one class.

### 7.5 Partial testbed abstraction

The repository exposes a testbed path (`NetworkType.testbed`, `TestbedManager`, `load_testbed_config()`), but the implementation is not yet symmetrical with the Containernet path. For example, `src/run_test.py` currently hard-codes `is_using_testbed = False`, and `src/core/testbed_mgr.py` is mostly placeholder behavior.

### 7.6 Inconsistent error propagation

Some layers return booleans, others log and continue, and top-level scripts often call `sys.exit()`. This makes control flow more difficult to reason about and complicates automated recovery or richer error reporting.

## 8. High-value refactorings and refinements

The following refinements would provide the best maintainability and flexibility gains without changing Oasis’s core purpose.

### 8.1 Introduce an application service layer for orchestration

**Current issue**: bootstrap, configuration resolution, and orchestration logic are split across `start.py`, `run_test.py`, and `TestRunner` in a script-oriented style.

**Recommended refinement**:
- extract a reusable service such as `OasisApplication` or `TestExecutionService`,
- move the imperative workflow from `run_test.py` into that service,
- keep `start.py` and `run_test.py` as thin CLI adapters.

**Why it helps**:
- easier unit testing of the full workflow,
- easier future APIs (CLI today, REST/job runner tomorrow),
- simpler error handling and dependency injection.

### 8.2 Replace conditional factory logic with explicit registries

**Current issue**: protocol, test, analyzer, and routing selection depends on string comparisons and hand-written dispatch logic.

**Recommended refinement**:
- create registries such as `PROTOCOL_REGISTRY`, `TEST_REGISTRY`, `ANALYZER_REGISTRY`, and `ROUTING_REGISTRY`,
- register implementations close to their definitions,
- keep the YAML names stable but resolve them through the registry.

**Why it helps**:
- adding a new protocol/test becomes localized,
- fewer merge conflicts in central factory files,
- clearer support matrix and better validation errors.

### 8.3 Separate pure configuration parsing from runtime side effects

**Current issue**: loading configuration and acting on it are intertwined; constructors often create directories or assume a specific root path.

**Recommended refinement**:
- keep dataclasses pure,
- move directory creation and artifact layout into a dedicated runtime context or artifact manager,
- inject the results directory into protocol/test instances instead of reading global paths.

**Why it helps**:
- cleaner testability,
- easier alternate output layouts,
- lower coupling between business logic and filesystem concerns.

### 8.4 Split `TestRunner` into smaller focused collaborators

**Current issue**: `TestRunner` currently acts as loader, planner, executor, process supervisor, and result archiver.

**Recommended refinement**:
- extract components such as:
  - `ProtocolLoader`,
  - `TestSuiteLoader`,
  - `ExecutionPlanner`,
  - `ExecutionEngine`,
  - `ResultArchiver`.

**Why it helps**:
- each class becomes easier to understand and test,
- parallel execution and result handling can evolve independently,
- lower cognitive load for contributors.

### 8.5 Make the backend choice explicit and complete

**Current issue**: the code exposes both Containernet and testbed abstractions, but the normal path is effectively Containernet-only today.

**Recommended refinement**:
- make backend selection explicit in CLI/configuration,
- either fully implement the testbed backend or mark it clearly as experimental,
- ensure the backend contract is feature-complete for both implementations.

**Why it helps**:
- avoids misleading abstractions,
- makes future non-Containernet support realistic,
- reduces dead or partially implemented branches in the code.

### 8.6 Standardize error handling with structured results or exceptions

**Current issue**: many functions return `False`/`None`, log internally, and sometimes also terminate the process.

**Recommended refinement**:
- use typed exceptions for unrecoverable errors,
- use structured result objects where partial recovery is expected,
- centralize CLI exit-code handling at the outermost layer.

**Why it helps**:
- more predictable control flow,
- better diagnostics for automation and CI,
- simpler unit tests.

### 8.7 Formalize the extension contract

**Current issue**: Oasis is already extensible, but the extension mechanism is implicit in factory code and YAML conventions.

**Recommended refinement**:
- document a clear plugin contract for new protocols, tests, analyzers, and routing strategies,
- add a single architecture-level extension section that names the required interfaces and registry keys,
- validate YAML against those supported extension points.

**Why it helps**:
- easier onboarding for contributors,
- less accidental breakage when adding new features,
- better long-term compatibility for downstream projects importing Oasis as a submodule.

### 8.8 Add more architecture-focused unit tests

**Current issue**: the existing unit tests are centered mainly on configuration loading.

**Recommended refinement**:
- add tests for registry resolution,
- add tests for execution planning (serial vs. parallel),
- add tests for result merging and artifact archiving,
- add tests for error propagation at the orchestration layer.

**Why it helps**:
- protects the control plane of the application,
- makes future refactoring safer,
- increases confidence without requiring full nested-Containernet integration tests for every change.

## 9. Suggested future target architecture

A maintainable long-term shape for Oasis would be:

```text
CLI / shell wrapper
  -> Application service layer
     -> Config/validation layer
     -> Backend adapter layer (Containernet, testbed, future backends)
     -> Extension registries (protocols/tests/routing/analyzers)
     -> Execution engine
     -> Artifact manager
```

That target preserves the current strengths of Oasis — especially YAML-driven composition and interface-based runtime components — while reducing the amount of script-level coupling.

## 10. File map for architecture readers

If you want to understand the implementation quickly, start here:

1. `README.md` – high-level overview and user-facing workflow.
2. `src/start.py` – nested runtime bootstrap.
3. `src/run_test.py` – main runner entrypoint.
4. `src/core/config.py` – configuration model and YAML loading.
5. `src/core/runner.py` – execution pipeline.
6. `src/interfaces/network.py` – network execution contract.
7. `src/containernet/containernet_network.py` – concrete network provisioning and traffic shaping.
8. `src/protosuites/proto.py` and `src/testsuites/test.py` – extension base classes.
9. `src/data_analyzer/` – post-processing pipeline.
10. `docs/get-started.md`, `docs/protocols_and_tools.md`, and `docs/tc-strategy.md` – operational and domain-specific documentation.

## 11. Summary

Oasis already has the core of a solid, modular experimentation platform:

- interfaces define the main roles clearly,
- YAML definitions provide powerful reuse,
- runtime execution is isolated in nested Containernet,
- analyzers cleanly separate measurement from visualization.

The biggest opportunities now are **not** in adding more features first, but in **making the orchestration layer more explicit, more testable, and less string-driven**. If Oasis adopts registry-based extension points, a thinner CLI layer, a cleaner backend contract, and more focused orchestration classes, it can become substantially easier to evolve while keeping the current workflow intact.
