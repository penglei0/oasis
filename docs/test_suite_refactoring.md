# ITestSuite Extension Contract — Findings, Summary, and Proposed Solutions

This document investigates the current `ITestSuite` design, catalogues the patterns already present in the codebase, identifies the duplicated or implicit logic that makes extension harder than it needs to be, and proposes concrete refactoring steps that will make adding a new test tool (e.g. `quic_perf`) a localized, low-risk change.

---

## 1. Current ITestSuite Contract

### 1.1 Abstract base class

`ITestSuite` (defined in `src/testsuites/test.py`) is an abstract class with:

| Member | Kind | Purpose |
|---|---|---|
| `__init__(config: TestConfig)` | constructor | Creates `result_dir`, builds the log-file naming pattern |
| `pre_process() -> bool` | abstract | Hook before the test runs |
| `_run_test(network, proto_info) -> bool` | abstract | Core measurement logic |
| `post_process() -> bool` | abstract | Hook after the test runs |
| `run(network, proto_info) -> TestResult` | concrete | Orchestrates pre → validate → _run_test → post |
| `name() -> str` | concrete | Returns `config.name` |
| `type() -> TestType` | concrete | Returns `config.test_type` |
| `is_competition_test() -> bool` | concrete | Returns `False` (overridden by decorator) |
| `is_succeed() -> bool` | concrete | Returns `result.is_success` |
| `get_result() -> TestResult` | concrete | Returns `result` |
| `get_config() -> TestConfig` | concrete | Returns `config` |

### 1.2 Supporting data structures

- **`TestConfig`** — a single dataclass used by all test tools. Fields cover iperf-style parameters (`interval`, `interval_num`, `parallel`, `packet_type`, `bitrate`), rtt/ping parameters (`packet_size`, `packet_count`), scp parameters (`file_size`), and generic tool parameters (`args`). Several fields are unused by most implementations.
- **`TestResult`** — tracks `is_success`, `pattern` (file-name template), `record` (actual path), `result_dir`, and `is_competition_test`.
- **`TestType`** — enum with values `throughput`, `latency`, `jitter`, `rtt`, `sshping`, `scp`.

### 1.3 Orchestration in `ITestSuite.run()`

The concrete `run()` method (lines 115-151 of `test.py`):

1. Resolves the `base_name` from the protocol name/version.
2. Builds `self.result.record` = `{result_dir}/{BASE_NAME}_{pattern}`.
3. Calls `self.pre_process()`.
4. Validates host configuration against the network.
5. Calls `self._run_test(network, proto_info)`.
6. Calls `self.post_process()`.
7. Returns `TestResult`.

This lifecycle is sound and provides a clean template-method pattern for subclasses.

---

## 2. Catalogue of Existing Test Suite Implementations

### 2.1 IperfTest (`test_iperf.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `iperf3` |
| TestType | `throughput` |
| Protocol interaction | Reads `proto_info.get_forward_port()`, `proto_info.get_tun_ip()` to determine receiver IP/port |
| Receiver IP logic | KCP/QUIC → use `tun_ip` on **client**; BTP/BRTP with port-forward → use **client** IP; otherwise → use `tun_ip` on **server** (fallback to `server.IP()`) |
| Output | Server-side `--logfile` to `self.result.record` |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.2 IperfBatsTest (`test_iperf_bats.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `bats_iperf` |
| TestType | `throughput` |
| Protocol interaction | Reads `proto_info.get_protocol_args()` to pass mode flags (`-m 0`/`-m 1`) |
| Receiver IP logic | Always uses `server.IP()` directly (no tunnel routing) |
| Output | Server-side log via `-l` flag; separate `{proto_name}_server/log/` and `{proto_name}_client/log/` dirs |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.3 RTTTest (`test_rtt.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `tcp_endpoint` |
| TestType | `rtt` |
| Protocol interaction | Same receiver IP logic as `IperfTest` (KCP/QUIC → client tun_ip; otherwise → server tun_ip) |
| Special behavior | When `packet_count == 1`, measures first-RTT by repeating 15 times and appending |
| Port allocation | Starts at `30011`, increments per run to avoid conflicts |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.4 PingTest (`test_ping.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `ping` |
| TestType | `latency` |
| Protocol interaction | None — always pings `host.IP()` directly |
| Receiver IP logic | No tunnel/forward awareness; pings direct host IP |
| Multi-host mode | When client/server not specified, pings from every host to host 0 |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.5 ScpTest (`test_scp.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `scp` + `sha256sum` |
| TestType | `scp` |
| Protocol interaction | Uses `proto_info.get_tun_ip()` on server for receiver IP |
| Special behavior | Generates random file, transfers via scp, verifies hash integrity |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.6 SSHPingTest (`test_sshping.py`)

| Aspect | Detail |
|---|---|
| Tool binary | `sshping` |
| TestType | `sshping` |
| Protocol interaction | Uses `proto_info.get_tun_ip()` on server for receiver IP |
| Multi-host mode | When client/server not specified, tests from every host to host 0 |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.7 RegularTest (`test_regular.py`)

| Aspect | Detail |
|---|---|
| Tool binary | Configurable via `config.name` |
| TestType | `sshping` (if name is "sshping") or `throughput` |
| Protocol interaction | Uses `proto_info.get_tun_ip()` on server for receiver IP |
| Special behavior | Supports `%s` placeholder in args for target IP substitution |
| Timeout | Waits `interval * interval_num + 1` seconds, then kills process |
| Lifecycle hooks | `pre_process` / `post_process` both return `True` (no-op) |

### 2.8 FlowCompetitionTest (`test_competition.py`)

| Aspect | Detail |
|---|---|
| Pattern | Decorator — wraps another `ITestSuite` |
| Purpose | Spawns background traffic flows (TCP or BATS) alongside main test |
| Multiprocessing | Uses `multiprocessing.Barrier` for synchronized start |
| Lifecycle hooks | `post_process` rewrites `result.record` to point to wrapped test's log |

---

## 3. Identified Patterns and Code Duplication

### 3.1 Receiver IP resolution — duplicated in 5 implementations

The logic for determining where to send test traffic (receiver IP) is repeated with minor variations across `IperfTest`, `RTTTest`, `ScpTest`, `SSHPingTest`, and `RegularTest`. The pattern is:

```
if protocol is KCP or QUIC:
    receiver_ip = proto_info.get_tun_ip(network, client_host)  # tunnel on client
elif protocol provides tun_ip on server:
    receiver_ip = proto_info.get_tun_ip(network, server_host)
else:
    receiver_ip = server.IP()
```

`IperfTest` has additional logic for BATS port-forwarding mode. `IperfBatsTest` bypasses this entirely and uses `server.IP()` directly.

**Impact**: Adding a new proxy-style protocol (e.g., QUIC) requires updating the string-matching logic in every test that resolves receiver IPs.

### 3.2 Receiver port resolution — duplicated in 2 implementations

`IperfTest` and `RTTTest` both query `proto_info.get_forward_port()` and fall back to a default port (5201 for iperf, 30011+ for rtt).

### 3.3 pre_process / post_process — universally no-op

Every implementation returns `True` from both hooks. Only `FlowCompetitionTest` uses `post_process()` to rewrite the result record. The hooks exist in the contract but carry no value for current implementations.

### 3.4 Client/server defaulting — duplicated in 4 implementations

`IperfTest`, `IperfBatsTest`, `RTTTest`, and `PingTest` all contain:

```python
if self.config.client_host is None or self.config.server_host is None:
    self.config.client_host = 0
    self.config.server_host = len(hosts) - 1
```

### 3.5 Process cleanup — inconsistent

Most tests use `pkill -9 -f <binary>` to kill server processes. `IperfTest` kills both client and server iperf3. `RTTTest` kills `tcp_endpoint` from the client during the loop and from the server at the end. Cleanup is ad-hoc and inline.

### 3.6 Factory function `load_test_tool()` — string-matching cascade

`load_test_tool()` in `src/core/runner.py` (lines 96-126) uses an `if`/`elif` chain to dispatch tool names to test suite classes. Adding a new tool requires:

1. Importing the new class.
2. Adding a new branch to the cascade.
3. Remembering which extra `TestConfig` fields need to be set.

This is the single biggest friction point for adding a new test tool.

### 3.7 TestConfig is a "god dataclass"

`TestConfig` holds parameters for all test types in a single flat structure. Fields like `file_size` (scp-only), `packet_count`/`packet_size` (rtt-only), and `parallel` (iperf-only) are unused by most implementations. This makes it unclear which fields are relevant when creating a new tool.

---

## 4. Summary of Test Suite Categories

Based on the analysis, existing test suites fall into three categories:

### Category A: Throughput tools (iperf-family)

**Members**: `IperfTest`, `IperfBatsTest`

**Characteristics**:
- Client-server architecture with a long-running server and a timed client.
- Need receiver IP resolution (tunnel-aware or direct).
- Need receiver port resolution (forward port or default).
- Output: server-side log file consumed by the throughput analyzer.
- Config fields used: `interval`, `interval_num`, `parallel`, `packet_type`, `bitrate`.

**Future member**: `QuicPerfTest` (similar client-server model, potentially different CLI flags, same output format).

### Category B: Latency/RTT tools

**Members**: `RTTTest`, `PingTest`, `SSHPingTest`

**Characteristics**:
- Client-only or client-server with lightweight server.
- Need receiver IP resolution (tunnel-aware for RTTTest/SSHPingTest, direct for PingTest).
- Output: client-side log file consumed by the rtt/latency analyzer.
- Config fields used: `interval`, `interval_num`, `packet_size`, `packet_count`.

### Category C: Transfer/utility tools

**Members**: `ScpTest`, `RegularTest`

**Characteristics**:
- Task-oriented (transfer a file, run a binary).
- Need receiver IP resolution.
- Output: task-specific log.
- Config fields used: `file_size` (ScpTest), `args` (RegularTest).

### Category D: Decorators

**Members**: `FlowCompetitionTest`

**Characteristics**:
- Wraps any Category A test.
- Adds background traffic.
- Does not directly run a measurement tool.

---

## 5. Proposed Solutions

### 5.1 Extract shared receiver resolution into a helper or base-class method

**Problem**: Receiver IP and port resolution logic is duplicated across 5 test suites.

**Solution**: Add a `resolve_receiver(network, proto_info) -> (ip, port)` method to `ITestSuite` (or a mixin/utility). This method encodes the protocol-aware routing logic once:

```python
# In ITestSuite or a ReceiverResolutionMixin
def resolve_receiver(self, network, proto_info, host_role='server'):
    """Resolve the receiver IP and port based on protocol type.

    For proxy-style protocols (KCP, QUIC), the receiver is the tunnel
    interface on the client side. For tunnel-style protocols (BTP, BRTP),
    the receiver is the tunnel interface on the server side. For direct
    protocols, the receiver is the server's primary IP.

    Returns:
        tuple: (receiver_ip: str, receiver_port: int)
    """
    hosts = network.get_hosts()
    client = hosts[self.config.client_host]
    server = hosts[self.config.server_host]

    proto_name = proto_info.get_protocol_name().upper()

    # Proxy protocols: traffic enters tunnel on client
    if proto_name in ("KCP", "QUIC"):
        tun_ip = proto_info.get_tun_ip(network, self.config.client_host)
        receiver_ip = tun_ip if tun_ip else client.IP()
    else:
        # Tunnel or direct protocols: traffic reaches server
        tun_ip = proto_info.get_tun_ip(network, self.config.server_host)
        receiver_ip = tun_ip if tun_ip else server.IP()

    receiver_port = proto_info.get_forward_port()
    return receiver_ip, receiver_port
```

Each test suite would call `self.resolve_receiver(network, proto_info)` instead of reimplementing the logic. The method can be overridden if a specific tool needs different behavior (e.g., `IperfBatsTest` always using `server.IP()`).

**Benefit**: Adding a new proxy protocol (e.g., QUIC) only requires updating the list in one place.

### 5.2 Extract client/server defaulting into the base class

**Problem**: Four test suites repeat the same client/server fallback logic.

**Solution**: Move this into `ITestSuite.run()` or a helper called before `_run_test()`:

```python
def _default_client_server(self, network):
    """Default client to host 0 and server to last host if not specified."""
    if self.config.client_host is None or self.config.server_host is None:
        hosts = network.get_hosts()
        if hosts:
            self.config.client_host = 0
            self.config.server_host = len(hosts) - 1
```

### 5.3 Replace `load_test_tool()` with a registry pattern

**Problem**: The factory function is a string-matching cascade that must be manually updated for each new tool.

**Solution**: Introduce a `TEST_SUITE_REGISTRY` dictionary that maps tool names to factory callables:

```python
# In testsuites/__init__.py or a new testsuites/registry.py

TEST_SUITE_REGISTRY: Dict[str, Callable[[TestConfig], ITestSuite]] = {}

def register_test_suite(name: str, match: str = 'exact'):
    """Decorator to register a test suite class."""
    def decorator(cls):
        TEST_SUITE_REGISTRY[name] = {
            'class': cls,
            'match': match,  # 'exact' or 'contains'
        }
        return cls
    return decorator
```

Each test suite registers itself:

```python
@register_test_suite('bats_iperf')
class IperfBatsTest(ITestSuite):
    ...

@register_test_suite('iperf', match='contains')
class IperfTest(ITestSuite):
    ...

@register_test_suite('ping')
class PingTest(ITestSuite):
    ...
```

The factory function becomes:

```python
def load_test_tool(tool, test_name, root_path=DEFAULT_ROOT_PATH) -> ITestSuite:
    test_conf = TestConfig(...)
    name = tool['name']

    # Exact match first, then 'contains' match
    if name in TEST_SUITE_REGISTRY:
        entry = TEST_SUITE_REGISTRY[name]
        return entry['class'](test_conf)

    for key, entry in TEST_SUITE_REGISTRY.items():
        if entry['match'] == 'contains' and key in name:
            return entry['class'](test_conf)

    return RegularTest(test_conf)
```

**Benefit**: Adding `quic_perf` is a single-file change — create `test_quic_perf.py`, decorate the class, done.

### 5.4 Introduce per-tool config adapters (optional decomposition of TestConfig)

**Problem**: `TestConfig` is a flat "god dataclass" where most fields are irrelevant to most tools.

**Solution**: Keep `TestConfig` as the base (for backward compatibility), but let each tool define a `from_tool_dict()` class method that extracts only the relevant fields:

```python
class IperfTest(ITestSuite):
    @classmethod
    def from_tool_dict(cls, tool: dict, test_name: str, root_path: str) -> 'IperfTest':
        config = TestConfig(
            name=tool['name'],
            test_name=test_name,
            interval=tool.get('interval', 1.0),
            interval_num=tool.get('interval_num', 10),
            parallel=tool.get('parallel', 1),
            packet_type=tool.get('packet_type', 'tcp'),
            bitrate=tool.get('bitrate', 0),
            client_host=tool['client_host'],
            server_host=tool['server_host'],
            test_type=TestType.throughput,
            root_path=root_path,
        )
        return cls(config)
```

The registry entry would point to `from_tool_dict` instead of `__init__`, so each tool owns the mapping from YAML dict to its config.

**Benefit**: Config validation is co-located with the tool that uses it. `RTTTest.from_tool_dict()` can require `packet_count` and `packet_size`; `ScpTest.from_tool_dict()` can require `file_size`. The `load_test_tool()` function no longer needs per-tool branches.

### 5.5 Standardize tool output contract

**Problem**: All tools produce logs consumed by analyzers, but the mapping from tool to analyzer is implicit (handled in `diagnostic_test_results()` via `test_type_str_mapping`).

**Solution**: Each `ITestSuite` subclass should declare its analyzer name:

```python
class ITestSuite(ABC):
    @classmethod
    def analyzer_name(cls) -> str:
        """The name of the analyzer that processes this tool's output."""
        return ""
```

```python
class IperfTest(ITestSuite):
    @classmethod
    def analyzer_name(cls) -> str:
        return "iperf3"
```

This makes the tool→analyzer relationship explicit and allows `diagnostic_test_results()` to be simplified.

### 5.6 Use the `IProtoInfo` interface to eliminate protocol name string-matching in tests

**Problem**: Test suites like `IperfTest` and `RTTTest` contain `if proto_info.get_protocol_name().upper() in ["KCP", "QUIC"]` to decide routing. This string-matching breaks when new protocols are added.

**Solution**: Extend `IProtoInfo` with a method that directly answers the routing question:

```python
class IProtoInfo(ABC):
    def is_proxy_protocol(self) -> bool:
        """Whether this protocol acts as a local proxy (traffic enters on client side)."""
        return False

    def resolve_receiver_ip(self, network, client_host_id, server_host_id) -> str:
        """Return the IP that a test tool should send traffic to.
        Protocols that provide tunnels or proxies override this to return
        the appropriate tunnel/proxy IP instead of the server's direct IP.
        """
        ...
```

This inverts the dependency: instead of the test suite knowing about protocol internals, the protocol tells the test suite where to send traffic.

**Benefit**: Adding a new proxy protocol (like QUIC) requires zero changes to any test suite — the protocol implements `resolve_receiver_ip()` and test suites call it.

---

## 6. Comparison Matrix — Current vs Proposed

| Concern | Current | Proposed |
|---|---|---|
| Add new throughput tool | Edit `runner.py` factory + create new file | Create new file with `@register_test_suite` |
| Add new proxy protocol | Edit every test suite's `_run_test` | Protocol implements `resolve_receiver_ip()` |
| Receiver IP logic | Duplicated in 5 files | Centralized in `resolve_receiver()` or `IProtoInfo` |
| Client/server defaulting | Duplicated in 4 files | Centralized in base class |
| Config validation per tool | In the factory function | In each tool's `from_tool_dict()` |
| Tool → analyzer mapping | Implicit in `diagnostic_test_results()` | Explicit via `analyzer_name()` |
| TestConfig relevance | All fields visible to all tools | Tools declare which fields they use |

---

## 7. Recommended Implementation Order

The following order minimizes risk by starting with non-breaking additions:

1. ✅ **Extract `resolve_receiver()` helper** into `ITestSuite` — update existing tests to use it. This is a pure refactor with no behavioral change.
2. ✅ **Extract `_default_client_server()` helper** — same approach.
3. ✅ **Introduce `TEST_SUITE_REGISTRY`** and `from_tool_dict()` — keep `load_test_tool()` as the single consumer; migrate tools one by one.
4. **Add `is_proxy_protocol()` / `resolve_receiver_ip()` to `IProtoInfo`** — default implementation preserves current behavior; protocols override as needed.  *(Deferred — `PROXY_PROTOCOLS` constant serves as the interim solution.)*
5. **Add `analyzer_name()` to `ITestSuite`** — update `diagnostic_test_results()` to use it. *(Deferred.)*
6. ✅ **Add unit tests** for the registry, receiver resolution, and config validation.

Each step is independently mergeable and testable.

---

## 8. Impact on Future `quic_perf` Integration

With the proposed changes, adding a `quic_perf` tool would require:

1. Create `src/testsuites/test_quic_perf.py`:
   - Subclass `ITestSuite`.
   - Decorate with `@register_test_suite('quic_perf')`.
   - Implement `from_tool_dict()` with quic_perf-specific config fields.
   - Implement `_run_test()` using `self.resolve_receiver()` for receiver IP/port.
2. The QUIC protocol suite implements `resolve_receiver_ip()` to return the tunnel IP.
3. No changes to `runner.py`, `test.py`, or any other existing test suite.

This is the extension contract we are aiming for: **one new file, zero modifications to existing files**.

---

## 9. Implementation Status

The following changes have been implemented in this PR:

### 9.1 Changes to `src/testsuites/test.py`

- Added `PROXY_PROTOCOLS` frozenset for centralized proxy-protocol detection.
- Added `resolve_receiver(network, proto_info) -> (ip, port)` to `ITestSuite`.
- Added `_default_client_server(network)` to `ITestSuite`.
- Added `@register_test_suite` decorator and `_TEST_SUITE_REGISTRY`.
- Added `get_test_suite_registry()` and `load_test_suite_from_registry()`.
- Improved docstrings for `TestConfig`, `ITestSuite`, and extension contract.

### 9.2 Changes to test suite implementations

| File | Changes |
|---|---|
| `test_iperf.py` | `@register_test_suite('iperf', match='contains')`, `from_tool_dict()`, uses `resolve_receiver()` and `_default_client_server()` |
| `test_iperf_bats.py` | `@register_test_suite('bats_iperf')`, `from_tool_dict()`, uses `_default_client_server()` |
| `test_rtt.py` | `@register_test_suite('rtt')`, `from_tool_dict()`, uses `resolve_receiver()` and `_default_client_server()` |
| `test_ping.py` | `@register_test_suite('ping')`, `from_tool_dict()` |
| `test_scp.py` | `@register_test_suite('scp')`, `from_tool_dict()`, uses `resolve_receiver()` |
| `test_sshping.py` | `@register_test_suite('sshping_test')`, `from_tool_dict()`, uses `resolve_receiver()` |
| `test_regular.py` | `from_tool_dict()`, uses `resolve_receiver()` (not registered — serves as fallback) |

### 9.3 Changes to `src/core/runner.py`

- `load_test_tool()` now delegates to `load_test_suite_from_registry()`.
- Removed the `if`/`elif` cascade.
- Falls back to `RegularTest.from_tool_dict()` for unknown tools.

### 9.4 New tests

- `src/testsuites/tests/test_suite_unittest.py` — 39 unit tests covering:
  - `PROXY_PROTOCOLS` constant.
  - `_default_client_server()` with various host configurations.
  - `resolve_receiver()` for TCP, KCP, QUIC, BTP protocols.
  - Registry contents and match types.
  - `load_test_suite_from_registry()` exact / contains / unknown dispatch.
  - `from_tool_dict()` for all 8 test suite classes.
  - `load_test_tool()` integration (skipped when matplotlib unavailable).
