# Opt-in XRCE → DDS writer diagnostic

Prepared offline on 2026-10-22. **NOT RUN AGAINST XRCE CLIENTS. IDENTITY AND MOVEMENT BLOCKED.**
No publishers, vehicle services, controls, agent launch command or gate integration.

## Explicit association, not an inferred join

`prepare.py` checks four pinned source hashes, copies the native source into a **new disjoint directory**, then patches only that copy. `native-agent.patch` is its generated zero-context review diff; the authoritative recipe also adds `trace.hpp`. Do not apply the diff blindly or patch the installed agent. `source-input.json` records a prepared copy; its destination is not the build directory. Modified source/header hashes match those used for the verified build.

- Each `ProxyClient` construction gets a process-local monotonically allocated `client_instance`. This is a generation token, **not SYSID**.
- `ProxyClient::create_datawriter` establishes a thread-local RAII scope carrying the exact `ClientKey`, session_id from CLIENT_Representation, converted XRCE object_id, client generation and unique creation attempt.
- In all three synchronous FastDDS writer-creation paths (reference/XML/binary), successful native writer insertion records that lexical context, **after explicitly comparing writer_id**. No asynchronous/temporal/callback-order join is used. Missing/wrong context produces an incomplete record.
- `native->guid()`, `native->get_topic()->get_name()/get_type_name()` and the actual participant's domain_id supply native metadata. GUID is serialized from its 12 prefix and 4 entity bytes.
- The actual installed public function `rmw_fastrtps_shared_cpp::create_rmw_gid("rmw_fastrtps_cpp", native->guid())` produces the recorded RMW identifier and all GID bytes. No reimplementation, numeric-suffix decoding or invented zero padding. Installed header and library hashes, ELF dependency/symbol verification: [build record](build-verification-2026-10-22.json). That record found rmw_fastrtps_shared_cpp 6.2.10 at configure time; current analyzer supports the observed 24-byte GID contract only.
- The scope emits a separate `xrce_result` with success only after insertion into `ProxyClient::objects_`. The join key is **process identity + attempt**, with all explicit client/session/object fields checked again. Native insertion alone is insufficient.
- Writer recreation has a new attempt even when object/session IDs repeat. A new ProxyClient has a new generation even when ClientKey repeats. Reuse of a GUID/GID across attempts is rejected as ambiguous by the offline analyzer.

`Agent.cpp` and its existing graph callbacks are **unchanged**, with equal original/copied source hashes retained in [source verification](source-verification-2026-10-22.json). The synchronous call path and metadata extraction are implemented in native ProxyClient/FastDDSMiddleware. The ROS wrapper is copied and rebuilt against that library because the diagnostic adds a ProxyClient member; never mix the diagnostic library with an arbitrary old wrapper or overwrite an installed library.

Records include PID, Linux boot_id and /proc/self/stat start_ticks, process-local steady reception time and system wall time. Missing process fields are null, not guessed. Session context does not include the transport peer/socket or a verified SYSID/SITL/model association: these remain pending. Times are diagnostic observation times, not message/source times; monotonic clocks are not compared across boots/hosts.

## Opt-in and bounded output

Only `TFG_XRCE_TRACE=1` enables output. Default is silent. No payload is read or logged. Output goes to the agent's stderr as one bounded `TFG_XRCE_TRACE {JSON}` write per event. At most 512 records per process (the final slot is an incomplete `trace_limit` marker), each at most 4096 bytes; strings over 256 bytes become null. Output must be continuously drained to a private capture file during any future authorized run; a bounded number of bytes is not a guarantee that a blocked stderr pipe cannot delay a diagnostic agent.

The write temporarily masks SIGPIPE on the emitting thread and consumes a newly generated signal before restoring the prior mask, so a lost pipe reader does not kill the agent. Write/format failures stop or omit diagnostic output without changing the existing agent result/callback behavior. They do **not** prove trace completeness. The offline analyzer rejects missing completion, sequence gaps, unknown context, errors/cap markers, duplicate or contradictory records and mixed process identities. A valid trace is only an internally coherent observed prefix; it is not a process shutdown receipt or a guarantee that no later events occurred. No retries, automatic relaunch or completion claim on missing output.

## Reproducible build only

Requires the previously identified container **already running**, with full ID
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f` and image
`sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`.
Revalidate identity/state first; stop if different or stopped. No installation or download is part of the recipe.

Host preparation (a new destination is mandatory):

```bash
.venv/bin/python tools/rover_xrce_trace/prepare.py /home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent /tmp/tfg-xrce-trace-native-NEW
```

Copy that prepared source directory and `build.sh` into fresh `/tmp` paths of the verified container. Inside the existing container, the build-only recipe is:

```bash
bash /tmp/tfg-xrce-trace-build.sh /tmp/tfg-xrce-trace-native-NEW /tmp/tfg-xrce-trace-build-NEW
```

It uses existing ROS/ArduPilot prefixes; both superbuilds and dependency downloads are disabled. It compiles the native library, copies the ROS wrapper source, binds its imported native-library target to the temporary build and builds/links the wrapper. It does not install or execute either agent, even `--help`. ELF inspection uses `readelf`/`nm`, not an agent run or `ldd`. Build inputs contain temporary absolute paths, so this is a reproducible procedure, not a claim of bit-for-bit reproducibility in another directory.

Actual 2026-10-22 results, not just doubles:

| Stage | Result |
|---|---|
| Host synthetic C++ scope and Python analyzer regressions | Passed; no ROS/DDS instantiated |
| Actual native sources and ROS headers | Full compilation passed, including all three writer variants |
| Native shared library link | Passed; SHA-256 `5bae08d754e8113b99c1d418154f907754168b1217b5be18c0969738def55703` |
| ROS micro_ros_agent wrapper link | Passed; SHA-256 `b1330420c764240c971263d5ec7abea3da82a46555bf677a2f21a1d78694325c` |
| Agent execution / received real diagnostic association | **Not performed** |

Temporary built wrapper: `/tmp/tfg-xrce-trace-link-20261022/agent-build/micro_ros_agent`;
native library: `/tmp/tfg-xrce-trace-link-20261022/native-build/libmicroxrcedds_agent.so`.
A separate incremental build/static verification is retained; the first full build's tool output was observed but not archived as a raw log. CMake emitted existing TinyXML2 package-name warnings and an unused PYTHON_EXECUTABLE warning; compilation/link succeeded.

## Offline reader

No CLI/runtime route was added. Example for a **future saved log**, not an execution command:

```python
from tools.rover_xrce_trace.analyze import analyze
report = analyze(open("agent-stderr.log").read().splitlines())
```

All results stay BLOCKED, `source_association_verified=false`, `movement_authorized=false`. The reader preserves the native GUID and converted GID separately. It never interprets a graph candidate as the sender of a sample, never matches by numeric similarity, and never authenticates a publisher cryptographically.

## Protected optional selection — implemented offline, not operated

The earlier missing selector is now implemented in the existing lifecycle. **Default remains the installed agent**; no diagnostic helper or overlay is selected unless the caller explicitly supplies a manifest. Inherited diagnostic environment variables are cleared. This increment does not expose a new MCP control tool or a manual agent launcher.

The host CLI accepts `--diagnostic-agent-manifest PATH` only with `start --profile two_drones_rover`. Stop/restart and other profiles reject that option before locks/backend side effects. Ordinary stop needs no selector; it uses the same existing PID/start_ticks ownership and shutdown protocol for the launch, agent and passive monitor.

[diagnostic-agent.example.json](diagnostic-agent.example.json) is the prepared manifest, **not consent or a report of an opening**. Its container ID/image, engine and current build hashes were rechecked during this increment. The library path is the real `.so.2.4.2`, not a symlink. The selector intentionally supports only the reviewed wrapper/native pair above. A rebuild producing a different pair must be reviewed and pinned explicitly; do not silently rewrite hashes to bypass rejection.

Under the existing executor/registry exclusion and durable lifecycle lease:

1. The host pins the descriptor to the lifecycle UUID, manifest digest and current helper hashes. It verifies the exact **already-active** engine/container/image. Diagnostic mode never starts a stopped container.
2. The backend verifies its inherited lease/descriptor, binds Docker calls to the full container ID and validates artifacts **before cleanup/start**. Missing, changed or symlinked build artifacts, ELF linkage mismatch, an existing agent, or a reused overlay path fail closed. The exact wrapper/library pair is checked, not just matching filenames or ELF SONAMEs.
3. It creates a fresh private `/tmp/tfg_diagnostic_agents/<lifecycle UUID>/` ament overlay. Wrapper and native library are copied with pinned hashes, along with the reviewed passive helper sources. No installed package/library is replaced. The overlay marker selects `micro_ros_agent` via ament; its lib directory is prepended for native-library loading. ROS domain/configuration, launch arguments, UDP port 2019, DDS middleware and `/drone1` agent namespace are retained from the ordinary launch. No second agent is started by a helper.
4. The existing supervisor creates the fresh launch log, starts one tagged passive monitor **before** the normal ROS launch, saves both process identities and the protected launch identity, and starts the existing passive rover worker. It retains monitor ownership when saving the rover worker state.
5. The monitor observes the actual agent executable, PID/start_ticks/container boot, launch ancestry, expected transport/namespace arguments and mapped native library. Its initial observation has an 8 s budget; the supervisor waits at most 10 s for that observation. Wrong/mixed libraries or duplicate agents fail; a not-yet-loaded native mapping is pending, not a fabricated success. Startup failure propagates to the existing UNCONFIRMED lifecycle restriction with no retry or cleanup bypass.
6. Lifecycle shutdown targets only attributable identities. Unknown diagnostic auxiliaries block cleanup rather than becoming signal targets. The host also retains `diagnostic_agent_session.json` beside the lock directory, pins the original engine/container/image for stop and refuses a new start/restart until explicit closure. This target is not a flight reservation or identity approval; existing global restrictions still take precedence. Stop rejects a substituted/unknown environment and uses the full container ID, treating Docker inspection errors as UNKNOWN rather than stopped. A recorded close target is checked without retrospectively requiring the current helper/build revision. Shutdown includes the diagnostic summary, which is labelled **last diagnostic session**, not an active reservation. Runtime capture files are preserved. `success=true` for infrastructure shutdown does not turn an incomplete diagnostic into valid identity.

### Passive supervision and bounds

The launch's existing stdout/stderr file remains the continuously drained source (`/tmp/tfg_demo.log`). A private monitor follows that file from its beginning, extracts raw `TFG_XRCE_TRACE` bytes and records its own observation times separately from source timestamps. It never publishes, calls a vehicle service, starts/restarts an agent or changes a gate.

Bounds: 512 trace lines, 2 MiB trace output, 8 KiB source-line buffer, 64 MiB source scan and **600 seconds wall time** for the monitor. Reads are 64 KiB with 100 ms idle polling; process/library observations are once per second. Full artifact hashes are rechecked at initial observation and closure; intermediate samples inspect paths/mappings, not a claim of continuous tamper-proof authentication. Existing readiness/lifecycle timeouts are unchanged. The diagnostic limits are not a sleep or permission to extend an attempt.

Capture output is 0600 under a 0700 overlay. The monitor records raw truncation/cap/error markers, byte/record counts, process facts and closure. Short write, flush/fsync/close failure, lost monitor, replaced/truncated source log, changed helper/artifact or missing process observation leaves an incomplete/failed diagnostic. Partial context is preserved. On lifecycle SIGINT/TERM the monitor drains while the attributable launch/agent close, for at most 10 s; no automatic flight/process restart occurs. A killed/missing monitor cannot produce a trusted closing receipt.

`phase=OBSERVING` means process/library observation, **not full identity or complete trace**. A `CLOSED` monitor receipt only means bounded capture closure; run the separate native trace analyzer to validate the join records. Every report keeps `status=BLOCKED`, `source_association_verified=false`, `movement_authorized=false`.

Artifact layout for the new lifecycle UUID:

- `selection.json`: descriptor, artifact/helper hashes and source paths.
- `launch.json`: protected launch PID/start_ticks/boot.
- `capture/trace.log`: raw extracted lines, including an unterminated tail when within bounds.
- `capture/monitor.json`: latest sourced observation, errors, limits and final receipt.
- `capture/supervisor.log`: monitor stdout/stderr; `capture/monitor.claim` prevents a second monitor.
- `/tmp/tfg_demo.diagnostic.json`: pointer to the **last** session only; not a guard, authorization or claim of current activity.
- Host lifecycle `operation.json` and `backend.log`: existing returned operation paths. They retain selection and failure state.

### Next single trial — PROPOSED, NOT AUTHORIZED OR EXECUTED

Obtain separate authorization covering one protected GUI opening, passive trace/reception and protected closure. First inspect restrictions, processes and exact environment with the existing read-only controls. Stop on UNKNOWN/UNCONFIRMED/APPLYING, an existing agent/session of uncertain provenance, changed engine/image/artifact, or ambiguous ownership. Do not reconcile, unlock or join an old session to make the test possible.

The real command prepared for **after authorization** is:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.example.json
```

Without the last option, the installed agent is selected. Do not replace the installed binary, alter launch arguments or invoke the diagnostic agent separately. The project cannot prevent privileged/external ROS clients from bypassing its controls; it detects existing/duplicate agents where observable and does not claim OS-wide exclusion.

Expected automatic observation: one selected agent, correct maps and an OBSERVING monitor; backend topic availability remains distinct from full readiness, GUI visibility and identity. Ask Joel whether the track and all three vehicles are visible and wait for the real response. A black/no-window response is recorded separately, not repaired with a restart.

Record HEAD, effective source/helper/overlay/binary hashes and environment/process identities in a new evidence directory. Save trace from the opening, before receiving Status. Do not add vehicle service calls merely to fill identity; this proposed test does not require `check_sim.sh`/prearm services. No changes to QoS, DDS parameters, model, renderer, timeouts or limits.

Use the existing collector only after verifying its independently reviewed binary. Prepared unexecuted cap-validation collector: `/tmp/tfg-rover-quota-cap-link-fefyp58g/build/rover_passive_collector`, SHA-256 `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93`. The historical successful capture used **43d5…**, not this binary. Stop if the prepared collector is missing/changed; do not substitute or rebuild during the attempt.

Inside that same accredited ROS environment, with a **new 0700 directory**, the separately authorized passive command would remain:

```bash
/tmp/tfg-rover-quota-cap-link-fefyp58g/build/rover_passive_collector --output "$NEW_PRIVATE_DIR/journal.jsonl" --max-samples 20 --duration-s 120 --reserve-streams > "$NEW_PRIVATE_DIR/receipt.json" 2> "$NEW_PRIVATE_DIR/stderr.txt"
```

Capture rc immediately, without a retry. The 120 s exploratory budget does not guarantee Status. Preserve raw files, receipt, hashes and graph candidates separately. Do not increase any budget or retry an incomplete stream.

Close with the ordinary protected command, without passing the selection again:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones_rover
```

Retain its process verification, diagnostic summary and monitor receipt; copy/hash the private overlay capture and the fresh launch log before any later opening. If closure is blocked/uncertain, stop and preserve restrictions, without manual signals/restarts. Infrastructure closure and capture completeness are reported separately.

Offline, use the existing journal analyzer for MessageInfo and `tools.rover_xrce_trace.analyze.analyze` for native trace records. Require one internally consistent process/session capture and exact equality between Status's **per-message** GID/RMW identifier and the native conversion record. Check native topic/type/domain against the captured ROS/type-support configuration; do not infer a conversion from similar names. Require the explicit matching client generation/attempt and successful XRCE commit, not session/object IDs or temporal proximity alone. Reject mixed-session evidence, contradictions, caps and missing records.

That would resolve **DDS Status endpoint → XRCE client/session/object** for the new run only. It would not prove cryptographic authentication, peer/socket→SITL instance, effective SYSID/DDS namespace, binary-source provenance of SITL, or bridge/plugin/model association. Gazebo odometry follows its bridge branch, not XRCE. Graph candidates remain candidates; even a complete join does not populate the Python worker's missing per-message GID or change the rover guard. Identity and movement remain BLOCKED.

### Verification scope

[selection-verification-2026-10-22.json](selection-verification-2026-10-22.json) records this increment's actual tests and incremental real-target/ELF verification. Earlier `checksums.json`, `offline-verification.json` and build records are historical snapshots retained unchanged; their old documentation hashes are not a claim that updated README text is byte-identical. No real overlay, agent, monitor, simulation or collector was started for this selector increment; overlay/process/closure tests use temporary files, fake ELF metadata and fake processes/clocks.

## Recovery review — 2026-10-23

The failed 22 October opening and its original evidence remain intact. The deployed helper-name regression is now covered by running the actual renamed `prepare` entry in temporary files, including the archived original that fails. A read-only informative recovery inspection (no TTL/preparation/application) and the pending one-shot scope-authorized fresh preparation/application are documented in [the existing recovery guide](../../docs/rover-xrce-prelaunch-recovery-2026-10-22.md#procedimiento-revisado--2026-10-23). No recovery or subsequent trial has been executed. The prepared wrapper/library/collector hashes were read again and match; this is availability, not operational validation. The next single-trial recipe above remains proposed and needs separate authorization after confirmed recovery.

## Passive UDP inventory and generation-bound peer — prepared 2026-10-24

The completed trial `eb113b19-4923-4983-bed4-2e99db1aa512` is immutable (119
manifest entries). Its Status GID/RMW matched native writer creation and XRCE
commit exactly. The updated chain, exact identifiers/hashes and remaining
uncertainties are in [the existing source matrix](../../docs/rover-source-correlation.md#matriz-actualizada--ensayo-único-del-24102026).
The session log's peer line has no ProxyClient generation. ClientKey/session
alone must not be used to join it across recreations.

Two preparations are separate:

- `socket_inventory.py` is part of the existing `selection.HELPERS` deployment.
  The selected monitor calls its read-only child inside the accredited process
  and network namespaces after observing the agent. Normal installed-agent mode
  does not start this monitor. No Docker, shell, ROS, publishers or services are
  added to the inventory. It reads `/proc` only, redacts arbitrary argv, records
  before/after metadata, and never changes identity or movement authority.
- The **new source variant**, `peer-agent.patch` plus `peer_endpoint.hpp` and
  current `trace.hpp`/`prepare.py`, binds InputPacket.source lexically to the exact
  ProxyClient reference used for writer creation. Metadata attached before moving the InputMessage unique_ptr into its session
  queue retains the original peer and validates the exact client instance; reassembled fragments force an
  unavailable peer rather than inheriting the last fragment. Optional `transport_peer` in
  writer/commit records must agree in the existing analyzer. Unsupported context
  is null; legacy records remain valid without inventing peer metadata. The
  getter uses the existing client_instance token and the creation attempt, not a
  later lookup by key. This observes the creation packet's peer, not all future
  Status packets or continuity across a reset/re-established peer.

`peer-source-preparation.json` records the disjoint local source copy and pinned
inputs (seven: the original four plus Processor.cpp, IPv4EndPoint.hpp and
InputMessage.hpp). The old
`native-agent.patch`, checksums and build verification files remain historical
22 October artifacts. **No new agent/wrapper was compiled, linked, installed or
executed for this increment.** The existing pinned binary pair lacks the new peer
metadata and its hashes have NOT been silently replaced. A real compatible
native/wrapper build and explicit selector/manifest hash review are prerequisites
before offering another executable trial. The small host C++ tests exercise the
lexical helper and the exact public IPv4 endpoint header, not an agent or a full
Processor build against ROS/FastDDS.

### Socket contract and bounds

Each row of private `capture/sockets.jsonl` contains protected context declarations,
observed namespace/boot/process identities, UDP4/UDP6 endpoints, socket inodes,
FD owners, permitted argv, and timestamped read provenance. It compares two
process/FD sweeps and before/after tables/context. UDP unconnected, wildcard binds,
SO_REUSEPORT-style duplicate endpoints, shared/inherited FDs, unreadable/disappeared
processes, PID reuse, namespace changes, truncation and exhausted budgets stay
explicitly ambiguous/incomplete. No owner visible is not absence of communication.
This is NOT an atomic snapshot; ABA/FD transfers between reads are not ruled out.

Nominal query bounds: 250 ms cooperative, 128 PIDs, 2048 FDs per pass, 1024 reads,
128 KiB serialized output; monitor child timeout 750 ms. Kernel stalls cannot be
preempted by a Python read; the outer timeout attempts to terminate only its own
query child, never an agent/SITL/discovered process. This is not a demonstrated
real-environment latency guarantee. A child timeout/persistence error disables
that channel with UNKNOWN, without changing trace or vehicle behavior.
The existing monitor may schedule 64 distinct observations every 5 seconds,
up to 8 MiB, and explicitly reports exhausted coverage. Partial race observations
are retained separately; they are not repaired or promoted. This does not extend
the existing trace/monitor bounds or Status capture limits. The socket summary is
separate from the native trace's closing receipt; CLOSED for trace is not socket
association success.

Offline, `socket_inventory.analyze_series(data, monitor_summary, writer,
lifecycle_id)` uses a native writer already validated by `analyze`; it retains
partial/changing rows and rejects mixed context/counts or truncated records.
`match_peer` matches the peer to a **local** UDP endpoint, then inode→FD→process,
without choosing by executable/node name. Even a repeated unique visible owner
is labelled a candidate, with `packet_origin_verified=false`. Nothing infers
SYSID effective from the socket, `--sysid 3`, or ClientKey suffix.

### Future incorporation, not authorization

After the missing real build/link and hash review, use one new protected session
with the existing diagnostic selector; no standalone second agent or manual socket
collector. Preserve trace + socket channel from startup, wait for actual operator
visual confirmation, perform at most one 20-sample/120-second/reserve-streams
Status/odometry capture, and close normally. No services/prearm or movement.
Recheck artifacts/context first. If native peer generation is missing, socket
owners change or records are incomplete, retain BLOCKED; do not infer or retry a
flight/capture. Review all scheduled socket observations, not just a favorable
row. See the source matrix for the full minimal evidence and public-parameter
availability limits. No such opening or collection was performed in this task.

The added InputMessage metadata member changes its ABI. A full native/wrapper
rebuild and link check are required; an old installed library must not be mixed
with objects compiled against this header. No such build was run for this variant.

## Peer variant: real compile/link verified — 2026-10-24

This supersedes the **source-only build pending** status above for the peer
variant. It does not supersede the immutable historical trial or its original
binary pair. [Build log](peer-build-2026-10-24/build.log),
[inputs](peer-build-2026-10-24/inputs.json),
[verification](peer-build-2026-10-24/verification.json) and the exact
[static-check script](peer-build-2026-10-24/verify.py) record this build.

The engine/container/image and creation/start timestamps matched the accredited
running environment. `prepare.py` checked all seven pinned native sources before
copying them into a new disjoint host temporary directory. Only that copy and the
existing wrapper sources/dependencies were used. The build ran in the container:

```bash
bash /tmp/tfg-peer-build-20261024-swzvihrs/build.sh /tmp/tfg-peer-build-20261024-swzvihrs/source /tmp/tfg-peer-build-20261024-swzvihrs-build
```

Both native and ROS wrapper targets compiled and linked successfully. Static
inspection checked SONAME/NEEDED/RUNPATH, exported native symbols required by the
wrapper, all 51 native header dependencies consumed by the wrapper and the native
InputMessage/peer-header dependencies. A first static assertion incorrectly
expected ProxyClient.hpp to be included directly by the wrapper; it was replaced
with the actual dependency-origin check. No code/build change was needed for it.
Installed wrapper/library hashes still match the historical installed hashes.
No agent/wrapper (including `--help`), monitor or collector was executed; no
runtime-loaded library mapping was observed. No install, network or downloads.

| New artifact inside the accredited container | SHA-256 |
|---|---|
| `/tmp/tfg-peer-build-20261024-swzvihrs-build/agent-build/micro_ros_agent` | `2c81395a0aaf5aaac094e302c69edbe357975f200947578e9b4ca7eaf17a63a8` |
| `/tmp/tfg-peer-build-20261024-swzvihrs-build/native-build/libmicroxrcedds_agent.so.2.4.2` | `cf2537265cb64b9ea0f52737306be6166e0a4456a4a2c94b21319b2298a097fa` |

[diagnostic-agent.peer.json](diagnostic-agent.peer.json) selects this exact pair.
The selector accepts the reviewed historical pair and the reviewed new pair,
never a cross-generation combination. `diagnostic-agent.example.json` remains
historical and does **not** provide peer metadata. Normal installed-agent mode
is unchanged. Future selection must use the peer manifest explicitly; none of
these files constitutes consent to start.

For a separately authorized single future trial, after fresh identity,
restrictions/process checks and atomic lifecycle revalidation, the start entry is:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.peer.json
```

Do not execute it under the build authorization. Recheck all hashes and helpers;
missing `/tmp` artifacts block the trial, with no silent reconstruction. Observe
exactly one selected agent, its new loaded library and diagnostic monitor; obtain
operator visual confirmation. Then, only under separate trial consent, one
Status/odometry capture (20 samples/120 s/reserve-streams), protected stop, and
same-session offline analysis of native peer context and socket journal. No
readiness/prearm, vehicle services or controls are needed for this diagnostic.
Peer may remain null for unproven/reassembled input, and socket sampling may be
incomplete or ambiguous. Build success does not demonstrate peer attribution,
socket ownership or live capture. Effective SYSID and the bridge/model branch
remain unverified; full identity and movement remain BLOCKED.

## Last-session pointer precheck correction — 2026-10-24

The peer attempt `3c3b6544-3324-4ac6-970d-776cb059d4c8` stopped before opening
because its evidence driver treated **every** supervisor state file as active or
uncertain state. This was a precheck classification defect, not a failed native
build or a demonstrated active session. The supervisor's `diagnostic_summary()`
already labels `/tmp/tfg_demo.diagnostic.json` as
`LAST_DIAGNOSTIC_SESSION_NOT_A_RESERVATION_OR_IDENTITY_APPROVAL`; `shutdown()`
intentionally retains it while deleting process/PID files. Its existence alone
neither proves activity nor proves closure.

The pure reader [session_precheck.py](session_precheck.py) uses existing frozen
descriptor rules and does not launch, clear metadata, recover, change a gate or
write runtime state. It admits a retained pointer only as
`HISTORICAL_CLOSED_POINTER` when all supplied evidence agrees:

- The descriptor and its digest match the host CLOSED target, the FINISHED start
  and its identified FINISHED stop operation. An unknown/missing/malformed target
  or descriptor, missing/contradictory closure or other owner is BLOCKED.
- The original overlay selection and helper/binary hashes match the frozen
  descriptor, independent of today's new helper version. Launch and monitor
  records have process identities, and the monitor has requested closure,
  phase CLOSED, capture_complete=true, no errors and the recorded mapped library.
- Current engine/container/image/creation identity, container start incarnation
  and boot match that recorded context. Current process reads are complete with
  no owned/ambiguous process or agent, and no other PID/process state file.

The corrected read-only driver gathers those records under existing execution
and registry exclusion, checks environment and host-record stability again, and
retains copies/hashes. Unknown reads still fail closed. This changes only the
precheck's historical-pointer classification; normal lifecycle exclusion,
reservations and start/stop behavior are unchanged. Old helpers are checked
against their **frozen** hashes, never reinterpreted against the peer build.

The new [read-only review](../../simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_24/fa427bba-755d-4194-9b28-1d9a85c854ba/precheck.json)
returned **CLEAR**, with no opening, monitor, collector, stop or recovery. The old
blocked attempt and historical receipts remain unchanged. CLEAR is a bounded
current inspection, not a durable permission, full identity approval or proof
of ground contact. This attempt did not execute the protected trial.

A future trial needs separate authorization and a fresh precheck plus the
lifecycle's own atomic revalidation. Its existing start command remains:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.peer.json
```

Do not delete the pointer to make a precheck pass or rerun evidence drivers into
an existing result directory. No peer binaries/hashes were changed or rebuilt.
Full identity and movement remain BLOCKED.

## Socket budget, GUI exit observation and next peer trial — 2026-10-24

This update supersedes the expanded socket serialization described above, without
changing any acquisition/output/time limits or historical files. The last closed
session was `f3380567-b48a-4e47-b4c5-c3be066a76d1`; its 64 socket rows remain
OUTPUT_BUDGET_DATA_INCOMPLETE, not repaired or reclassified.

### What was corrected offline

The expanded representation repeated per-read keys/paths/times, before/after UDP
rows, process/argv data in FD owners, and again in derived associations. The
budget was applied to that expanded form, so all useful ownership rows were
removed before the monitor could persist them. The **row-local version 2 wire
format** now stores explicit tables of source paths, UDP sockets, processes,
permitted argv and owners. Before/after and association records reference these
tables; read columns are named once and preserve every original source ID,
UTC reception and monotonic interval. Each JSONL row carries its own context and
pools: no dependency on an earlier row surviving. No message payloads or arbitrary
argv/environment data are added.

The existing reader expands version 2 and retains support for historical version
1. Missing/out-of-range references, noncanonical/contradictory tables, incomplete
context/provenance, before/after disagreement or associations inconsistent with
their source tables fail closed. The first and second ownership sweeps both need
valid provenance. Re-encoding/reference consistency is **not** a signature or
protection against an attacker rewriting an entire self-consistent evidence set.
Unavailable data and shared sockets remain unknown/ambiguous. A usable repeated
endpoint/FD/process observation remains a candidate, never full identity.

Limits remain 128 KiB per row, 1024 reads, 128 PIDs, 2048 FDs/pass, 250 ms cooperative
query budget, 750 ms monitor child timeout, 64 observations every 5 seconds, and
the existing 600-second monitor/trace bounds. The newline counts toward monitor
serialization; oversize/truncated output remains incomplete/uncertain. A
synthetic representative fixture (32 processes, 802 reads, including a simulated
SITL/agent and ordinary launch processes) serializes at **69,490 bytes**, versus
**137,673 bytes** expanded, under the unchanged **131,072-byte** cap. It is not a
reconstruction of the discarded historical data, a performance benchmark or a
real-environment latency/completeness guarantee. Real process count/churn can
still exhaust any budget and must remain BLOCKED.

131 affected tests passed after correcting the related regressions. They cover
fake /proc → collector representation → monitor fake transport → real JSONL
serialization → existing offline reader/analysis, including truncated writes,
missing/contradictory references, reused PID/start_ticks, shared sockets,
disappearance, volume overflow and preserved BLOCKED identity/movement. An
initial run found three failures (the old size assertion needed to check wire
bytes, first-sweep provenance was not checked, and a mutation fixture needed to
represent an actual before/after contradiction); the subsequent run passed.
A final missing-declared-context case exposed an exception path; it now returns
UNKNOWN instead of escaping the analyzer. Only the affected socket suite was
rerun after that change: **42 passed in 0.68 s**. The earlier combined run was
**131 passed in 6.15 s**. No operational monitor or socket collection was
performed in these tests.

### GUI diagnosis: observations and limits

The preserved `tfg_demo.log` of f338 explicitly reports GUI command
`ruby /usr/bin/gz sim -v1 -g --force-version 8` exiting **134** (line 857).
Lines 678–716 record `D3D12: Removing Device`, Ogre RenderingAPIException,
`glGetError code: 1285`, and a **134217728-byte (128 MiB)** allocation requested in
`GL3PlusVaoManager::allocateVbo`, followed by abort. The exception says
"Out of GPU memory or driver refused"; it does not select between those causes.
No GPU memory occupancy/budget counters or device-removal reason were captured.
An allocation request is not a measurement of VRAM capacity or free memory.

The shared OGRE log records OGRE 2.3.1, GL 4.1/Mesa
23.2.1-1ubuntu3.1~22.04.4, renderer D3D12 (Intel UHD Graphics), texture budget
stall/free messages and GLSL sampler warnings. It includes a software EGL device
probe; this alone does not prove that the final scene ran in software. The log
path is shared by render activity and cannot attribute every line to GUI PID 9017
by itself. Current read-only package metadata confirms the same Mesa package
version, without querying private configuration or changing rendering. Missing
`package://ardupilot_gazebo` mesh/material resources are separately observed;
no evidence establishes that they caused the VBO exception. None of this
establishes a connection to XRCE/SITL identity or a prior ROS timeout.

Previously the diagnostic monitor observed agent/library identity but did not
report the GUI's later exit separately. It now parses an explicitly attributed
GUI `process has died` launch-log event into `gui_observation`: PID, exit code,
source and wall/monotonic **reception** times. `EXITED` does not affect lifecycle
exclusion/cleanup or its backend result. Missing/unattributable exit remains
UNKNOWN, conflicting exits CONTRADICTORY; process-start text does not prove GUI
liveness or rendering. Zero/negative/positive reported exit codes are retained
when that explicit event exists. No exit event is **not** a claim of a successful
GUI, and visual confirmation always requires the operator. The parser adds no
monitor process, launch callback, retry or automatic intervention. Observation
uses the existing bounded source drain, so missing/truncated source can hide an
exit and must be considered unknown.

### Artifacts and single future protected trial (NOT EXECUTED)

[peer-helper-verification-2026-10-24.json](peer-helper-verification-2026-10-24.json)
records current static reads: the accredited active engine/container/image and
the existing peer wrapper/library and collector hashes still match. All native
build inputs are unchanged: **no native or wrapper rebuild is required**. Only
`monitor.py` and `socket_inventory.py` changed in the deployed diagnostic helper
set; the next lifecycle descriptor must freeze their new hashes via the existing
selection/deployment logic. Do not reuse an old overlay or edit its frozen hashes.
The manifest, reviewed selector pairs, transport peer/RMW conversion and native
trace schema remain unchanged.

- Wrapper: `2c81395a0aaf5aaac094e302c69edbe357975f200947578e9b4ca7eaf17a63a8`.
- Native library: `cf2537265cb64b9ea0f52737306be6166e0a4456a4a2c94b21319b2298a097fa`.
- Passive collector: `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93`.
- Selection: `diagnostic-agent.peer.json`; existing /tmp paths are recorded there
  and in the verification JSON. Missing/changed files block; no automatic repair.

**One proposed graphical check, within the next separately authorized peer
session:** hypothesis: the GUI can again fail during initial render allocation
while the server remains available, before any Status collector starts. Keep
profile, models, QoS, renderer, variables and lifecycle limits unchanged. Observe
for at most 60 seconds of wall time after startup, preserving launch/OGRE logs
and actual operator confirmation of pista/two drones/rover. This is an observation
window, not a sleep, warm-up solution or performance comparison. A reproducible
attributed GUI exit/error supports this failure mode; an intact scene only
establishes that opening's success, not a permanent fix or a VRAM cause. No
benchmarks, renderer switches, automatic restart or second opening.

The single future session sequence, conditional on explicit authorization:

1. Fresh read-only precheck: all guards/restrictions, processes, engine/container/
   image/incarnation and frozen artifacts. A coherent historical CLOSED pointer
   is permitted by `session_precheck`; corrupt/contradictory/missing closure blocks.
   Lifecycle still performs its own atomic admission. Do not reuse an old CLEAR.
2. Use the exact existing start entry with `diagnostic-agent.peer.json`. Confirm
   one selected agent, its mapped peer library, monitor OBSERVING and socket
   channel with complete, decodable observations (no budget/persistence error).
   Offline fixture success does not satisfy this live check.
3. Complete the one graphical observation above and wait for the operator's
   real confirmation. On GUI exit, ambiguous ownership, failed supervision or
   incomplete socket context, preserve evidence and perform only protected stop;
   do not run Status capture or retry.
4. If all checks pass, run the existing collector exactly once, with
   `--max-samples 20 --duration-s 120 --reserve-streams`, in a new private directory.
   Preserve journal/footer, receipt, stderr, return code and all source hashes.
5. Protected stop, then current process/guard/target checks and monitor receipt.
   Do not force manual cleanup on uncertainty. Preserve all three results:
   infrastructure closure, stream coverage, and correlation validity.
6. Analyze only that session: exact Status MessageInfo GID/RMW → native writer
   GUID/conversion → confirmed XRCE creation with matching process/boot/start_ticks,
   attempt, client_instance, ClientKey/session/object/topic/type/domain. Match the
   generation-bound native peer to a normalized local UDP endpoint → inode → all
   FD/PID/start_ticks/namespace owners and both reading sweeps. Reject missing
   context, changed owners, wildcard-only/shared/duplicate sockets, partial rows
   or mixed sessions. Review the whole socket series, not a favorable row.

A socket association remains observational and non-atomic; it does not prove
which owner sent a particular UDP packet, continuity across client resets,
effective SYSID or bridge/model provenance. `--sysid 3` remains observed argv,
not a read of SYSID effective. Full identity and movement remain BLOCKED even
when every diagnostic join succeeds.

### Following the code in VS Code

Use Ctrl+P to open a path, Ctrl+Shift+F for a function name and F12/Go to Definition
(or Find All References) to follow these existing diagnostic boundaries:

| Component/function | Role and evidence |
|---|---|
| `selection.py: descriptor`, `deployment` | Freezes/deploys the reviewed helper set and exact native pair; ordinary mode stays installed-agent mode. |
| `monitor.py: SocketRecorder.sample` | Schedules bounded passive reads and persists their wire JSONL. Fake transport is used only in tests. |
| `socket_inventory.py: collect`, `pack_inventory`, `unpack_inventory` | Reads /proc metadata; stores explicit references; reconstructs and rejects broken references. No payloads/control. |
| `socket_inventory.py: validate_inventory`, `match_peer`, `analyze_series` | Offline provenance/contradiction checks and endpoint/FD/process candidates; no new query or approval. |
| `monitor.py: Drain.feed`, `GuiObservation.feed` | Drains native trace and separately observes attributed GUI exit from the existing launch log. |
| `tests/test_rover_socket_inventory.py: pipeline` | Shows the complete fake /proc/transport → wire → file → reader → analysis path. |

`simulation_lifecycle.py` and `sim_processes.py` remain the protected runtime
orchestration/cleanup path; this increment did not change them. The selected
native peer library, monitor and /proc helper are **opt-in diagnostic
instrumentation**, not a rover movement executor. Offline readers/tests are not
needed to keep the simulation running. A GID identifies the endpoint that supplied
a sample; a socket inventory identifies visible owners of a network endpoint.
Neither reads SYSID or authenticates the complete vehicle chain.

## Peer-first search and measured budget diagnosis — 2026-10-24

This supersedes the all-UDP search and the small-fixture preparation claim above.
It does not change limits, native binaries, gates, historical results or consent.
Measurements, exact executed-source hash and byte breakdowns are retained in
[socket-scope-verification-2026-10-24.json](socket-scope-verification-2026-10-24.json).

### Accredited cause versus missing history

The 110-entry trial `cedfd5c5-9955-4ca0-b61a-0a4bda305098` is unchanged. It retained
39 rows: 37 OUTPUT_BUDGET_DATA_INCOMPLETE, two ENOENT. All 37 fallback rows lack
table-after provenance: the search had already stopped before completing both
sweeps. The old fallback then overwrote its earlier reason. Only 32 read events
and cleared socket/owner pools survived those fallbacks. **The original section
sizes, total PID/FD counts and earlier failure types cannot be reconstructed.**
The 23 attributable processes in the process inventory are not the complete
/proc population. Retained rows occupy 2,329–57,066 bytes *after* fallback; that
is not their pre-fallback size. ENOENT does not mean no owner.

What the exact executed source establishes: it parsed every UDP socket, scanned
all FDs, gathered executable/namespaces for every process twice per pass, and
kept owners and derived associations for **unrelated** UDP endpoints. The wire
format still serialized provenance for the broad search. That unnecessary scope
consumes both reads and bytes. Executing the frozen source (SHA-256
`8f541fde54bb6f0d9fb0344913012012891b6429088dd4ef5da75eb83ea82907`)
on synthetic fake /proc reproduces a pure byte overflow with no earlier error.
This proves the algorithmic failure mode, not the missing historical topology.

For that reproducible synthetic case (23 processes, 100 unrelated UDP sockets),
the old 161,541-byte wire row breaks down as follows (JSON value bytes, excluding
keys/separators/framing): reads/timestamps **84,449**, source paths **5,100**,
sockets **32,021**, FD-owner/provenance records **27,050**, process identities
**275**, permitted argv **217**, context/derived references/remaining record
**12,185**. Process identities alone were not the main byte consumer. The new
search's corresponding value bytes are 54,531 / 4,000 / 313 / 235 / 135 / 105 /
2,061; framing and diagnostic accounting are included in the totals below.

### Concrete search change

`SocketRecorder.sample` now waits for the existing native analyzer to validate
a coherent writer/commit prefix and select the explicit `rt/ap/v3/status` topic.
This is selection of the requested diagnostic stream, **not identity assignment
from its name**. All distinct native peers for that stream are retained; process
boot/PID/start_ticks must match the observed selected agent. No peer, partial
creation or unknown context means WAITING_NATIVE_PEER/blocked, never a fallback
to scanning every endpoint. Pending/invalid peer context also prevents the
series reader from accepting prior rows as a complete result.

The existing analyzer is deployed as an additional **existing-code helper** in
`selection.HELPERS`; no new module, operational API, agent or control path was
introduced. All helper paths/hashes are frozen in the next fresh descriptor.
The installed-agent/default path remains unchanged.

The /proc helper reads the full UDP4/UDP6 tables, validates them, and retains only
local endpoints matching those explicit peers, including wildcard binds. It
records total/relevant table counts and full-table hashes before/after; unrelated
socket churn is not relabelled as relevant data. It then enumerates **every
visible PID and every FD within the original budgets**, not only SITL or expected
process names. Every PID gets stat/start_ticks checks surrounding the FD walk.
Only owners of relevant inodes get full executable/namespace/permitted-argv
reads; they are rechecked, and a second complete global walk is compared.

An unknown executable can share the inode and remains an owner. Multiple FDs,
processes, duplicate endpoints, wildcard matches and owners in another namespace
remain explicit ambiguity. A process in another namespace can retain an inherited
socket, so it is not skipped. Non-owners need no executable/namespace attribution.
Empty peer matches are not absence of UDP communication. These are repeated
reads, never an atomic snapshot; PID/FD transfer and ABA between reads remain
limits, not grounds to claim authentication.

Disappearing PID/FD entries are classified PROC_ENTRY_DISAPPEARED; EACCES/EPERM
are PERMISSION_DENIED. Both leave the global search incomplete. Successful reads
on other processes cannot turn a partially searched system into a unique-owner
claim. Size fallback now preserves **earlier reasons** and bounded accounting:
wire bytes/sections, read-event count, visible PID count, FD entries/lists completed,
owner rows and relevant socket count. This is the minimum measurement needed if
an actual topology still fails; it does not reconstruct the lost 37 rows.

### Limits and measured regression envelope

- 1,024 `Reader.get` query events total (not a count of every internal kernel
  syscall), 128 visible PIDs, 2,048 FD links per pass; 65,536-byte table reads,
  4,096-byte stat reads and 8,192-byte cmdline/context bounds remain unchanged.
- 250 ms cooperative query time and 750 ms outer child timeout remain unchanged.
  Synthetic clocks exercise width/ordering/budget logic, **not real I/O latency**.
- 131,072 serialized UTF-8 bytes **including the newline** per JSONL row. The
  helper checks packed bytes including bounded accounting before output; the
  monitor checks stdout and persisted bytes again. File bound remains at most
  64 rows (~8 MiB), scheduled every 5 s, within the existing 600-second monitor.
- Native trace retains its independent 512-record/2 MiB bounds. Peer request
  context must fit the existing 8,192-byte stdin bound; no silent truncation.

All figures below are **synthetic stress fixtures**, not observed live topology.
They use realistic-width synthetic reception timestamps and the same fake /proc
for both the frozen algorithm and the new one. Native writer/commit fixture
structure is derived from this session's retained trace, with explicitly replaced
fake process IDs/peer; FD/inode topology is invented for stress and labelled so.

| Fixture | Old maximum wire before fallback | New persisted wire | New result / margin to 131,072 |
|---|---:|---:|---|
| Base, 3 processes | 15,267 B | 11,115 B | Complete candidate; 119,957 B margin |
| 23 processes, 100 unrelated UDP sockets | 161,541 B | 62,057 B | Complete candidate; 69,015 B margin |
| 43 processes, 100 unrelated UDP sockets, 604 FD entries across both walks | 181,380 B; also read-budget failure | 108,295 B | Complete candidate; 22,777 B margin; 908 reads |
| 63 processes and more unrelated FDs | 171,324 B; read-budget failure | 123,561 B | **INCOMPLETE at 1,024 reads** despite fitting bytes |

The tests exercise fake capture → wire → monitor persistence → JSONL reader →
provenance validation → peer candidate, including unknown/shared owners,
foreign namespace, disappearing PID/FD, permission failure, PID reuse, absent
context/ref, truncated output, byte/read budgets and a missing native peer.
The cause-reproducing byte test first failed at a smaller case that still fit;
increasing its *synthetic stress input*, not any operational limit, then
reproduced overflow. Final affected run: **143 passed in 6.49 s**.

A bounded current-background read observed 3 visible PIDs and 23 FD entries,
including the read-only query itself, after simulation shutdown. It is recorded
with source/reception times and is **not a substitute** for the ended simulation's
/proc state. No sockets were queried in that read. Real wall-time cost, total
active FD population/churn and byte composition of the next live topology remain
operational unknowns. No claim of guaranteed live fit is made.

### Prepared next test: precise success and stop criteria

Static reads rechecked the exact active environment and hashes of peer wrapper,
library and collector; all match. Native source/build inputs are unchanged, so
**no native/wrapper rebuild is needed**. Only Python helpers change: selector,
monitor and socket inventory, with the existing analyzer added to deployment.
Use the same `diagnostic-agent.peer.json`; never reuse an old overlay or alter
its descriptor hashes. Missing/altered binaries block; do not rebuild during a
trial. The future start command remains the one already documented above.

The offline correction is prepared with a demonstrated algorithmic cause and
measured envelope. Exact historical pre-fallback composition remains unrecoverable;
the new accounting is explicitly prepared to measure that gap if it recurs.
The next separately authorized single session must start with fresh protected
precheck/identity/artifact checks, preserve trace from launch and wait for confirmed
native peer context. Before Status capture, require valid decoded scoped rows,
completed global ownership sweeps, no budget/context/persistence error, one actual
selected agent/library and actual operator confirmation of the scene. A GUI exit,
UNKNOWN visualization, no usable peer, incomplete search or any exhausted budget
means preserve metrics/logs and protected stop, **no Status collector or retry**.
Do not increase limits or reinterpret missing owners to get a pass.

If those checks pass, one existing 20-sample/120-second/reserve-streams capture
and protected closure follow. Exact MessageInfo GID/RMW → native GUID/conversion
→ writer/commit process/generation/attempt/client/session/object/topic/type/domain
must agree. Its native peer must be included in each row's declared scope and
match a local UDP endpoint, inode and all visible FD/PID/start_ticks owners,
with complete references and consistent before/after reads from that session.
Shared/changed/missing owners cannot establish a unique association. A successful
candidate still does not prove the sender of an individual UDP packet, effective
SYSID, cryptographic identity or bridge/model provenance. Full identity and
movement remain BLOCKED. No future opening is authorized by these preparations.

For Joel in VS Code: follow `SocketRecorder.sample` → existing `analyze` →
`socket_inventory.collect` → `_tables` → `_owners`, then `pack_inventory` /
`unpack_inventory` → `validate_inventory` → `match_peer` / `analyze_series`.
`old_measure`, `stress` and `pipeline` in the existing test file show the frozen
comparison and whole fake chain. All of these changes are opt-in diagnostic
instrumentation or offline analysis; protected lifecycle/flight control and
movement authorization are unchanged. The socket tells us who visibly owns a
relevant network endpoint, not which vehicle identity or SYSID is authenticated.

The final ownership review also retains possible UDP6 wildcard/IPv4-mapped
sockets for an IPv4 peer: /proc alone does not expose IPV6_V6ONLY. They remain
dual-stack candidates/ambiguity and prevent false IPv4 uniqueness. Two offline
regressions cover these cases; no IPv6 socket is excluded merely because the
native UDP4 peer is displayed as IPv4.

Final targeted socket regression run after the dual-stack check: **55 passed in
1.55 s**. The earlier affected combined suites passed **143 in 6.49 s**; these
counts are separate runs, not an additional operational validation.

## Protected scoped trial b9ee: reception, port contract and coverage — 2026-10-24

The [session evidence](../../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f/session_analysis.json)
records one protected opening `51790d37-9fce-489b-9a24-688d3790fff7`, an actual
new Joel confirmation (pista and three complete vehicles), one passive 20/120/
reserve-streams collector and one protected stop. No restart, vehicle service,
readiness/prearm, motion or second opening occurred. Collector rc=0, footer and
receipt valid, 1 Status + 19 odometry samples. Their MessageInfo/graph metadata
are kept separately. Exact Status GID/RMW matched a confirmed native DDS/XRCE
creation; **peer→socket→SITL was not demonstrated**.

All 64 socket rows were structurally complete and within budget: 6,324–6,337
bytes including newline (minimum 124,735-byte margin), 26 reads (998-read margin),
30 total UDP rows and **zero relevant inodes**. Owner walks were skipped because
of that empty selection. This small output does not validate the cost of the
real global FD/owner walk. The largest row's JSON value bytes were record/context
3,099; read events 2,710; sources 276; columns 124; sockets/processes/argv/owners
only 2 bytes each (empty arrays). Framing is included in the persisted total.

### Demonstrated defect and offline correction: raw sin_port

The actually built `UDPv4Agent::recv_message` in `UDPv4AgentLinux.cpp` (preserved copy SHA-256
`0d3d11252c58b65c85762390b5c79f72a2b9f4efdae6547b09da43a611a96217`)
assigns `client_addr.sin_port` directly to IPv4EndPoint. The endpoint getter and
formatter return this native integer unchanged. The earlier statement that the
getter supplies host-order port was wrong. The peer helper faithfully emitted
its raw integer, but Python incorrectly used that as a normalized UDP port.
The observed wrapper ELF EI_DATA is little-endian. Raw **20920** therefore decodes
from the network-order uint16 representation to **47185**, by the pinned source
contract and ELF layout, not by finding a convenient matching number. No socket
or owner at that actual endpoint was retained in this trial, so the correction
cannot retroactively supply an inode, FD or SITL process.

`analyze.normalized_udp_peer` now performs this explicit interpretation only with
the known transport-source hash and an established native ELF byte order.
`monitor.verify_agent` observes the ELF header of the verified wrapper;
`SocketRecorder.sample` normalizes peers before selecting UDP rows, and stores
byte order/contract in the per-row request context. `match_peer` uses that explicit
interpretation too. Missing interpretation is UNKNOWN, not a guessed native/
network swap. Raw trace bytes and historical `analyze()` outputs are not changed.
C++ tests now construct the endpoint from the public `htons` contract, and tests
exercise both ELF byte orders, missing/unknown interpretation and unchanged raw
records. This is a **Python interpretation fix**, not a native code change;
existing native pair/hashes remain valid and no rebuild/deployment occurred here.

### Separate failure: capture began after socket coverage

Socket observations cover **13:12:03.520275–13:17:23.438406 UTC**; the Status
reception was **13:21:43.626511 UTC**. The 64-observation schedule had ended before
that receipt. The monitor's existing 600-second wall budget also expired before
it could observe protected stop; its final receipt is INCOMPLETE, with wall-budget
and unobserved agent/launch-exit errors. Formal lifecycle stop nevertheless was
SUCCESS, post-stop reads had zero owned/ambiguous processes/agents, no guards or
restriction, and the host target CLOSED. These are distinct outcomes; no later
unattributed residual was observed. No monitor time or sampling limit was extended.

The evidence driver rechecked phase/processes before collector submission, but
that did not guarantee remaining diagnostic time through execution/setup and
closure. The offline reader now accepts explicit Status wall reception times
and rejects receptions outside the sampled socket span. These are reception
clocks in the same accredited container, not simulated/source header timestamps.
Being inside a sampled span would still not establish atomic packet attribution.

The pure `monitor.capture_window` helper is prepared for the **future evidence
driver**, inside the container immediately before exec: require current same-boot
OBSERVING receipt, no source error, usable socket coverage, remaining monitor
budget for existing 140-second outer capture plus 60-second protected-stop bound,
and remaining scheduled socket observations for that capture. It does not alter
these limits, implement a flight gate, authorize motion, start anything or retry.
A delayed reply/submission must block and close, never extend budgets.
A future driver must invoke it locally using that fresh session's frozen helper:

```python
# After real visual confirmation and fresh process/ref/hash checks, inside the
# accredited container; prefix is the exact newly recorded lifecycle overlay.
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(prefix))
from monitor import capture_window
receipt = json.loads((prefix / 'capture/monitor.json').read_bytes())
capture_window(receipt, now=time.monotonic(),
               observed_boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
# Only if this succeeds, execute the single already-authorized collector.
```

This is prepared offline, not a second operational test. The current historical
pointer precheck remains BLOCKED on this INCOMPLETE monitor receipt despite
infrastructure CLOSED/no guards. That needs an explicit read-only closure review
under the existing policy before another opening; do not delete metadata or
weaken the policy here. Full identity and movement remain BLOCKED.

VS Code: follow `normalized_udp_peer` for raw/native versus normalized port;
`verify_agent` for ELF provenance; `SocketRecorder.sample` and `_tables/_owners`
for the scoped exhaustive search; `analyze_series(receipt_wall_ns=...)` for time
coverage; `capture_window` for the future evidence driver's bounded eligibility.
These are diagnostic helpers/offline readers. Protected lifecycle, mission gates,
vehicle executors and movement authority are unchanged.

### Offline closure audit of b9ee — 2026-10-24

See the [session closure addendum](../../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f/closure_audit_addendum.md). The unchanged original manifest verifies 152 entries. Monitor final receipt was 13:21:23.313789 UTC, 313.646 s before stop submission; closure_requested=false. Lifecycle SUCCESS certifies its protected infrastructure cleanup, not diagnostic capture completion. The actual monitor wait/exit code was not retained independently. Corrected time coverage would have rejected this reception, not supplied its missing socket evidence. No additional functional correction or timeout change is justified. Keep the historical pointer BLOCKED pending explicit closure-policy review, then require fresh precheck and locally checked remaining capture/stop budgets before a separately authorized trial.

### Historical descriptor blocker: supported scope — 2026-10-24

Local read-only review finds host `missions/generated/diagnostic_agent_session.json`
CLOSED for `51790d37-9fce-489b-9a24-688d3790fff7`, closed by
`391610b1-899f-40e2-9368-28867d05f88f`. The persisted post-pointer classification
in b9ee is BLOCKED / UNKNOWN_OR_CONTRADICTORY, specifically
`Monitor closure absent/incomplete/contradictory`. This is the diagnostic
precheck's derived verdict, not a lifecycle guard state or an identity approval.
`session_precheck.classify_last_session` requires monitor phase CLOSED,
capture_complete=true, closure_requested=true and errors=[] (lines 77–81).
The historical receipt is INCOMPLETE/false/false with three errors; the evidence
cannot satisfy that condition merely by waiting or authorizing another action.
The classifier is pure; the evidence driver invokes it. The lifecycle itself
checks the host target separately and does not invoke this classifier. Do not
bypass the diagnostic precheck by invoking start directly.

No supported transition for THIS completed-launch/monitor-timeout case was found.
`prelaunch_recovery` is pinned to owner 39fb9601 and trial 5d541497, proves failure
BEFORE launch and requires that original UNCONFIRMED guard. It must not be reused
or retargeted here. Flight reconciliation/administrative retirement is not a
mechanism for repairing a monitor receipt. No person or CLI authorization can
make the present classifier return CLEAR while these historical inputs remain
unchanged; it contains no authorization override.

The minimum next work is a separately scoped OFFLINE policy/design review for
representing independently verified infrastructure closure WITH incomplete
historical diagnostics, preserving the original receipt and blocker history.
It is not another stop, receipt edit, descriptor deletion or recovery invocation.
Any future new transition needs explicit Joel approval of its exact scope before
application, audited evidence binding the descriptor, start/stop operations,
backend final ownership checks and independent later reads, with fresh exclusion,
identity/process/reservation revalidation and rejection of contradictions. Those
requirements describe a proposal, not an implemented or currently authorized
recovery command; no fresh operational reads were made in this review.

For a future separately authorized diagnostic trial, the monitor MUST remain
active through protected stop and observe agent/launch exit; lifecycle SUCCESS
alone is insufficient. Status MUST be received inside both active monitor time
and the socket observation span. Immediately before capture, remaining existing
budgets must cover capture and protected stop; budget failure means preserve and
close, never extend or retry. Sampled-span coverage is necessary, not sufficient:
complete owner search, unchanged identities and usable references are also needed.
No future trial is prepared or authorized by this clarification.

### Proposed policy: closed infrastructure / incomplete diagnostics (review pending)

**PROPOSED, NOT IMPLEMENTED, NOT AUTHORIZATION.** Scope is only historical session
51790d37-9fce-489b-9a24-688d3790fff7. No receipt, descriptor, reservation or runtime
state is changed. The previous closure-policy review requirement is concretized
below; this subsection does not supersede the present BLOCKED decision.

Current classifier exposes two outcomes: BLOCKED/UNKNOWN_OR_CONTRADICTORY and
CLEAR/HISTORICAL_CLOSED_POINTER. The latter requires complete monitor closure.
Current tests use immutable eb113 evidence for the successful path, and cover
active/uncertain targets, missing/corrupt records, failed closure, incomplete/error
monitor, different overlay, processes/state files and changed environment/boot/library.
They do not model independent infrastructure closure after monitor timeout.

Minimal proposed third classification:

| Input / condition | Proposed output | Admission consequence |
| --- | --- | --- |
| Existing complete-monitor path passes all existing checks | CLEAR / HISTORICAL_CLOSED_POINTER | Unchanged: only this pointer passes, no authorization |
| Exact reviewed case passes ALL independent closure and timeout checks below | BLOCKED / HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE | Requires separate scope review; never automatic start |
| Any other missing, active, uncertain or contradictory evidence | BLOCKED / UNKNOWN_OR_CONTRADICTORY | Unchanged, no exception |

This is a transition of a DERIVED CLASSIFICATION, not a mutation CLOSED->CLOSED
or INCOMPLETE->CLOSED. Keep target.state=CLOSED, monitor.phase=INCOMPLETE,
capture_complete=false, original errors, and movement/source-association flags
false. Proposed fields infrastructure_closure=VERIFIED_FROM_RECORDS,
diagnostic_capture=INCOMPLETE and requires_explicit_scope_review=true make the
reason visible without overloading CLEAR. Existing drivers that accept only CLEAR
must continue rejecting this new classification. No override token or application
command is proposed as part of the classifier change.

Required original proof for the case-specific branch:
- Verify the original b9ee manifest (152 entries; SHA-256
  047f42f388c7391856ee912906613f7f9db6eb16d6d96429eb18e030ac269e7e), retaining
  originals and binding all compared copies to the reviewed owner/descriptors.
- Exact start FINISHED/start owner 51790d37 and FINISHED/stop owner 391610b1,
  full UUIDs as recorded above, identical diagnostic descriptors, target CLOSED
  by that stop, and accredited environment reference. Short IDs here are prose,
  never matching keys. Preserve all existing overlay/process/library checks;
  do not skip checks that currently occur after the monitor-closure predicate.
- Independent stop backend return 0 and complete structured cleanup report with
  success=true, errors=[], remaining=[], unattributed_auxiliaries=[]; reconcile
  it with operation times and the saved post-stop inventory/host guard reads.
  A FINISHED operation or empty process snapshot alone is insufficient.
- Original monitor has the correct owner/process/boot/library and a structurally
  final INCOMPLETE receipt, capture_complete=false, closure_requested=false and
  exactly the three recorded timeout/unobserved-exit errors. Other errors do not
  qualify. Bind its start/end observations, duration limit and last socket data;
  establish timeout BEFORE stop submission from same-boot monotonic observations
  and corroborating wall reception records. Do not compare simulated timestamps
  to wall time. This case lacks an independently waited monitor exit code: do
  not invent one or require its retrospective recovery. The durable final receipt
  plus subsequent independent cleanup evidence is the proposed substitute for
  classification only, not proof of complete monitor capture.
- Keep 64 socket inventories, 20 collector samples and time-coverage failure as
  diagnostic results. They are not evidence of a successful peer->SITL join.

Before ANY subsequent opening, still require fresh read-only observations under
existing admission/registry exclusion: current engine/container/image and
incarnation agree with the reference; complete process inventory has no owned,
ambiguous or relevant agent/worker processes; no active/uncertain reservation,
lifecycle/reconciliation/applying marker or unrelated session; pointer, target,
operations and reviewed artifacts have not changed. Read failures, unknowns and
changed context block. Recheck versions/hashes at the eventual protected admission
without a check/reserve gap. Today's documentation review performs none of those
operational reads and grants no stale eligibility.

Authority boundary: Joel may explicitly approve a separately reviewed policy
implementation, then a specific later diagnostic opening based on fresh evidence.
An agent must not reconstruct that permission from a previous trial authorization.
There is currently no supported administrative transition for this case. This
proposal intentionally leaves the third outcome BLOCKED: making it admissible
would require a separately reviewed consumer/authorization design, not silently
changing the existing driver's `status == CLEAR` check. Do not reuse prelaunch
recovery or introduce generic unlock. No runtime mutation is needed merely to
classify the historical evidence more accurately.

Planned regressions (not implemented/run here):
1. b9ee immutable fixture + complete independent stop proof -> proposed third
   classification, still BLOCKED, original inputs byte-for-byte unchanged.
2. Original eb113 success -> unchanged CLEAR/HISTORICAL_CLOSED_POINTER.
3. All current negative tests remain BLOCKED; incomplete monitor alone without
   the pinned independent proof remains UNKNOWN_OR_CONTRADICTORY.
4. Missing/failed cleanup, nonempty/ambiguous owners, mismatched closing owner,
   target not CLOSED, mixed-session records, modified manifest/helper/library,
   unknown/changed boot/incarnation and extra reservations never qualify.
5. Missing final monitor, extra errors, nonfinite/reversed chronology or stop
   before timeout do not qualify for this narrowly defined timeout branch.
6. Repeated pure classification is deterministic, has no writes and cannot change
   capture_complete; an existing CLEAR-only consumer rejects the third outcome.
7. Changes between reviewed historical proof and fresh admission block; tests
   must distinguish historical classification from current opening eligibility.

Risks: a permissive consumer could treat a descriptive closed classification as
permission; prevent this with BLOCKED plus a consumer regression. Missing monitor
exit observations can conceal a tail gap: retain that uncertainty rather than
claim full capture. A historical empty inventory can be stale, so require fresh
checks. Case-pinning avoids accidental generalization to an unrelated failure;
future cases need separate review. The monitoring deadline and sample coverage
remain unchanged: Status inside the sampled span and monitor active until it
observes protected stop are requirements of a future separately authorized trial.

### Offline implementation of descriptive classification — 2026-10-24

The preceding policy is now implemented ONLY for descriptive classification in
`session_precheck.classify_last_session(historical_evidence=...)`. The recovery
and admission policy remain PROPOSED/NOT IMPLEMENTED. Existing callers without
historical_evidence retain their prior fail-closed behavior. No caller is changed
to admit this outcome and no real descriptor is rewritten.

`_timeout_closure_proof` reads the pinned original 152-entry manifest and verifies
ALL listed sizes/hashes, rejects missing/altered originals and unsafe paths, binds
the supplied target/start/stop/reference/selection/launch/monitor to those exact
originals, and checks independent cleanup/return and timeout-before-stop order.
Common context/process/library checks still run after the exceptional monitor
branch. Environment/process inputs must be freshly collected by a real caller;
fixture inputs do not become current observations. Both original flags remain
false, output status remains BLOCKED, and requires_explicit_scope_review=true.
The original manifest and historical classifications remain byte-for-byte intact.

Recorded-fixture result (not a new operational inspection): before, without proof,
BLOCKED/UNKNOWN_OR_CONTRADICTORY; with the pinned proof,
BLOCKED/HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE. Traditional complete
closure remains CLEAR/HISTORICAL_CLOSED_POINTER. Missing/changed proof, contradictory
owners/environment/monitor, ambiguous processes and extra state files remain
BLOCKED/UNKNOWN_OR_CONTRADICTORY. Repeated calls do not mutate inputs or create files.

Verification: 151 affected tests passed in 6.33 s across session precheck, socket
inventory, XRCE peer and diagnostic selection. The latter suites cover actual
network-order normalization contract, scoped endpoint search, all visible owners,
shared sockets, read/FD disappearance and errors, dual-stack ambiguity, missing
references, truncated/budgeted wire records, Status outside the reception span,
and insufficient/stale monitor/sampling budgets. No new version of those helpers
was needed; these offline guarantees do not measure real owner-search load.

### Proposed supported disposition (NOT implemented; explicit review required)

Existing prelaunch recovery and flight/administrative retirement cannot legitimately
handle this completed-launch case. Reuse only their mechanisms: exclusion registry,
atomic JSON, durable originals/audit and exact reviewed-scope authorization, never
their case-specific permissions. Proposed minimum is a separate historical
DISPOSITION RECORD, not rewriting or deleting the old pointer or monitor receipt.

Input: the new BLOCKED descriptive class for the pinned b9ee owner. Proposed
records: REVIEWED (historical hashes and exact proposed scope), PREPARED (fresh
identity/owner/version digest, finite validity), APPLYING, DISPOSED_DIAGNOSTICALLY_INCOMPLETE
or APPLYING_UNCONFIRMED. Original target remains CLOSED and monitor INCOMPLETE.
Output would acknowledge that this pointer alone no longer prevents a later
separately authorized diagnostic trial; it would not mark capture complete,
verify identity, unlock a reservation or start anything. Supporting that output
would require a separately reviewed classifier/consumer branch; none exists now.

Preparation must inspect the full historical proof and current state under the
existing admission/registry exclusion: exact engine/container/image/incarnation,
container boot and all relevant host/container process identities (PID/start_ticks,
boot, executable and permitted context), no workers/agents/launch/monitor or
ambiguous owners, exact pointer/target/operations/overlay hashes, and absence of
active/UNCONFIRMED/APPLYING reservations or unrelated sessions. Inaccessible reads
and changed identity block. Capture a canonical scope digest including original
hashes and versions, proposed transition, expiry, current observations and limitations.
The historical record must never be treated as fresh process evidence.

A local operator action outside model-generated MCP text must explicitly consume
`AUTHORIZE_DIAGNOSTIC_DISPOSITION <owner> <preparation_id> <sha256>` for exactly that
scope and its diagnostic uncertainty. This literal is a proposed contract, NOT an
available command or proof of human authentication. The project currently cannot
authenticate humanity from model text; no MCP apply path should be added on that
basis. Joel must review the local execution boundary before implementation.
No substitution of preparation IDs or automatic renewal after timeout/boot change.

Before committing a disposition, reacquire exclusion and revalidate every owner,
version, process and environment observation, archive original bytes durably with
hashes, write/fsync intent and single-use authorization claim, then atomically
commit the new disposition audit and fsync its parent directory. It must contain
original manifest/descriptor/monitor/stop hashes, explicit incomplete outcome,
reason, authorization reference and before/after semantics. No guard is removed.
If persistence fails, preserve APPLYING_UNCONFIRMED and block admission; interrupted
intent requires explicit read-only inspection and separately authorized completion,
not replay of runtime actions. Repeating a committed same-scope request returns
its audit without new writes. Lost response requires query only; conflicting
scope, fresh preparation or changed originals rejects. Implement tests for every
persistence boundary before permitting this transition. There is no dry-run/apply
CLI in this increment: the only executable new path is read-only classification.

### Rover objective after a socket join

A complete scoped endpoint/inode/FD/PID-start_ticks observation would link the
Status-producing XRCE client to a particular SITL process, not prove effective
SYSID from argv. The next missing fact is effective DDS/SYSID configuration tied
to that process/session through an already available public read interface or
preserved effective-parameter source; do not invent a service. The independent
odometry branch still needs publisher sample attribution to the actual bridge
binary/config hash and Gazebo rover model, frames and units. A second native
trace framework is not justified.

Existing control path: `rover_ground_executor.admit_ground_trial` snapshots,
validates and reserves; `run_ground_worker` owns worker/results and conservative
uncertainty; both remain disabled by OPERATIONAL_ROVER_ENABLED. `RoverControlCore`
implements bounded terrestrial operations, while `Ros2RoverAdapter.probe/observe`
require explicit transport types, v3 authority, fresh typed observations and
accredited `MotionBinding`; `RoverEnvironmentGuard` rejects identity inconsistency.
The Python NativeRos2Session still lacks per-sample attributed GID in its present
callback contract. The passive C++ observer is not wired into it. Filling a
MotionBinding with plausible strings does not accredit these missing associations.

Real blockers, not extra instrumentation wishes: (1) scoped socket-owner join
not yet observed; (2) effective SYSID/session association; (3) independent bridge/
model/odometry binding; (4) production binding/read path satisfying the existing
adapter and stop-observation contract; (5) separately reviewed operational policy
and explicit finite trial authorization. These gates prevent sending to a merely
similarly named vehicle. Public rover motion/MCP remains disabled.

Only after those blockers are resolved should a distinct minimal movement trial
be reviewed: one explicitly selected rover_01/v3, current global+vehicle reservation,
finite low-speed/time/distance bounds chosen explicitly by Joel, fresh independent
velocity/pose observation before control and after bounded stop, persisted attempts/
replies/observed movement, and UNCONFIRMED retained if stop cannot be confirmed.
No numeric defaults or consent are supplied here. This increment neither prepares
nor executes that trial. In VS Code follow `_timeout_closure_proof` then
`classify_last_session`; for diagnostics follow `normalized_udp_peer`,
`SocketRecorder.sample`, `_owners`, `analyze_series` and `capture_window`; for the
separate disabled control path follow the executor, adapter and environment guard.

### Disposition durability prototype and archived dry-run — 2026-10-24

Implemented `historical_disposition.py`: pure `dry_run`, read-only `query` and an
explicit `OfflineDisposition.apply` durable protocol restricted to a /tmp sandbox.
This is NOT a production apply command. The existing runtime descriptor, monitor
receipt and precheck are unchanged. There is no CLI apply and no MCP exposure.
The scope restriction is deliberate: no reviewed live reader/operator-authentication
boundary for disposition exists yet; arbitrary JSON cannot establish current truth.

A real-records, process-free dry-run is available and was executed once:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition dry-run --evidence simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f/
```

It reads originals only and prints to stdout. It creates no directories, leases,
preparations or runtime state. Result: BLOCKED; historical_proof=true; current
freshness, completeness, restrictions, guards, other sessions, host processes and
host boot UNKNOWN. The archived classification uses an explicitly labeled
historical proof scenario, never live eligibility. Scope hash for that incomplete
assessment is 1305807bbb3b3b03488e917852531d4b605ac5c0e15fde15cd98aaf5f8a76417;
it is NOT a preparation or a value that can authorize real application. The full
stdout from this review is temporary at /tmp/rover-disposition-dry-run.json.

Sandbox flow (API, not an operational command):
`assessment = dry_run(records, current, now=clock())`, inspect conditions and exact
scope, then `OfflineDisposition(new_tmp_directory).apply(records, reader,
scope_sha256=assessment['scope_sha256'], authorization='AUTHORIZE_DIAGNOSTIC_DISPOSITION '
+ owner + ' ' + assessment['scope_sha256'])`. Test readers supply deterministic
observations; production cannot use them. The authorization names the exact owner
and canonical scope (which includes full descriptor, stop operation, monitor and
current identity); this literal validates scope only, NOT human authentication.

The prototype locks sandbox v1.execution.lock then registry.lock in the same order
as protected lifecycle, reads twice under exclusion and rejects changed or stale
scope, unknown observations, nonempty guards/processes or other sessions. Sandbox
locks do NOT coordinate with real lifecycle locks. Records remain unchanged and
classification stays BLOCKED. Scope includes the pinned historical manifest hash;
all original evidence is revalidated by the classifier on each first application.
A fresh real reader would also need exact relevant host process identities,
complete container process attribution, artifact/session context, reservations,
restrictions and environment incarnation observations under actual shared locks.
These operational integrations are intentionally pending, not simulated as safe.

Durability: exclusive 0600 intent + fsync before archival; archive of the canonical
input scope (descriptor/receipts/closure records and historical manifest link), then
atomic fsynced final record. Query distinguishes NOT_ATTEMPTED, uncertain intent
and DISPOSED_DIAGNOSTICALLY_INCOMPLETE. Original raw evidence stays at its pinned
paths, unaltered; archive is a parsed input snapshot, not a claim of byte-exact raw
copy. No guard or pointer is deleted. Errors/interruption leave durable intent;
a best-effort independent persistence_failed marker prevents a final replacement
followed by reported persistence failure from being treated as clean completion.
If storage is so broken that even that marker cannot persist, no durable software
protocol can guarantee a recorded failure; callers must retain uncertainty and
must not reopen from a successful-looking file alone. Production must resolve
that boundary before implementation.

Repeated completed same-scope application is read-only and never reconsults a
reader or repeats an action (lost response -> query). It is NOT a current eligibility
result. Other scope, damaged archive or interrupted intent blocks; no auto-resume,
renewal, cleanup or retry. Partial files are retained. Scope changes between the
two fresh reads block before intent creation. External clients not using project
locks remain outside this protocol's coordination boundary.

Future consumption is NOT implemented: a precheck would need a separately reviewed
branch validating a durable disposition's full scope/owner/original hashes AND all
fresh current checks under actual exclusion. It would report historical closure
with diagnostics still INCOMPLETE, never identity/motion approval. No existing
CLEAR-only consumer accepts the prototype audit. Consequently no exact real apply
call can honestly be offered yet: the blocked part is production reader, actual
lock binding and reviewed local operator boundary, not a missing permission string.
Review those pieces explicitly before exposing any production apply API. The next
step is that narrow offline integration review, not an opening or runtime recovery.

Tests run the complete classification -> dry-run -> exact-scope sandbox application
-> query -> repeat path on immutable b9ee fixtures. Negatives cover wrong scope,
unknown/stale observations, descriptor change, processes/guards, two-read races,
competing lock, interruption, both archive/final write failure boundaries including
failure after replace, changed archive and conflicting prior disposition. No ROS,
Docker or runtime reads occur. Follow `dry_run`, `OfflineDisposition.apply/query`
and `_timeout_closure_proof` in VS Code; the only new CLI action is offline dry-run.

### Project integration and current dry-run — 2026-10-24

This subsection supersedes only the earlier statement that there is no project
reader/apply entry point. `current_records`, `real_dry_run` and
`ProjectDisposition.apply_reviewed` now implement that integration. No disposition
has been applied in this work; original descriptor/monitor/precheck remain unchanged.

Interfaces reused:
- `reconciliation_environment.inspect_environment`: bounded Docker metadata reads,
  exact engine/container/image/incarnation, explicit DOCKER_UNAVAILABLE versus
  STOPPED/ACTIVE/absent states. An inactive/unknown environment prevents container
  inventory. Identity mismatch prevents entry into a replacement container.
- New public `sim_processes.readonly_inventory`: calls existing snapshot,
  remembered_identities, select_owned and unattributed_auxiliaries, the same
  attribution used by protected stop. It returns known project processes, ambiguous
  auxiliaries, agents, state files and explicitly requested overlay JSON records.
  It neither signals nor deletes files. Permission/read/JSON errors propagate.
  Repository source definitions are supplied to a short-lived metadata-only Python
  process in the exact running container via the existing inventory approach; no
  installed helpers are overwritten, no ROS nodes/services are started. Shared
  ownership rules are provenance, not an assertion of cryptographic accreditation.
- Host relevant-role inventory records process_identity; same module/role matching
  approach as existing diagnostic/prelaunch inspection. It is metadata-only and
  cannot protect against external uncoordinated/manual ROS clients or all possible
  renamed processes. Container attribution inherits the lifecycle snapshot's
  treatment of disappearing processes; two application reads catch observed changes,
  not an atomic kernel-wide snapshot or proof that no transient process ever existed.
- `vehicle_execution_lock.restriction`, all vehicle_locks JSON files, current
  diagnostic target, start/stop operations and original environment reference.
- `v1.execution.lock` THEN `registry.lock`, nonblocking, same order as lifecycle.
  Dry-run opens existing lock files without creating them; application uses the
  same actual shared files via file_mutex. ExitStack releases on every path.
  A lock/read failure is BLOCKED, never an empty inventory.

The current reader binds the retained selection/launch/monitor and target to the
pinned originals. It does not rehash every retained overlay executable: original
binary/helper identity is bound by the historical manifest/descriptor and receipt.
This is enough for disposition of a CLOSED session, not launch provenance. Every
future opening must independently validate its newly selected actual artifacts.
Read timestamps and environment query metadata are reported as provenance but
excluded from the stable scope digest; original records/current identity/guards,
processes and boot remain bound. Freshness (3 s) is checked independently at each
use. No timeout was increased.

Current dry-run command (not apply):

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition dry-run-current
```

One sandbox attempt failed accessing Docker socket (permission denied, not proof
of container shutdown). The platform-required retry outside the sandbox was
explicitly approved and completed one actual current inspection at
16:22:57–16:22:59 UTC (18:22:57–18:22:59 Europe/Madrid). No state was changed to
obtain this result. Saved outputs, including the failure, are in
`simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_24/disposition_integration_20261024/`.

| Condition | Source and observed result |
| --- | --- |
| Historical closure proof | Pinned 152-entry manifest + matching live local records; valid |
| Freshness | monotonic reader interval, <=3 s; passed |
| Environment | inspect_environment; ACTIVE, expected engine/container/image/incarnation |
| Container ownership/session | readonly_inventory; owned=[], ambiguous=[], agents=[]; only historical pointer |
| Host workers | host /proc role inventory; none observed, host boot known |
| Reservations/restrictions | vehicle_locks JSON enumeration + restriction(); empty/None |
| Target/operations/monitor | original-matching CLOSED target, FINISHED stop, INCOMPLETE monitor preserved |

Result DRY_RUN_ELIGIBLE is eligibility for this separate audit operation at those
observations only. Base classification remains BLOCKED with incomplete diagnostics.
It is not a preparation, authenticated human consent, a current-state promise,
movement authorization or permission to open another session.
Scope SHA-256: de67fb09603f1df8fb72c9e9bbba1f9d43f184dbe1af1f66dd16b547ee1b3ee8.

The exact FUTURE call requiring Joel's separate authorization is:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition apply-reviewed --scope-sha256 de67fb09603f1df8fb72c9e9bbba1f9d43f184dbe1af1f66dd16b547ee1b3ee8 --authorization 'AUTHORIZE_DIAGNOSTIC_DISPOSITION 51790d37-9fce-489b-9a24-688d3790fff7 de67fb09603f1df8fb72c9e9bbba1f9d43f184dbe1af1f66dd16b547ee1b3ee8'
```

NOT executed here. It records a scope declaration, not authenticated identity.
It re-reads the actual project records and current environment twice under shared
exclusion, rejects any differing/unknown/stale scope, then writes only
`missions/generated/historical_dispositions/51790d37-9fce-489b-9a24-688d3790fff7/`:
exclusive intent, canonical input snapshot, completed audit or failure marker.
It never edits descriptor, monitor, lifecycle operation, guards or reserves. Query
of an already completed exact scope is idempotent and does not imply current
eligibility; lost response requires query, not another scope or renewal. Partial
persistence/interruption leaves uncertainty, with no automatic completion.
The command may reject later changed conditions; do not substitute a new digest
under the old authorization. A new scope needs explicit new authorization.

Future precheck consumption: `assess_disposition(records,current,audit)` validates
query output, exact scope/owner/declaration and NEW fresh current checks. It reports
historical_pointer_resolved=true only for a matching committed audit and otherwise
false, always opening_authorized=false, movement_authorized=false and base status
BLOCKED. It never changes the monitor outcome. No current driver was silently
changed to accept a new state: a future authorized evidence driver must explicitly
consume this result, keep every existing admission check and obtain independent
opening authorization. The archived trial driver is evidence and must not be edited.
No generic CLEAR override or reservation unlocking was introduced.

Verification uses temporary project roots/shared lock paths and false readers:
full project apply/query, two-read changes, existing-lock concurrency, Docker-query
failure distinct from STOPPED, persistence failures/interruption and repeated calls.
The metadata-only supervisor function is tested against ownership outputs and
permission failure. Current source observation is operational read evidence, not
validation of all live race/failure cases. No production apply was tested or run.

Actual test results for this integration: 113 passed in 72.95 s (disposition,
session precheck, simulation profile suites); after added query/consumption
regressions, 56 passed in 5.92 s (disposition + session precheck); final new
public-reader regression: 23 disposition tests passed in 5.45 s. These are
separate runs, not additive counts or production-apply validation. Python syntax,
explicit new-file whitespace and git diff --check passed; original 152 evidence
entries were reverified unchanged. No full suite or operational start was run.

### Reviewed disposition applied and consumed — 2026-10-24

One explicitly authorized `apply-reviewed` was executed for owner
51790d37-9fce-489b-9a24-688d3790fff7 and scope
`de67fb09603f1df8fb72c9e9bbba1f9d43f184dbe1af1f66dd16b547ee1b3ee8`.
Return code 0; recorded interval 16:50:13.889626–16:50:16.466301 UTC
(18:50:13–18:50:16 Europe/Madrid). No replacement digest, second apply, simulated
operation or vehicle command occurred. Read-only query confirmed
DISPOSED_DIAGNOSTICALLY_INCOMPLETE. Descriptor hash, guard-file list and all original
152 manifest entries remain unchanged; monitor INCOMPLETE/capture_complete=false.

Audit: `missions/generated/historical_dispositions/51790d37-9fce-489b-9a24-688d3790fff7/`.
Application command/output, exact application sources, audit copies, unchanged-state
checks and the new precheck observation are preserved under
`simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_24/disposition_application_20261024/`.
The user declaration is recorded scope consent, not cryptographic authentication.

The new explicit diagnostic precheck is available for a current READ-ONLY review:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition diagnostic-precheck
```

It was run once after integration, 16:55:29–16:55:30 UTC. Result SATISFIED,
disposition_consumed=true, all current conditions true; historical classification
still BLOCKED/HISTORICAL_INFRASTRUCTURE_CLOSED_DIAGNOSTICS_INCOMPLETE. No identity
or movement approval: opening_authorized=false and movement_authorized=false.
This is an observation, not a reusable admission token; inspect the JSON decision,
not just the CLI exit code. The command never starts or reserves anything.

**The integration is now usable, not merely a standalone helper:**
`simulation_lifecycle.run_lifecycle` invokes `diagnostic_precheck_locked` for
start/restart with a retained diagnostic target, while already holding execution
then registry locks, BEFORE creating a lease or invoking either restart step.
The current reader now resolves owner-specific retained operations/reference so
ordinary fully CLOSED monitor sessions remain supported. `diagnostic_precheck`
accepts either that unchanged complete-history path or ONLY the reviewed committed
production disposition for the exact scope above, with fresh matching current
checks. Output is diagnostic SATISFIED, never global CLEAR; the original classifier
and monitor are unchanged. Stop remains available through its existing protected
path. Active/uncertain/malformed sessions, wrong audit/scope, missing records,
changed identity/guards/processes and stale observations block without backend
side effects. The consumer never reacquires locks already held by lifecycle.

Reviewed consumers: simulation_control wrappers, MCP start/restart wrappers and
shell start/restart entry points already route through run_lifecycle; backend
scripts require its inherited verified lease. Direct run_lifecycle calls therefore
receive the same check, including default-agent start/restart, rather than a
manifest-only bypass. The archived evidence drivers are immutable records and
still show their old direct classifier calls; DO NOT rerun them as a future driver
or edit them to erase the original failure. No vehicle executor gate changed.
Clients outside project coordination remain outside these guarantees.

Offline verification: 134 tests passed in 11.16 s across disposition, session
precheck, lifecycle exclusion and diagnostic selection; one subsequently added
complete-history compatibility regression passed in 0.09 s. Tests replay the
actual scope/audit as clearly labeled fixtures, preserve all input records, reject
invalid/offline/wrong-scope audits, changed/stale/active contexts, and verify both
locks are held before precheck with no lease/backend work on rejection. Start and
restart consumption use fake backends only. Syntax and whitespace were checked;
these results do not validate another simulation run.

### Exact next-session procedure — PREPARED, NOT AUTHORIZED OR EXECUTED

Three separate facts: **history disposed** is durable; **diagnostic precheck
satisfied** was true at the saved read; **another trial authorized** is FALSE.
A future single opening/passive reception/protected stop requires separate Joel
permission and a new private evidence directory/new UUID. No old trial driver,
prefix, visual reply or collector output directory may be reused.

1. Run the diagnostic-precheck command above into the NEW evidence directory,
   requiring SATISFIED and opening_authorized=false. Preserve current environment,
   guard/process/source observations. Then obtain the separate exact trial consent.
   Lifecycle repeats the checks atomically at the actual admission; a previous
   standalone pass cannot replace that. Changed/unknown context means stop here.
2. Verify the actual artifacts in the accredited, already-running container using
   the existing selector hash/ELF checks; absence/difference blocks, no rebuild or
   substitution during a trial. Expected peer manifest SHA-256:
   `7943cf7c9541b06c6e05cf02f514bc61c1f2bc668593ae1bc203b65a18c3ad7c`.
   Wrapper `2c81395a0aaf5aaac094e302c69edbe357975f200947578e9b4ca7eaf17a63a8`;
   library `cf2537265cb64b9ea0f52737306be6166e0a4456a4a2c94b21319b2298a097fa`;
   collector `/tmp/tfg-rover-quota-cap-link-fefyp58g/build/rover_passive_collector`,
   SHA-256 `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93`.
   These are expected identities, NOT a fresh availability check performed here.
3. After separate permission, the sole protected opening command is:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.peer.json
```

Require actual SUCCESS, preserve returned lifecycle owner/prefix and logs, verify
one agent, its exact mapped native library, its monitor and GUI observations.
The lifecycle deploys current helpers through selection.deployment, not manual
replacement or a second agent. Current helper SHA-256 values:

| Helper | SHA-256 |
| --- | --- |
| selection.py | 8e909d1923a4054dadba20b855763eda33589ca446168a28f2941f99fa2f60f7 |
| monitor.py | 7a39be22486744fddcd905a705585522956d8fabc1ce15c70a68546a0c248be5 |
| socket_inventory.py | eb8b70d6cefe766a492f6cb2ebfb36b14bc1b48e0692f28e2da06c9771367493 |
| analyze.py | a627814f09a645495775cbbea2c78a27e1108ba5f74ec09c74f6391110f584ff |

4. Obtain and WAIT for Joel's actual new reply: pista, two drones and rover
   complete. If GUI/agent/monitor is absent, exits, is ambiguous, or receipt/peer/
   socket coverage is incomplete, skip collector, preserve data and protected stop.
   Do not wait indefinitely for a reply or peer beyond existing budgets, restart,
   increase limits or treat backend SUCCESS as visible rendering.
5. For exactly one future reception, use the existing accredited container/ROS
   context and freshly returned prefix. Immediately before executing the collector,
   call the frozen overlay's capture_window LOCALLY with current monotonic time,
   fresh monitor receipt and current container boot, AFTER setup, artifact/process
   checks and the new visual answer. It must leave >=140 s outer-capture +60 s
   stop budget in the 600 s monitor budget AND >=140 s in the 64x5 s socket
   schedule. Both deadlines matter. Any delay requires a fresh local check, never
   extended budgets. Confirm native Status peer/creation and complete scoped
   socket sweeps, not only phase=OBSERVING. Use normalized_udp_peer with the pinned
   transport source/ELF contract: do NOT reuse raw 20920 or normalized 47185 as
   the next session's port; new peer endpoints are observations, not constants.

The exact collector invocation INSIDE that existing accredited context, only after
those checks and in a NEW 0700 directory, remains:

```bash
/tmp/tfg-rover-quota-cap-link-fefyp58g/build/rover_passive_collector --output "$NEW_PRIVATE_CAPTURE_DIR/journal.jsonl" --max-samples 20 --duration-s 120 --reserve-streams
```

The authorized evidence driver must capture stdout as receipt.json, stderr and
return_code.txt for THIS invocation; bound its outer call to existing 140 s and
never repeat it on timeout/lost response/incomplete streams. The existing local
Python API is `subprocess.run(argv, stdout=receipt, stderr=errors, timeout=140,
check=False)` with exclusively created files, followed by the saved real rc.
Do not execute the historical collector_command.sh, whose prefix/output UUID and
pre-budget-check logic belong to the failed historical trial.

6. After that single invocation, immediately use protected stop (also when capture
   fails); do not insert another human confirmation before closing:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones_rover
```

Verify THIS session's attribution before calling. If restrictions/ownership are
uncertain, retain them and report BLOCKED; never force manual cleanup. Preserve
formal stop result and current post-stop process/guard observations independently
of monitor receipt. For complete diagnostics the monitor must observe requested
closure and agent/launch exit, finishing CLOSED/capture_complete=true without
errors; lifecycle SUCCESS cannot supply that evidence. Existing monitor signal
drain bounds also remain unchanged; if they expire, preserve INCOMPLETE.

7. Analyze the same-session journal/receipt/rc and native trace/socket series.
Require exact Status GID/RMW/native writer/generation/client/session/object and
creation confirmation; normalize the contextual peer, demand complete references,
all visible owners and consistent inode/FD/PID-start_ticks observations. Feed the
actual Status wall reception times to analyze_series(receipt_wall_ns=...). Status
must fall inside monitor lifetime AND socket span; source/simulation timestamps
cannot establish that. Shared/changed/missing owners or out-of-span reception are
ambiguous, not identity. Preserve sample coverage separately from monitor closure,
then manifest raw bytes. No SYSID, ground contact, full identity or movement is
inferred; those remain BLOCKED.

### Single authorized trial 8076 — supervision blocked, no reception — 2026-10-24

Evidence: `simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/8076e735-81bb-4542-afda-8db2fe54acef/`.
Lifecycle owner `e2381f94-12bb-4826-8e5c-07bfed20b6f1`; protected stop owner
`9765f88a-d86c-42ef-850b-8ffa9e69e56b`. Exactly one protected GUI opening and
one protected stop, no collector invocation, no restart, readiness/prearm or
vehicle services/controls. Runtime code/helpers/parameters/graphics were not edited.
The new evidence driver and receive/stop commands were prepared BEFORE opening.
It used the integrated current precheck under existing locks; exact peer manifest,
wrapper, library and collector hashes/ELF checks passed. Historical SATISFIED was
not reused. Snapshotted executed sources and command/stdout/stderr receipts identify
what actually ran; the historical trial drivers were neither changed nor rerun.

Timeline (UTC; add two hours for Europe/Madrid): lifecycle start command
17:09:50.776570; formal start SUCCESS returned about 17:10:41.666394. Opening
supervision was queried immediately, 17:10:41.668208–17:10:41.972714, and rejected
an incomplete socket search. The protected stop was requested at 17:10:41.988683,
returned SUCCESS at 17:11:01.987460. No visual question or collector followed the
failed prerequisite. There is NO Joel visual confirmation for this trial.

Independently, the monitor/launch log had already observed GUI `gz sim-2`, PID
20991, EXITED/139 (receipt wall time 17:10:05.956477 UTC). Launch log records repeated
`Unable to create the rendering window`, OGRE RenderingAPIException `Out of GPU
memory or driver refused`, glGetError 1285 and segmentation fault. This proves a
rendering-window creation failure and process exit, NOT a proven VRAM shortage,
rover-induced failure, permanent graphics cause or relationship to socket limits.
Backend/agent remained available until protected stop. Backend SUCCESS was not
interpreted as an image. The supervision driver's first failing assertion was the
socket inventory; GUI EXITED is an independent finding in its saved monitor data.

All three persisted socket rows were analyzed, without selecting a favorable row:

| Row | Wire bytes including newline | Read events | Outcome |
| --- | ---: | ---: | --- |
| 1 | 123565 | 1024 | INCOMPLETE / READ_OR_WALL_BUDGET |
| 2 | 3144 | 8 | INCOMPLETE / ENOENT at agent /proc/20999/stat |
| 3 | 2651 | 4 | INCOMPLETE / ENOENT at launch /proc/20962/stat |

No row exceeded 131072 bytes; largest serialized margin 7507 bytes. Row 1 reached
the 1024-read cap (zero remaining reads). Its retained read events span about
0.053786 s against the unchanged 0.25 s query budget; the common error label is
READ_OR_WALL_BUDGET, but the saturated event count supports read-budget exhaustion.
The precise next refused read is not retained as a separate event. First global
owner walk starts at read 13, the second at 592; the retained walk segments contain
579 and 432 read events. Search counters: 24 visible PIDs, 41 completed FD listings,
899 FD entries listed. This is actual runtime metadata, not a synthetic topology.
It shows that bounded serialized output does NOT mean the two global FD sweeps
fit the read cap. Largest serialized value sections: reads 109091 bytes, sources
10896, record/context 2042; framing/other fields account for the remainder.
Rows 2 and 3 occurred at 17:10:44 and 17:10:49, AFTER protected stop was requested;
keep these closure-time disappearances separate from the first pre-stop failure.
ENOENT was not treated as proof of no owner and no association was credited.

The normalized peer now selected a real socket: raw native uint16 16621 -> UDP
127.0.0.1:60736 by pinned transport source + ELF little endian. First table had
30 total UDP rows, one selected inode 19244352. A before-sweep owner was retained:
FD 16, PID 21027, start_ticks 17794017, executable
`/root/ardu_ws/install/ardupilot_sitl/bin/ardurover`, with explicit boot/network/PID
namespace provenance. No after-sweep owner could be confirmed; associations=[] and
all-series result UNCERTAIN_OR_INCOMPLETE. This is a partial observation, NOT a
unique peer->SITL join. argv `--sysid 3` remains declared configuration only.

Native trace: 84 records, 53458 bytes, 42 valid writer/commit correlations. The
Status writer has agent PID 20999/start_ticks 17794015, client_instance 1,
attempt 15, ClientKey 2902458371, session 129, writer object 14,
`rt/ap/v3/status`, `ardupilot_msgs::msg::dds_::Status_`, domain 0. Generation-bound
writer->XRCE->peer was recorded. No received Status MessageInfo exists: Status
samples=0 and odometry samples=0 because collector was NOT STARTED, not because
an executed receiver failed to obtain streams. No coverage-vs-Status test is
possible; native writer GID does not substitute for a received message GID.

Closure outcomes are separate: formal lifecycle SUCCESS; target CLOSED; post-stop
owned=[], ambiguous=[], agents=[]; guard files empty and restriction=None. The
last-session pointer is retained historical metadata. Additional bounded host
role reads found no relevant process or permission-unknown entry. Monitor receipt
CLOSED/capture_complete=true, closure_requested=true, errors=[] after approximately
52.694 s. This certifies log-drain closure; socket summary still has three
incomplete snapshots. Monitor process exit code is NOT independently provided by
the existing supervisor (not inferred from its Python return path). No tail
completion or successful full chain is invented from lifecycle SUCCESS.

Next minimal work is OFFLINE review of the measured two-pass read cost without
hiding owners, and separate review of the retained GUI rendering failure. No
limit was increased, no new build/instrumentation/control was implemented and no
second trial is authorized. Full rover identity and movement remain BLOCKED.

### Offline cost correction after 8076 — 2026-10-24

No new opening, Docker/ROS query, receiver, agent or vehicle operation was run.
The 88 manifested 8076 originals remain intact. Machine-readable measurements,
source references and the offline measurement recipe are in
`simulation/ros2_gazebo/results/rover_socket_offline_2026_10_24/8076_cost_review/`.
Graphic findings and ONE proposed graphics-only control are in
[the existing GUI guide](../../docs/gazebo-black-gui-diagnostic.md#revisión-offline-de-8076-y-contraste-con-h2--2026-10-24).
No graphics correction is claimed without operational proof.

#### What actually consumed the read cap

Counts below are `Reader.get` events, not all kernel syscalls: open/read/close and
scandir internals can use several syscalls per event. Own-query directory-FD
identification also does internal readlinks; these do not become extra counted
get events. Do not use these counts as CPU/RTF measurements.

| Retained phase | Events | Breakdown |
| --- | ---: | --- |
| Context then UDP tables | 13 | context 11 (boot/self namespaces and anchor/agent identity), tables 2 |
| First global owner sweep, completed | 579 | PID list 1; FD lists 24; FD links 497; stat 50; other owner metadata 7 |
| Second sweep, partial | 432 | PID list 1; FD lists 17; FD links 381; stat 33 |
| Total | 1024 | cap exhausted; final UDP tables/context not reached |

The 50 first-sweep stat events comprise two bracketing stat reads for each of 24
PIDs plus two owner-detail stat reads. Other owner metadata is exe/net/pid namespace
before and after argv (six) plus cmdline (one). All visible PIDs were searched;
only matching owners received detailed argv/executable metadata.

899 listed FD entries are PARTIAL across both sweeps: first 497, second 402 already
enumerated. Only 381 second-sweep links had been read, leaving at least 21 of those
listed links unread, before further PID checks and closing tables/context. They
are not two completed FD sets. The second global list values/full result were not
retained, so the actual eventual second topology cannot be recovered. Even just
finishing the already listed FD work required more than the remaining zero reads.
First-pass owner PID 21027/FD16 is a partial observation, never proof of uniqueness.
The later ENOENT rows belong to shutdown, not the original cap exhaustion.

#### Minimal correction, and what must still be read again

`_identity(..., observed_start=...)` now reuses the immediately preceding post-FD
stat in the SAME PID/sweep when collecting matching-owner details. The old code
read that stat again before exe/namespaces. Both FD-bracketing stats for ALL PIDs
are preserved, as are the final identity/stat after argv, both independent global
PID/FD sweeps, both socket tables, and both context reads. A recycled PID after the
reused stat is still rejected by the final identity comparison. Exe/namespace,
FD links and PID listings are NOT cached across sweeps/observations. No process
name filter, only-owner second pass, or skipped foreign owner was introduced.

The reused read ID is explicit in source_reads, deduplicated when referenced twice;
all actual operations retain consecutive event IDs and their own time/source fields.
No phantom operation or synthetic timestamp is inserted. Version-2 serialization
and old-journal decoding are unchanged; no extra compression layer was added.
This saves ONE get event per relevant owning process per sweep, two for one owner.
It does not solve this runtime topology's read cap and must not be advertised as
another ready-to-succeed peer trial.

Actual 8076 provenance occupied 109091 of 123565 bytes (~88.3%); source strings
another 10896 bytes. At the cap, reusing one event permits another real event to
be attempted, so the prefix still records 1024 events; a large byte reduction
would be misleading. Measured offline examples (separate from observed 8076):

| Explicit fixture | Before | After | Result at CURRENT limits |
| --- | --- | --- | --- |
| Reconstructed first-sweep topology, stable second sweep assumed | 1024 reads / 124680 B | 1024 / 124675 B | both INCOMPLETE |
| Synthetic reduced FD load | 702 reads / 86214 B | 700 / 85982 B | both complete metadata candidates, no identity approval |

The real prefix was 123565 B, not the reconstructed 124680 B: fixture timestamps
and unknown metadata are explicitly synthetic and affect encoded widths. Compare
before/after only within the same fixture. In the reduced fixture provenance drops
75461->75237 B with all references round-tripped and validated. The meaningful
saving is two actual read events, not omission of provenance for performed work.

#### Representative regression and remaining budget decision

`tests/fixtures/rover_socket_8076_topology.json` is hash-bound to 8076's manifest
and socket journal. Its 24 first-sweep PID values/order and 497 FD numbers, relevant
owner/context/endpoint are extracted from retained events. Nonowner start ticks,
nonmatching link values, namespaces not inspected and 29 irrelevant UDP rows are
UNKNOWN historically; stable placeholders are explicitly declared. Repeating that
first tree for the second sweep is a modeled assumption, not recovered evidence.
The reduced-load and larger stress trees are labeled synthetic separately.

8076 retained a hash of socket_inventory.py but not the guessed helper snapshot
path in executed_sources. Frozen baseline tests use the byte-identical retained
b9ee offline-correction source and assert it matches the hash actually recorded
in 8076/source_hashes.json (`eb8b70...67493`). No absent source file was reconstructed
inside historical evidence. The tests exercise fake proc -> actual monitor wire
serialization -> file -> reader -> association, and reject partial searches, a
late second owner, PID recycling immediately after reused stat, and agent/FD loss
while closing. Existing namespace/permission/dual-stack/reference/truncation tests
remain in the affected run. No operational environment availability is implied.

For a stable repetition of the OBSERVED first-sweep topology, with P=24 visible
PIDs, F=497 relevant-search FD links per pass and O=1 owning process, the existing
complete-query cost model is `28 + 6*P + 2*F + 18*O = 1184`. The correction changes
only owner overhead to `16*O`, giving 1182. Even eliminating all owner-detail
metadata would leave 1166 under these bracketing requirements, above 1024. This
model is not a claim that the unobserved historical second sweep had that topology.

**Quantified proposal ONLY; no operational limits changed:** 1280 total get events
and 160 KiB serialized row cap. Counterfactual cloned modules on FAKE proc produce
1184 / 143117 B before and 1182 / 142890 B after, with all references retained.
For the latter, margins would be 98 events and 20950 bytes, not a guarantee for
larger/changing topologies. Extra nonowner FD costs two events across stable
sweeps; an extra PID adds six overhead events plus its FD work. More owners cost
additional identity reads. Real wall/outer-query latency remains unvalidated.

This proposal would require coordinated review of Reader.MAX_READS (module
MAX_READS), MAX_BYTES, monitor.SocketRecorder.MAX_ROW, and the reader journal-size
bound. Only raising reads would still exceed the current 128 KiB output cap;
only compacting bytes leaves the read cap failure. At 64 samples, 160 KiB raises
the maximum socket-file budget by 2 MiB over 128 KiB, excluding per-line newline.
The current constants remain 1024 events, 128 KiB, 0.25 s cooperative query,
0.75 s outer query, 128 PIDs, 2048 FDs/pass, 64 samples/5 s. No native rebuild,
selector rewrite or retrospective upgrade of any incomplete inventory occurred.
Approval of a budget change, or a demonstrably equivalent lower-read algorithm,
is still needed BEFORE proposing another full peer reception. Do not test blindly
with these unchanged limits and claim this small optimization solved the blocker.

#### Joint budget review — 2026-10-24 (proposal; NOT selected)

Continuation evidence: `simulation/ros2_gazebo/results/rover_socket_offline_2026_10_24/budget_comparison/`.
No stable-tree reconstruction repeated. Reuse the preceding measured offline
1182 events / 142890 B, assuming repetition of the observed FIRST sweep. Historical
second-sweep completion remains unknown. The two-event saving and baseline-source
hash binding above remain unchanged; the 1024-event default cannot finish even
that stable model. No further completeness checks have been removed.

| Proposal/default | Margin vs stable reconstruction (events / B) | 64 maximum rows | Rows fitting 8 MiB | Nominal schedule at 5 s |
| --- | --- | --- | --- | --- |
| CURRENT 1024 / 128 KiB | -158 / -11818 | 8 MiB | 64 | 320 s |
| Proposed 1280 / 160 KiB | 98 / 20950 | 10 MiB: incompatible | 51 (7.96875 MiB) | 255 s |
| Candidate 2048 / 256 KiB | 866 / 119254 | 16 MiB: incompatible | 32 (8 MiB) | 160 s |

MAX_ROW includes the persisted newline; the helper also counts its newline before
fallback. At 51*160 KiB, 32768 B remain; do not assume a 52nd full row fits.
The present 8 MiB socket maximum is implicit in LIMIT=64 times MAX_ROW=128 KiB,
not a separate budget controller. `analyze_series` admits at most 64*(MAX_BYTES+1)
bytes: this tolerance must not silently become permission to write extra bytes.
Trace BYTE_LIMIT=2 MiB and source SCAN_LIMIT=64 MiB are SEPARATE channels/scan bounds.
8 MiB here means socket series, not the combined diagnostic archive. If approval
instead means 8 MiB for trace plus sockets, reserve the 2 MiB trace first: the
socket capacities become 48/38/24 rows respectively, before other receipts. A
whole-archive bound would need a separately agreed accounting scope.

NEW synthetic stress (63 PIDs, unrelated sockets/FDs; not historical topology),
through capture -> actual monitor serialization -> JSONL -> reader -> analyzer:

| Budget | Events / serialized B | Outcome |
| --- | --- | --- |
| 1024 / 128 KiB | 1024 / 123676 | read budget; incomplete |
| 1280 / 160 KiB | 1280 / 151599 | read budget; incomplete |
| 2048 / 256 KiB | 1346 / 159447 | repeated endpoint/process candidate only; identity BLOCKED |

The last has 702 events and 102697 B margin. With an additional shared owner it
uses 1364 / 161963 B, and the ANALYZER rejects unique association. PID change,
process disappearance, permission denial, missing post-context, a forced byte cap
and synthetic expired clock all remain uncertain/incomplete across all three
budgets. Reasons survive the persistence/read path. No executable-name filtering
or owner omission is introduced. Existing truncated/reference/late-owner tests
are retained; their previous passing run is historical, not a fresh operational
check. 25 new cases passed; raw rows and metrics are in the continuation evidence.
The first draft of the missing-context test changed a shared dict, accidentally
changing the expected context too; corrected to remove post-read context. This
was a test-fixture error, not an observed product defect.

**Decision:** none of these candidates is approved/selected for operation.
1280/160 is compatible with 8 MiB ONLY if reduced to <=51 rows, and covers the
stable reconstruction but not the larger synthetic stress. 2048/256 fits that
stress per row but its <=32-row series is too short for the current conservative
140 s outer collector +60 s protected-close budget. More row bytes alone cannot
solve the problem. No production parametrization was added: changing four
constants plus admission semantics just for a candidate would create an unreviewed
operational path. Tests use temporary scoped overrides; defaults/manifest stay
intact. An intermediate row cap with 2048 events could be evaluated separately,
but is not measured or selected here.

Time remains an independent unknown: .25 s cooperative query, .75 s child timeout,
600 s monitor, 64 current observations at >=5 s interval are unchanged. Fake clocks
prove termination/classification, not real /proc latency, scheduling or fsync cost.
No extrapolation of real latency from 1182 synthetic reads is justified. The
aggregate arithmetic test rejects 64-row sizing for either larger candidate;
it does NOT claim an aggregate runtime writer has been implemented/tested.

Before another peer trial, explicit budget approval and a coordinated implementation
are still required: capture MAX_READS/MAX_BYTES, SocketRecorder MAX_ROW/LIMIT,
reader series count/file bound, aggregate byte accounting and admission coverage
must share the reviewed values. No environment-variable override or new profile.
Only Python helpers would change; native wrapper/library do NOT need rebuilding.
Manifest hashes of those native artifacts must still match fresh container reads;
this offline review does not certify current availability of container /tmp paths.

Preparation must finish BEFORE opening: fresh precheck under existing exclusion,
verified disposition/current guards/environment/processes, helpers hashed and
native pair/collector verified, then one protected start. Check complete inventories,
validated normalized peer and GUI supervision; obtain Joel's NEW visual response.
Before collector require a fresh monitor record and budget for BOTH 140 s capture
and 60 s close in socket schedule and monitor wall time. Existing capture_window
checks 200 s monitor time but only 140 s socket schedule: it is insufficient for
this proposed stronger end-to-close coverage and must be reviewed before adopting
reduced row counts. Do not silently claim the current check guarantees close
coverage. With 51 rows, even nominally <=11 may be consumed before reserving
40*5 s; real query/scheduling overhead can make this tighter. With 32 rows the
200 s reservation cannot pass even at outset. If visual response is late, inventories
are empty/incomplete, context changes, or coverage is insufficient: no collector;
request protected close while monitor is active. Never extend limits or reopen.
Preserve monitor receipt and any supervisor-provided rc separately; current
lifecycle SUCCESS is not a waited monitor rc or proof of complete capture.

Joel: socket_inventory.Reader.get records each actual metadata operation;
_owners searches ALL visible PID/FD owners twice; _identity brackets owner identity;
pack_inventory/unpack_inventory preserve references; SocketRecorder.sample persists
bounded rows; analyze_series/match_peer reject incomplete/ambiguous series.
Follow these symbols in VS Code, then capture_window for admission. These are
optional diagnostic instrumentation, not a rover control path. Socket ownership
supports a visible endpoint->process candidate over sampled intervals; it does
not prove packet origin, effective SYSID or the whole rover identity. All remain
BLOCKED pending the existing contract and separate authorizations.

### Implemented offline budget and capture/close admission — 2026-10-25

This section supersedes the preceding *proposal-only* budget for FUTURE code.
Historical measurements/limits/results remain as recorded. Joel authorized code
preparation, not a deployment or new session. Nothing was copied into a container.

`budget.py:SocketBudget/SOCKET` is the single reviewed contract: **2048 get events,
256 KiB per framed row, 64 observations, 16 MiB socket journal, 5 s interval**.
The .25 s cooperative query, .75 s outer timeout and 600 s monitor are unchanged.
No inherited environment selects a budget. Invalid types/ranges, nonfinite timing,
row-count/product exceeding aggregate, or incoherent timeout ordering are rejected.
The socket budget is separate from the existing 2 MiB native trace channel and
64 MiB source-log scan bound; it is NOT a 16 MiB whole-session archive bound.

Reused measurements, not another historical reconstruction: stable-first-sweep
repetition was 1182 events /142890 B; margins now **866 events /119254 B**.
Synthetic stress was 1346 /159447 B; margins **702 /102697 B**. These are NOT
measured live latency or guaranteed bounds on every future topology. Current-code
regressions rerun the modeled topology because relevant budget/serialization code
changed; historical absent second-sweep data remains absent. Provenance and both
all-PID/FD walks remain; no executable-name filter or candidate-only second walk.

Effective bounds, including framing:

- `budget.encode_row`: UTF-8 JSON + exactly one newline; refuse >262144 bytes.
- `SocketRecorder.sample`: refuse oversized output/row, count >64, aggregate append
  beyond 16777216 B or a file length inconsistent with its successful byte counter.
  Short writes/fsync/close failures retain uncertainty and stop further collection.
- `budget.journal_rows`: preferred PATH reader checks regular/no-symlink file and
  fstat size BEFORE reading. It then uses bounded readline(row_limit+1), checks
  newline, per-row, row count and aggregate, including files that grow after stat.
- `analyze_series` consumes those rows incrementally; checks declared budget and
  persisted byte counter when supplied, row count, references and all associations.
  No cherry-picked successful row can override a partial/changing series.

Use the path interface for future analysis; do NOT first call read_bytes on an
arbitrary file:

```python
from pathlib import Path
from tools.rover_xrce_trace.socket_inventory import analyze_series
report = analyze_series(Path(socket_journal), monitor_socket_summary,
                        validated_status_writer, lifecycle_id,
                        receipt_wall_ns=status_receipt_wall_ns)
```

The retained bytes API is for already-bounded caller-owned historical buffers;
it cannot undo an allocation made by its caller. File reading no longer allocates
the whole journal or a list of all lines. Expected raw input working buffers are
one <=256 KiB row (+1 rejection byte), one decoded row at a time and retained
bounded analysis/candidate summaries. Python objects/JSON decoding and encoding
multiply raw sizes: **16 MiB is a disk/wire cap, NOT an RSS cap**. Bytes callers may
already hold up to 16 MiB; subprocess capture_output holds at most a correctly
verified helper's one framed result. /proc event/identity work and pre-fallback
encoding also consume memory under event/PID/FD/file bounds. No live peak RSS was
measured or promised. Native/GUI logs have their separate existing bounds.

#### Admission through closure, not N * interval

`SocketRecorder.summary` now records byte usage, next scheduled observation and
last query finish. `capture_window` requires a fresh same-boot OBSERVING record,
a complete recent inventory, exact current budget, no missed next slot and
consistent counters. It computes available slots from BOTH count and worst-case
remaining bytes, clips slots to the monitor deadline minus query timeout, and
calculates `last_start = next_start + (slots-1)*5`. That last programmable start
must reach `now + 140 + 60`; monitor time also reserves those 200 s plus the final
query timeout. A record with 40 slots and next_start=now+4 reaches only now+199,
and is rejected even though 40*5=200. A delayed visual answer must be checked again;
no automatic extension/refresh/retry. Future scheduling is explicitly conditional
on timely queries, never proof of samples not yet taken. Analyze actual socket
windows against Status receipts afterward; socket-only analysis does not certify
monitor/lifecycle closure, on either side of the last inventory.

The monitor's CLOSED/capture_complete receipt is still distinct from OS exit.
The short-lived supervisor now records an actual Popen.poll return if observed
while it owns the child, with PID/start_ticks and reception times. Summary exposes
that separate `monitor_exit`; once the supervisor has exited and no wait status
was retained it reports **UNKNOWN**, not an rc reconstructed from CLOSED/PID absence.
No lifecycle success/failure decision or shutdown signal policy was changed.

#### Deployment and next protected session (NOT performed here)

`selection.HELPERS/deployment/helper_sources` now includes budget.py at the bootstrap
`/tmp/budget.py`, then its own isolated overlay sibling. The same mechanism copies
selection, monitor, inventory, analyze and budget, freezes all hashes and validates
presence before launching. The deployed-entry regression uses those real renamed
bootstrap paths, not an import from the repository. Old descriptors are historical
and are NOT rewritten to have current helper hashes. Future selector/monitor/reader
must use the same reviewed helper snapshot/contract. Native manifest and ELF hashes
are unchanged; Python-only changes require no recompilation.

Today's bounded metadata query initially failed inside the sandbox (permission
error), then succeeded through the approved read-only route: exact documented
engine/container/image, but container **exited, Running=false, Pid=0**, FinishedAt
2026-10-25T07:48:17.5089221Z. It was NOT started. Therefore current in-container
helpers, temporary wrapper/library/collector availability and graphics/SDF/resource
environment are **NOT REVALIDATED**. Never substitute local paths or another binary.
Future source/hash index and test receipts are in
`simulation/ros2_gazebo/results/rover_socket_offline_2026_10_25/prepared_contract/`.

Before a separately authorized peer trial: container must already be active with
matching identity; fresh existing precheck under exclusion, disposition/guards,
process/session checks; verify exact native pair and collector in manifest; copy
only reviewed helpers by existing mechanism, record their hashes and verify overlay.
Then one protected opening, inspect unique agent/library/monitor, normalized validated
peer, complete inventories with relevant inodes, and GUI supervision; wait for Joel's
NEW visual confirmation. Recheck fresh 200 s admission immediately before ONE
20-sample/120 s/reserve-streams collector. Missing/late visual response, GUI exit,
unknown context, incomplete/empty relevant inventory or insufficient budget means
close WITHOUT collector. Close while monitor is active; preserve lifecycle result,
monitor closure receipt, separate OS rc if actually available, and actual socket
coverage independently. No new opening is authorized by this preparation.

Read these VS Code symbols: `SocketBudget` (shared units/caps), `Reader.get` and
`_owners` (actual operations/all owners/two walks), `pack_inventory/unpack_inventory`
(reference-preserving compression), `SocketRecorder.sample/summary` (bounded disk
and schedule), `capture_window` (conditional admission), `analyze_series/match_peer`
(all-row validation). All are optional diagnostic code, not rover movement code.

### Closed history after container reactivation — 2026-10-25

This supersedes the old requirement that a CLOSED pointer's StartedAt/proc boot
must equal the CURRENT execution. It does not relax active-operation checks or
rewrite any history. Review evidence:
`simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_25/reactivated_container_review/`.
The earlier GUI-control evidence94081694 remains intact, including its original
BLOCKED result. No new GUI or peer session was opened during this correction.

Four identities/contexts remain separate:

1. Persistent Docker environment: engine ID, full container ID, image, exact name
   and creation timestamp must still equal the original reference/manifest.
2. Historical session: CLOSED target, matching start/stop FINISHED operations,
   selected overlay/helpers and launch/agent/monitor receipts must be coherent.
   All historical proc boot IDs must agree WITH EACH OTHER. Historical PIDs/ticks
   are not looked up as though they belonged to the current execution.
3. Current execution: known ACTIVE metadata, StartedAt and container /proc boot;
   complete current ownership/ambiguous-agent/session inventory, host workers,
   guards and restriction checks under execution then registry exclusion. The
   reader brackets its inventory with a metadata/boot recheck; change/failure blocks.
4. Future protected opening: a NEW `environment_execution_reference.json` and lease
   field pin the current persistent identity/StartedAt/container boot. This is never
   copied over the historical `rover_environment_reference.json`.

`classify_last_session` returns explicit historical/current execution contexts,
`container_reexecuted`, `container_boot_changed`, and the original monitor phase/
capture flag. A consistent completed CLOSED history may be historical in a new
execution of the SAME persistent container. Boot changes alone are also reported
as a different proc context; neither proves a Docker-engine restart. Container
kernel boot is not host-worker boot or daemon identity. No clock-duration or
cross-boot PID continuity is inferred. Unknown current identity, active/uncertain
target, missing closure, contradictory receipts, processes or extra state still block.

A historically INCOMPLETE monitor remains INCOMPLETE. The exact51790 proof and
reviewed disposition mechanism remain case-pinned. Its audit cannot complete an
e238 history: e238 is assessed from its OWN operations/receipts. In particular,
e238's monitor CLOSED/native-capture receipt never retroactively completes its
incomplete socket inventories or creates a Status sample that was not collected.

Consumer chain: `classify_last_session` -> `dry_run` -> `diagnostic_precheck` ->
`diagnostic_precheck_locked` -> standalone read-only CLI or `run_lifecycle`.
MCP/backends enter the existing lifecycle; no MCP changes or alternate entry added.
Pure disposition/query paths still have no start consent. `historical_proof=false`
in the current report means the special INCOMPLETE-disposition case is NOT needed;
complete-history eligibility uses its separate CLEAR branch. It is not a failed
complete-closure condition. `disposition_consumed=false` confirms no foreign audit
was borrowed.

For start/restart after retained history, lifecycle consumes the current reference
under the SAME locks, revalidates before creating its operation and around each
backend step, and the inherited backend verifier checks the pinned lease execution
again. A change before the lease blocks with no backend call; a change/read failure
once the operation is active retains UNCONFIRMED and restrictions. Ordinary cold
starts with no retained diagnostic history keep their existing bootstrap behavior;
this correction is not a new generic Docker launcher or recovery override. Stop
policy/signals, vehicle gates and the terrestrial adapter are unchanged.

Current read-only result at2026-10-25T09:03:43Z: **SATISFIED**, historical pointer
**HISTORICAL_CLOSED_POINTER**, owner e2381f94-12bb-4826-8e5c-07bfed20b6f1.
Persistent identity matches. Original StartedAt2026-10-21T08:24:48.062034411Z /
boot51f3835d-91d2-4044-a115-2dcb8c14768a remain original. Current execution is
StartedAt2026-10-25T08:40:21.826966668Z /bootfbd6bc53-f08d-4e5c-9d77-9ed87c8b562a.
Freshness, reader completeness, no restrictions/guards/other sessions/host workers
and known host identity passed. The observation is NOT a reusable admission token.

A continuation artifact read confirmed wrapper/library/collector hashes unchanged;
selection.py, monitor.py and socket_inventory.py copied into /tmp are older,
analyze.py matches, and /tmp/budget.py is absent. No deployment or rebuild occurred.
These are future PEER requirements, not prerequisites of the normal-agent two_drones
control. The small audit wrapper initially failed to import host `tools` AFTER the
precheck had completed; fixing its sys.path resumed ONLY the artifact read after
rechecking active execution. It did not repeat the precheck or start any process
other than bounded metadata-query Python.

The one previously authorized graphical control remains PENDING, with no opening
consumed. When resumed: current identity/process/guard precheck under lifecycle
exclusion, then exactly:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones
```

No diagnostic manifest, readiness/prearm, services or collectors. Retain separate
new launch/OGRE logs and the effective GUI command. Ask Joel for NEW confirmation
of runway and TWO drones, and await it; inspect within the proposed bounded30 s
visual-observation interval. Backend SUCCESS is not visual confirmation. A vanished,
black/incomplete or uncertain GUI means preserve evidence and close with no retry:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones
```

Use that protected close for this session; verify formal result, processes and
guards afterward, preserving uncertainty without manual cleanup. A favorable
window only establishes punctual availability, not a renderer repair or rover
causality. The peer experiment is NOT authorized by this pending graphical control.


### Cierre gráfico y traspaso pasivo /3 — 2026-10-25

La prueba gráfica pendiente descrita arriba ya se consumió con agente normal:
start a9c6a83c-169a-4098-b398-71ba43d1b252 y stop
4ab52609-3bb3-4ea1-85a7-6ac021ac3e9f, ambos SUCCESS. Joel confirmó pista y dos
drones completos. URI/meshes desaparecieron de los logs; errores de materiales y
shaders persistieron. No se ejecutó peer ni colector. Evidencia y límites:
[README del ensayo](../../simulation/ros2_gazebo/results/gui_control_two_drones_2026_10_25/7074b972-8e58-4dad-a953-7d901a1357d2/README.md).

Tras cerrar se revisó el build aislado de the multi-agent subsystem con odometry-fields, sin ejecutar
su binario. Fuentes actuales y snapshots coinciden; configure/build históricos
retorno 0, enlace ELF y dependencias con candidatos disponibles contrastados por
lectura. Eso no prueba recepción ni carga efectiva en runtime. La selección
explícita PROPUESTA, NO AUTORIZADA NI EJECUTADA es:

```text
/tmp/tfg-rover-odomfields-sKoVKFJr/build/rover_passive_collector --output <NEW_PRIVATE_DIRECTORY>/journal.jsonl --max-samples 20 --duration-s 120 --reserve-streams --odometry-fields
```

SHA-256: `637f2c3e3475983146b9891a058760cc6ece0ae6ea22e37d2484cd7f46e4d464`.
No reemplaza el histórico `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93`.
No cambia manifest de agente ni selección activa. Antes de usarlo: autorización
separada, sesión three-vehicle protegida, hashes frescos, directorio privado nuevo,
recibo/stderr/rc y contexto conservados. La CLI exige reserve-streams antes de
odometry-fields. El lector rover_passive_journal acepta /3 mediante analyze_bytes
con recibo y retorno; GID/RMW por muestra siguen separados de candidatos del grafo.
Pose/twist/covarianzas son datos brutos, no acreditan frame, unidades físicas ni
asociación con modelo. Status no añade modo, external_control o failsafe.
No existe límite de bytes obligatorio: 16 KiB es umbral de informe, no garantía.

Regresión offline afectada: 18 tests pasados, con fixtures/dobles; no ejecutó el
colector ROS preparado. Revisión exacta en collector-odometry-fields-selection-proposal.json
dentro de la evidencia anterior. Identidad completa y movimiento siguen BLOCKED.


### Ensayo peer /3 autorizado — 2026-10-25, apertura consumida

Evidencia: [0f678646](../../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_25/0f678646-fe41-47b0-ba33-20fad1ae873e/README.md).
Se corrigió primero el precheck: dry_run verifica los campos requeridos y el
estado del entorno antes de llamar classify_last_session. STOPPED,
DOCKER_UNAVAILABLE, UNKNOWN y registros parciales quedan explícitamente BLOCKED;
los TypeError de programación se propagan en esta ruta. No se fabrican registros.
Se conserva el bloqueo por identidad distinta y por cambios durante el inventario.
111 tests offline de disposición/clasificador pasaron antes de la operación;
52 tests de disposición pasaron después al añadir cuatro regresiones del lector
real con entradas temporales. Son tandas distintas y parcialmente solapadas.

El contenedor exacto se reactivó UNA vez tras verificar /ros_entrypoint.sh
(setup ROS y exec bash), engine/ID/imagen y mounts. No se recreó ni reconstruyó.
El precheck fresco bajo exclusión dio SATISFIED. Coincidieron binarios peer y /3,
fuentes del build, corrección de recursos y helpers (incluido budget.py). Lifecycle
desplegó la selección congelada de 2048 lecturas/256 KiB/64 observaciones/16 MiB.

Start 104e100b-6614-49d5-85ea-2f070350cc67: SUCCESS. Joel respondió realmente
«No, la veo negra». Se omitió el colector /3; no hay journal, footer, recibo de
colector ni datos R1 nuevos. Cero muestras significa NO EJECUTADO, no ausencia de
publicación. No hubo reapertura, cambios gráficos ni servicios de vehículos.
Stop 897be6db-83d0-4e65-804f-1b10ee416617: SUCCESS; destino CLOSED; lecturas
posteriores sin procesos atribuibles, ambiguos o agentes y sin guardas/restricción.

La captura del monitor NO cerró completa: phase FAILED, capture_complete=false,
PermissionError en /proc/1358/exe durante el intervalo de cierre; rc UNKNOWN.
Se conserva la excepción original. La proximidad al cierre no demuestra por sí
sola desaparición, zombie ni causa de permisos. No se corrigió este componente
durante la operación ni se equiparó lifecycle SUCCESS con captura completa.

Se conservaron 84 registros nativos válidos (42 creaciones), incluido writer Status
010feb7d9c00be420000000000000f03, GID de conversión nativa
010feb7d9c00be420000000000000f030000000000000000, cliente/generación 1,
ClientKey 2902458371, sesión 129, intento 15, writer_id 14, dominio 0.
El peer nativo 127.0.0.1:37604 se normaliza a 127.0.0.1:58514 por el contrato
UDP/ELF fijado. Esto no es un GID recibido por muestra: el colector no se ejecutó.

Ocho inventarios con lecturas repetidas coherentes: 26 eventos y 6305–6312 B por
registro; total 50482 B. Cero filas UDP relevantes/inodes/propietarios, por lo que
NO hubo barridos de propietarios ni validación de su coste con carga real. La
salida pequeña NO acredita peer→SITL. Toda la serie está analizada, sin elegir una
fila favorable. No se infiere SYSID efectivo ni origen de paquetes.

Logs conservados: cero errores de URI/meshes observados; persisten excepciones
fixed-function/materiales de OGRE. No se observó device removal ni error de
creación de ventana en estas firmas; la pantalla negra sigue sin causa única
acreditada. Antes de proponer otra apertura: investigar offline el error de lectura
del monitor y la falta de endpoint seleccionado usando los originales. La GUI debe
resolverse con hipótesis revisable. El historial FAILED no se convierte en CLOSED;
ninguna disposición de otro descriptor puede justificarlo. Nueva apertura requiere
autorización y precheck frescos. Identidad completa y movimiento siguen BLOCKED.

### Corrección offline tras 0f678646 y precheck actual — 2026-10-25

La traza histórica y sus 93 archivos/manifiesto permanecen intactos. En agents(),
el monitor buscaba el basename exacto de cada /proc/PID/exe, incluyendo procesos
ajenos. PermissionError de /proc/1358/exe escapó de agents -> run -> main, que
persistió FAILED/capture_complete=false. No se conservó stat/argv de ese PID en
ese instante: no podemos certificar si era zombie, proceso vivo sin permiso o un
cambio concurrente. Lifecycle SUCCESS sólo acredita su propia parada, no este
monitor ni una recepción que se omitió por GUI negra.

Corrección: antes de exe se comprueba stat; sólo un zombie observado estable en
ambas lecturas (mismo start_ticks) se descarta como ejecutable vivo. ENOENT conserva
la semántica de desaparición; permisos/datos de proceso incoherentes producen un
candidato UNKNOWN, nunca ausencia. La verificación falla cerrada y el monitor
puede seguir drenando hasta un recibo INCOMPLETE en vez de abortar por esa lectura.
No modifica señales, límites, reservas ni criterios de captura completa. Tests con
árbol /proc ficticio recorren drenaje -> archivo -> recibo para zombie y acceso
denegado; no prueban retrospectivamente el estado del PID histórico.

El endpoint Status histórico raw 127.0.0.1:37604 se normaliza a :58514 con el
contrato fuente UDP/ELF fijado. El header/recv local revisado confirma sin_port sin
ntohs en IPv4EndPoint: no hay defecto demostrado de conversión que justifique otro
swap. Peer/generación/intento coherentes; ocho lecturas repitieron tablas sin
filas relevantes. La topología completa no se guardó, sólo conteos/hash y filas
seleccionadas: no puede reconstruirse qué otro puerto estaba en las tablas.
No se atribuye la ausencia a fragmentación, reinicio, namespace o gráficos sin prueba.

Observación mínima preparada: table_scope_before/after añade hasta 32 endpoints
locales NO seleccionados, derivados de las MISMAS lecturas, más indicador de
truncamiento y hash global ya existente. No se buscan propietarios por parecido,
puerto intercambiado o nombres. Si no caben, se omiten explícitamente dentro del
fallback INCOMPLETE; no se amplían 2048/256KiB/64/16MiB. Regresión recorre captura,
serialización, archivo, lector y asociación: diagnóstico presente con cero match
sigue NOT_OBSERVED_NOT_ABSENCE_PROOF. Sigue pendiente medirlo en sesión acreditada.
Cambios sólo Python: no requieren recompilar agente, wrapper o colector.

Precheck ACTUAL bajo exclusión: BLOCKED por "Monitor closure absent/incomplete/
contradictory" del descriptor 104e100b-6614-49d5-85ea-2f070350cc67. Entorno activo,
lecturas actuales completas, sin procesos/guardas/restricciones; disposición de
otro historial no consumida. La autorización condicional pasiva NO consumió una
apertura/recepción/reactivación. No se desplegaron helpers durante este bloqueo.
La opción headless existente no elude el precheck. No se creó una recuperación
administrativa ni se convirtió el monitor FAILED en CLOSED. Evidencia y pruebas:
[ingeniería offline](../../simulation/ros2_gazebo/results/rover_navigation_offline_2026_10_25/71c84a57-51fb-4c47-9b6f-874e8a295adf/README.md).

### Revisión separada de FAILED 104e100b — 2026-10-25

Ampliación acotada, no override: session_precheck._failed_closure_proof acepta sólo
104e100b-6614-49d5-85ea-2f070350cc67 con los 93 originales del manifiesto SHA-256
2cbfa422e39f75ea64967467d59176ce8a079b2e79e7f00c05bc1e6635e65504. Verifica todos
los bytes/tamaños, descriptor/selección/launch/referencia, operaciones FINISHED
start/stop, retorno real 0, informe independiente de limpieza sin residuos ni
auxiliares ambiguos y comprobación posterior sin procesos/guardas. PermissionError
por sí solo no cumple esa prueba. No prueba que PID1358 saliera ni que el monitor
observara el cierre: su recibo queda FAILED/capture_complete=false, captura INCOMPLETE.
La clasificación de infraestructura cerrada sigue BLOCKED hasta disposición aparte.

historical_disposition ahora distingue los dos propietarios revisados; query/apply
requieren el propietario exacto y no reutilizan scope/destino/autorización de 51790d37.
La auditoría nueva se almacena en historical_dispositions/104e100b...; los originales
y la auditoría antigua no se editan. Validación actual y exclusión se reutilizan sin
cambiar su orden. apply revalida dos veces la evidencia y el alcance bajo los locks;
cambio de contexto, original, guarda, proceso o digest bloquea sin renovar alcances.
La ruta de idempotencia/claim durable y fallos parciales se mantiene. Declaración
registrada NO autentica a una persona. Tests de ampliación usan sólo directorios
temporales, incluso cuando simulan ProjectDisposition.

Dry-run REAL de esta tanda: DRY_RUN_ELIGIBLE, ocho condiciones verdaderas; entorno
actual ACTIVE y consistente, sin guardas/restricciones/procesos ajenos observados.
Scope SHA-256: 3062abcb03521e2b20f04f756931c9772531090eb5959f95476153e9a502b480.
NO se aplicó. Evidencia:
[31c8d4bd](../../simulation/ros2_gazebo/results/rover_failed_review_2026_10_25/31c8d4bd-50b1-44c7-b36a-81e9900e2e0c/README.md).

Llamada exacta para una FUTURA aplicación, sólo tras autorización explícita de este
alcance; no está ejecutada ni autorizada en esta tanda:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition apply-reviewed --owner 104e100b-6614-49d5-85ea-2f070350cc67 --scope-sha256 3062abcb03521e2b20f04f756931c9772531090eb5959f95476153e9a502b480 --authorization 'AUTHORIZE_DIAGNOSTIC_DISPOSITION 104e100b-6614-49d5-85ea-2f070350cc67 3062abcb03521e2b20f04f756931c9772531090eb5959f95476153e9a502b480'
```

Efecto limitado: intent.json/originals.json de auditoría separada; no cerrar monitor,
convertir FAILED en CLOSED, completar captura, liberar reservas o autorizar arranque.
El precheck sólo puede consumir esa auditoría si assess_disposition vuelve a
confirmar alcance exacto y lecturas actuales frescas. Una respuesta perdida exige
query con --owner 104e100b..., nunca repetir ciegamente ni sustituir el digest.
Si el alcance cambia, se requiere nueva revisión/autorización, no un reintento.

#### Recepción pasiva posterior, todavía sin autorización de apertura

Tras eventual aplicación revisada hacen falta precheck actual y autorización
independiente. Vía existente, NO ejecutada:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --headless --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.peer.json
```

Headless no exige confirmación visual ni acredita que la GUI esté reparada. Conserva
agente único, biblioteca cargada, monitor y nuevo prefix. Selección preparada con
hashes exactos de manifest/5 helpers/budget y límites:
future-passive-selection.json en la evidencia anterior. No desplegada en esta tanda;
los binarios existentes necesitan verificación FRESCA de disponibilidad/hash, no
reconstrucción rutinaria. Pareja peer 2c81395a.../cf253726... permanece fijada.
Colector /3 explícito: /tmp/tfg-rover-odomfields-sKoVKFJr/build/rover_passive_collector,
SHA-256 637f2c3e3475983146b9891a058760cc6ece0ae6ea22e37d2484cd7f46e4d464.

Antes de invocarlo UNA vez: capture_window del overlay con recibo/boot actuales,
2048 lecturas/256 KiB/64 filas/16 MiB, sin fallos ni contexto parcial y margen
condicional >=140 s captura +60 s cierre tanto en monitor como en inventarios.
20 muestras/120 s/--reserve-streams/--odometry-fields, directorio privado nuevo,
stdout como recibo, stderr, rc real o UNKNOWN. No aumentar plazos. Detener por la
vía protegida al terminar o ante fallo; el monitor debe seguir activo hasta la
petición de parada y observar salida antes de su límite. Lifecycle SUCCESS no
sustituye su recibo/exitcode. No readiness/prearm ni servicios/control de vehículos.

Lo que puede resolver: MessageInfo de Status, writer/RMW/contexto XRCE, peer y,
si las lecturas lo muestran sin ambigüedad, socket/inode/FD/proceso. Endpoints
no seleccionados sólo diagnostican el alcance, no son coincidencias alternativas.
Odometry /3 aporta pose/velocidades/frames/covarianzas y ambos relojes de muestras
RETENIDAS, no frecuencia/pérdida/jitter del flujo entero. No basta para acreditar
modelo: requiere bridge/proceso/YAML/modelo efectivos y procedencia. No basta para
SYSID efectivo: argv/ClientKey no lo acreditan; necesitaría estado efectivo por una
interfaz pública autorizada aparte. Identidad completa y movimiento siguen BLOCKED.

### Disposición aplicada y única recepción headless — cierre 2026-10-26

En esta tanda se aplicó UNA vez la disposición autorizada 104e100b... con digest
3062abcb03521e2b20f04f756931c9772531090eb5959f95476153e9a502b480. Resultado
DISPOSED_DIAGNOSTICALLY_INCOMPLETE, auditoría durable separada, originales intactos,
monitor histórico todavía FAILED. Precheck fresco posterior SATISFIED consumió
sólo esa disposición. No hubo reactivación: el contenedor acreditado ya estaba activo.

Apertura a4e77c9e-827f-43a6-ad33-d41729b18ff1 con --headless y peer: SUCCESS.
No GUI, ni confirmación visual inventada. Agente único/biblioteca exacta y overlay
con los cinco helpers/budget verificados. Sin rebuild nativo ni sustitución del
colector histórico: /3 SHA637f2c3e... explícito, 20/120/reserve-streams/odometry-fields.
El gate local dejó 542.79 s de monitor y 310.43 s de programa de sockets, mayores
que los 140+60 s exigidos. Una sola recepción rc0 en 20.835 s: 1 Status +19 odom.
Parada 83e9879e-81cb-4e3d-8b7e-420b8e9de65d inmediata: SUCCESS. Monitor CLOSED,
capture_complete=true, errors=[]; wait status del proceso monitor UNKNOWN.
Guardas/restricción nulas, procesos atribuibles/ambiguos/agentes vacíos después.
El flag gui=true del registro STOP es su valor por defecto; STOP no abre ventana.

[Originales, análisis y manifiesto](../../simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728/README.md).
Los timestamps operativos originales son UTC del 25/10; no se renombra su carpeta.

La serie de sockets contiene SIETE filas: seis REPEATED_READS_AGREE y una INCOMPLETE
por ENOENT /proc/1570/stat durante el cierre. El analizador estricto conserva toda la
serie como UNCERTAIN_OR_INCOMPLETE. Las seis candidaturas repetidas a ardurover no
son una certificación de propietario único durante TODO el intervalo ni de un paquete.
No se corrige retroactivamente la fila final, no se ignora y no hubo otra captura.
El cierre nativo del monitor es diferente de la cobertura de su canal de sockets.

Coste real: 1217–1250 lecturas por inventario completo (incluye ambas barridas), 145801–149582 B por fila;
la parcial tiene 8 lecturas/3116 B. Total893278 B; márgenes 798 lecturas,112562 B/fila,
15883938 B agregados y57 observaciones. No se agotó presupuesto. La fila parcial
es pérdida de contexto al desaparecer el agente, no desbordamiento. Esta vez hubo
socket exacto y búsqueda de todos sus propietarios; no se extrapola a otra topología.

El control de liveness del launch ya no necesita exe/argv: compara stat/boot y
trata el zombie observado como terminado. Permisos/lecturas desconocidas siguen
siendo error, no ausencia. Tres regresiones offline pasaron antes de desplegarlo;
no se recompilaron los binarios por ese cambio Python.

## Medición futura conjunta: fuentes y transporte — 2026-10-26

PROPUESTA, NO AUTORIZADA NI EJECUTADA. No se repitió 4ac58516. El trabajo actual
es preparación de lectores/transporte, con consultas de archivos, y 289 pruebas
offline. No se desplegaron helpers ni se reconstruyeron agentes o colector.

### Retorno real del monitor y ventanas de sockets

Causa de monitor_exit.json ausente en el ensayo: sim_processes.start sólo retenía
Popen hasta OBSERVING y sólo registraba poll si terminaba durante esos primeros
segundos. Luego salía, perdiéndose el handle de wait. El recibo CLOSED no recupera
ese código; el retorno HISTÓRICO permanece UNKNOWN.

Preparado: el mismo helper monitor.py soporta --supervise y lanza sólo su hijo
--observe-child. El padre permanece en wait y registra monitor_exit.json con
PID/start_ticks/boot y retorno realmente observado; monitor_supervisor.json
distingue WAITING_CHILD, CHILD_REAPED y UNCERTAIN. El arranque comprueba que el
padre no haya terminado antes de aceptar OBSERVING. Una claim exclusiva impide
reutilizar el overlay y reescribir recibos. No hay relanzamiento. El poll del
supervisor inicial no sobrescribe un recibo de wait del hijo: usa otro archivo.

Las señales del cierre protegido se reenvían únicamente al hijo con la misma
identidad comprobada; no a un PID reciclado. El padre espera con límite de 600 s;
no aumenta duración del monitor ni el presupuesto de sockets. Ante espera fallida
o escritura parcial registra incertidumbre cuando puede; si ni siquiera puede
persistirla, la falta de recibo sigue siendo desconocida, nunca rc=0 supuesto.
SIGKILL/interrupción del padre también puede impedir registrar el retorno.
Todo ello está probado con Popen/archivos temporales, no en una sesión real.

analyze_series conserva el resultado estricto y añade usable_windows de las
barridas individualmente válidas, sin ocultar otras filas. closure_evidence une
monitor, operación stop y destino CLOSED de esa misma sesión para clasificar
una pérdida terminal. Contradicciones o ausencia de cierre no la justifican.
En 4ac58516: seis ventanas válidas, una pérdida terminal de contexto del agente,
serie UNCERTAIN_OR_INCOMPLETE; Status entre las ventanas extremas, fuera de las
barridas individuales. Nuevo análisis separado:
[socket-window-analysis.json](../../simulation/ros2_gazebo/results/rover_identity_preparation_2026_10_26/c45ae0d8-5515-40ae-a359-244ac1323822/socket-window-analysis.json).

### Una sola propuesta, después de revisar las piezas pendientes

1. Antes de autorizar, revisar el [mapa de fuentes y sus bloqueos](../../docs/rover-source-correlation.md#lectores-fuentes-y-marcos--implementación-offline-2026-10-26).
   La respuesta pública GetParameters puede obtener MAV_SYSID; todavía no atribuye
   el servidor a XRCE/SITL. Faltan el registro nativo del replier/request-reply y
   el emisor de GID desde el publisher real del bridge. No existen hoy esos dos
   emisores; no prometer que otra captura idéntica completará esa identidad.
   Resolver también la fuente/versión del plugin para origen de pose/twist; no
   reemplazarla por el contrato nominal del mensaje ni por un spawn parecido.
2. Si se autoriza esa medición pasiva, hacer precheck fresco bajo la exclusión,
   verificar entorno, procesos/reservas, binarios y **nuevos hashes Python**.
   Actualizar por el despliegue existente monitor.py y sim_processes.py; los
   binarios peer y /3 no requieren recompilación por estos cambios Python.
3. Una apertura protegida headless two_drones_rover con el manifest peer, sin
   prearm ni controles. Recoger desde el inicio padre/hijo del monitor y su
   biblioteca; configuración efectiva seleccionada por argv, PID/boot/start_ticks
   del bridge antes/después, bytes/hash de YAML y SDF seleccionados, metadatos
   públicos disponibles de entidad/plugin/Gazebo. Lo no observable queda UNKNOWN.
4. En un nodo de lectura ya poseído y autorizado, sin spin concurrente, usar el
   lector opt-in GetParameters preparado (MAV_SYSID, DDS_USE_NS), una petición con
   deadline. Registrar nombre/tipo descubierto, request, respuesta tipada, tiempos
   y vínculo nativo del servidor si el emisor pendiente ya está revisado. Nunca
   SetParameters, servicios de control ni completar valores desde argv/ClientKey.
5. Sólo con cobertura/presupuesto actuales, una recepción /3 20/120/reserve-streams/
   odometry-fields, sin ampliar QoS o plazos. Mantener fuente de GID separada de
   discovery; conservar datos parciales y lecturas contemporáneas, no mezclar 40e8
   o configuraciones actuales con el historial de 4ac58516.
6. Cierre inmediato protegido mientras observa el monitor. Conservar recibos de
   monitor, supervisor y wait por separado, rc o UNKNOWN; inventarios y estado
   posterior. Si falla una condición, omitir captura/cerrar sin reabrir ni reparar.

Resultado exigible: explicar cada enlace observado y cada UNKNOWN, no conceder
identidad o movimiento desde el informe. No recomiendo otra apertura para
**acreditar identidad completa** antes de disponer de los dos emisores y el
contrato del plugin anteriores. Las lecturas/lectores ya preparados sí reducen
incertidumbre de configuración; no sustituyen esas fuentes pendientes.

### Actualización de la propuesta tras la geometría — 2026-10-26

La captura /3 existe y cerró; no se necesita otra para reproducir su antigua
negativa de orientación. [El rumbo proyectado](../../docs/rover-control.md#rumbo-con-inclinación-corrección-posterior--2026-10-26)
reemplaza la simplificación qx/qy; no acredita marcos ni pendiente operativa.
Se conservaron plazos, límites y bloqueo físico. No hubo despliegues ni operaciones.

La propuesta única anterior incorpora ahora, en su fase de lecturas autorizadas,
`rover_identity_inventory.read_rover_model_description(node, timeout_s=...)`,
usando un nodo de lectura ya poseído y ocioso. Devuelve la configuración SDF
robot_description con hash, no una identidad de entidad; comparte transporte
GetParameters de sólo lectura con la consulta de MAV_SYSID. El lector de grafo
por defecto no empieza a realizar estas peticiones automáticamente.

Conservar antes/después los publicadores, identidad de procesos, robot_description,
YAML seleccionado, creación de entidad y sockets FDM, separando esos datos de los
de Status/XRCE. El puente entre ramas es SITL JSON/FDM ↔ ArduPilotPlugin/modelo,
no una cadena artificial GID→modelo→SYSID. Los emisores nativos de publisher del
bridge/replier y la acreditación de marcos siguen siendo prerrequisitos para
prometer identidad completa, no resultados implícitos de estos lectores.

## Una futura sesión pasiva de identidad y marcos — preparación 2026-10-26

**NO AUTORIZADA / NO EJECUTADA.** No reutilizar una autorización de una captura
anterior. Geometría cerrada; ni esta preparación ni una recepción favorable
habilitan movimiento. Matriz de pruebas y límites:
[rover-source-correlation](../../docs/rover-source-correlation.md#preparación-pasiva-de-identidad-y-marcos--2026-10-26).

### Artefactos preparados y comprobación real

El nuevo manifest explícito es [diagnostic-agent.identity.json](diagnostic-agent.identity.json),
schema /2. El /1 peer y el agente instalado predeterminado permanecen disponibles
sin cambios. La selección /2 exige **los cuatro hashes juntos**, comprueba ELF y
crea un overlay privado nuevo para agente **y** bridge; no sustituye instalaciones.
El monitor verifica PID/start/boot, ascendencia y biblioteca real del bridge rover,
además del agente. Una biblioteca instalada mezclada o un reinicio bloquean la
observación diagnóstica. Los errores se persisten como FAILED, no como OBSERVING.

Build real temporal, sin ejecutar artefactos:

| Artefacto | SHA-256 |
|---|---|
| ROS wrapper | `eedd3756864cbc26fd30f14a0fcf7c46e21a9f5b3712b17a9826ced7d373c099` |
| Native Agent | `2b18ce9acc46305c48b2708de52218efc688cfa3a927e37ac9c8e7a752b40828` |
| parameter_bridge | `44b065a6bef150a42f6b8d0316007a9c775ba19d9cfc0b6a6c72f2e11128f386` |
| libros_gz_bridge | `5842aa4764e9861acaff01f8715d1fa0fd6820dab1a6f59bb365b68ff14625e4` |
| Lector pasivo nuevo | `92884e6b1883c1b2af8fb903e4ad83cf21cddf4261c99a79c004952ce9ba67c9` |

Los cuatro primeros están en
`/tmp/tfg-identity-build-1895b961-27af-4427-86fe-baadc86e81af/`, rutas exactas en
el manifest; el lector es
`/tmp/tfg-identity-probe-build-20261026-a/rover_identity_probe`.
[Verificación ELF, hashes y límites del registro de build](../rover_identity_probe/build-verification-2026-10-26.json).
Se compiló/enlazó contra rclcpp 16.0.19, rmw_fastrtps_cpp 6.2.10, gz-transport
13.6.0 y gz-msgs 10.4.0 instalados. Eso **no prueba recepción**. Hubo warnings
upstream de TinyXML2 y `expand_names`; no se corrigió código upstream ajeno.
La salida completa inicial de build se observó en herramientas, pero no se
conservó como log bruto completo; no se la reconstruye.

Receta reproducible, sólo build cuando esté autorizado y el contenedor acreditado
ya esté activo (rutas nuevas, dependencias existentes, sin instalación/red):

```bash
.venv/bin/python -m tools.rover_xrce_trace.prepare_identity /home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent /home/joelm/TFG/ardupilot_ros2_ws/src/ros_gz/ros_gz_bridge /tmp/identity-source-NEW
# Copiar ESA fuente nueva al contenedor verificado; dentro:
bash /workspace/tfg/tools/rover_xrce_trace/build_identity.sh /tmp/identity-source-NEW /tmp/identity-build-NEW
# Lector independiente, sin ejecutar ni instalar:
cmake -S /workspace/tfg/tools/rover_identity_probe -B /tmp/identity-reader-build-NEW -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/identity-reader-build-NEW --parallel 2
```

El entorno de build debe cargar `/opt/ros/humble/setup.bash` y
`/root/ardu_ws/install/setup.bash`, como la receta verificada. Cambiar directorios
puede cambiar hashes/RPATH: no sustituir los hashes revisados para superar el
precheck. No repetir builds en el ensayo ni ejecutar los binarios, ni --help,
para comprobarlos.

### Secuencia futura exacta, condicionada a autorización separada

1. Conservar HEAD/diff, fuentes efectivas, hashes del manifest y todos los helpers.
Revalidar engine/container/image y ejecución actuales; contenedor detenido o
identidad distinta bloquean, sin reactivación implícita. Consultar precheck fresco:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition diagnostic-precheck
```

Exigir SATISFIED con reservas/procesos/sesiones actuales claros. Una disposición
histórica no concede esta apertura. Validar todos los artefactos mediante
`selection.validate_sources(selection.descriptor(selection.load_manifest(...), ID))`
**sin prepare_overlay** en esta fase. Registrar también hash del lector y sus
headers compartidos; su manifest de build no es autorización. Ante ausencia o
cambio, detenerse; no reconstruir ni desplegar por tanteo.

2. Sólo con la nueva autorización, UNA apertura protegida:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --headless --profile two_drones_rover --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.identity.json
```

El backend existente despliega los helpers seleccionados antes de iniciar y fija
una referencia actual del entorno. Guardar la salida/operation.owner_id como
`SESSION` de ESTA apertura, nunca reutilizar un ID histórico. Confirmar único
agente, biblioteca exacta, bridge rover del overlay e identity_bridge acreditado,
monitor OBSERVING sin errores. La variante headless no exige confirmación visual
y no pretende resolver la GUI. No readiness/prearm ni servicios de control.

3. Inmediatamente, dentro del mismo contenedor, evaluar presupuesto y **toda**
la serie disponible de sockets (no sólo la última fila favorable):

```python
import json, time
from pathlib import Path
from tools.rover_passive_validation import session_window
from tools.rover_xrce_trace.analyze import analyze
from tools.rover_xrce_trace.socket_inventory import analyze_series
prefix = Path('/tmp/tfg_diagnostic_agents') / SESSION
monitor = json.loads((prefix/'capture/monitor.json').read_bytes())
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
plan = session_window(monitor, now=time.monotonic(), boot_id=boot)
trace = analyze((prefix/'capture/trace.log').read_text().splitlines())
assert trace['trace_valid']
writers = [w for w in trace['correlations'] if w['topic']=='rt/ap/v3/status']
assert len(writers)==1
sockets = analyze_series(prefix/'capture/sockets.jsonl', monitor['socket_inventory'], writers[0], SESSION)
assert sockets['series_state']=='REPEATED_ENDPOINT_PROCESS_CANDIDATE_ONLY'
assert not sockets['errors'] and sockets['usable_windows']
assert monitor['identity_bridge']['verified_overlay_library']
print(json.dumps({'budget': plan, 'sockets': sockets}))
```

Registrar el resultado y sus fuentes; lectura concurrente que resulte
contradictoria/incompleta bloquea. Revalidar frescura inmediatamente antes del
lector. No usar cero inodes ni una fila parcial como asociación. Si faltan margen,
contexto, supervisión, referencias o propietarios únicos: **omitir lector y cerrar**.

Presupuestos sin ampliación: monitor 600 s; sockets 2.048 lecturas / 256 KiB /
64 observaciones / 16 MiB. `session_window` reserva 140 s de captura exterior y
60 s de cierre, 41 nuevas observaciones, 512 KiB del lector y 2 MiB de traza.
Con una fila previa al máximo son **13.631.488 B = 13 MiB**, margen 3 MiB.
Es un ejemplo conservador comprobado, no tamaño observado. Con bytes/observaciones
previos excesivos se rechaza; no se aumenta el límite. Las condiciones deben
seguir cumpliéndose mientras se recoge. El presupuesto programado no garantiza
cobertura observada futura.

4. Crear un directorio privado NUEVO para ESA sesión, sin exist_ok ni sobreescritura.
En el contenedor, `mkdir -m 700 /tmp/tfg-rover-passive-validation-$SESSION` debe
fallar si ya existe: inspeccionar la evidencia, no repetir automáticamente.
Con el hash del lector nuevamente contrastado y ROS/RMW/contexto habituales:

```bash
docker exec -e TFG_SIM_PROJECT=Agentic_Drone_Mission_Control 0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f bash -c 'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; exec /tmp/tfg-identity-probe-build-20261026-a/rover_identity_probe --session-id "$1" --output "/tmp/tfg-rover-passive-validation-$1/journal.jsonl"' -- "$SESSION"
```

Conservar stdout/stderr y rc por separado. El tag permite al lifecycle existente
atribuir el proceso; el lector verifica la sesión real antes de inicializar ROS.
No cambia configuración persistente ni RMW para obtener coincidencias.
Máximo 120 s cooperativos/20 muestras almacenadas; consultas GetParameters una
vez/2 s, Scene una vez/1 s. El plazo exterior de observación sigue siendo 140 s.
Si una llamada nativa opaca no retorna, no se promete interrumpibilidad desde
Python: registrar timeout/respuesta incierta y solicitar únicamente parada
protegida. No matar manualmente, repetir ni crear otro lector.

El lector separa omisiones previas a Status de omisiones por cuota. Tras llenar
20 muestras puede terminar las consultas pendientes dentro del mismo plazo,
sin almacenar más. El cierre destruye suscripciones/clientes y contexto, no emite
HOLD, velocidad cero, armado ni desarmado. Sólo declara reader_closed después de
fsync/cierre del journal y recibo exclusivo 0600. Datos incompletos o errores de
escritura dejan rc=2/recibo ausente o incierto; no se declara captura completa.

5. Solicitar inmediatamente el cierre de ESA apertura, con monitor aún activo:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones_rover
```

Verificar cierre formal, destino CLOSED, monitor/monitor_exit real, procesos y
reservas posteriores. Ante bloqueo no forzar señales/guardas. Copiar originales,
trace, sockets, selection/launch/monitor/exit, configuración efectiva seleccionada
por el bridge y hashes a evidencia nueva con manifiesto. Un SUCCESS no sustituye
recibo ni cobertura; pérdida terminal se informa separada de ventanas utilizables.

6. Analizar copias offline, sin ROS ni conexiones:

```bash
.venv/bin/python -m tools.rover_passive_validation analyze-reader COPY/journal.jsonl --receipt COPY/journal.jsonl.receipt.json --trace COPY/trace.log --monitor COPY/monitor.json
.venv/bin/python -m tools.rover_passive_validation evaluate-transform DATASET_WITH_SOURCED_FIT_AND_HOLDOUT.json
```

El análisis exige monitor coherente de la misma sesión y ventana. Evaluar además
`analyze_series` sobre la serie completa con los tiempos de Status y la evidencia
de cierre, conservando pérdidas terminales. Ni registros GID coincidentes ni un
ajuste numérico actualizan gates. SYSID efectivo y GID→bridge podrían resolverse;
plugin→entidad, origen/precisión, incertidumbre vertical y efectos de comandos
pueden seguir pendientes aun con recepción y cierre correctos.

### Cómo seguirlo en VS Code

- `prepare_identity` produce copias/patch; `build_identity.sh` sólo compila.
- `selection.check_manifest`, `validate_sources`, `prepare_overlay` seleccionan
  artefactos antes del arranque; defaults y exclusión siguen en lifecycle.
- `monitor.Drain` conserva ambos prefijos bajo **el mismo** límite; `verify_bridge`
  observa maps y proceso, sin controles.
- `rover_identity_probe::Session`, `Query::poll`, `Retention::retain` y `Writer`
  explican contexto, lecturas, cuotas y persistencia. Es instrumentación diagnóstica.
- `read_journal`, `correlate_parameter`, `correlate_bridge`, `transport_routes` y
  `evaluate_transform` sólo analizan. No son el executor operativo ni habilitan
  movimiento. La falta de precisión o de asociación nunca se resuelve por bandera.

### Resultado de la única autorización posterior — 2026-10-26

Se consumió una apertura headless: f206c00d-b5fd-4ea9-87cf-53f4bbcf872b.
Start SUCCESS; captura omitida al fallar monitor; stop protegido SUCCESS.
Monitor INCOMPLETE/rc1, 59,125 s, sin agotar el timeout. No hubo lector ni llamadas
de parámetros. [Resultado y originales](../../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801/).
El precheck posterior está BLOCKED por este descriptor incompleto, aunque no hay
procesos/guardas actuales en las lecturas conservadas. No se reutilizó ni aplicó
la disposición de otro propietario. Corregir el helper no autoriza una reapertura.

Después del cierre se amplió el diagnóstico de PermissionError con relecturas de
stat. Sólo dos Z del mismo start_ticks resuelven una carrera; lo demás mantiene
UNKNOWN. El estado de los PID históricos sigue desconocido. Los helpers realmente
ejecutados están archivados con sus hashes; no se hacen pasar los nuevos por ellos.

Para plugin→entidad se preparó una copia instrumentada **sin desplegar**:

```bash
.venv/bin/python -m tools.rover_xrce_trace.prepare_model /home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot_gazebo /tmp/tfg-model-source-NEW
# Sólo build en contenedor acreditado activo; no instalar, cargar ni ejecutar:
cmake -S /tmp/tfg-model-source-NEW -B /tmp/tfg-model-build-NEW -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/tfg-model-build-NEW --parallel 2
```

La receta fija hashes originales, conserva fuentes externas y contiene un único
sendto funcional. No sustituye el lector 92884e6b... ni el manifest identity /2.
La variante compilada está en `/tmp/tfg-model-build-20261026-5379-b/`, hash de
biblioteca `b4be39e9daf2cc8927b64bc1356c2eaace1ae5d927b23dce10701100fe1129a4`.
Su selección por lifecycle **queda pendiente** de revisión explícita; no hay una
vía manual autorizada de carga. `TFG_MODEL_TRACE=1` es opt-in diagnóstico, no
permiso de control, y no se activó en este ensayo.

Los registros ECM/WorldPose/FDM ofrecen una vía operativa viable sin exigir
identidad del publicador por muestra a una API Gazebo que no la expone. Alcance,
modelo de confianza y condiciones pendientes están en
[la matriz actualizada](../../docs/rover-source-correlation.md#plugin--entidad-sin-exigir-un-identificador-inexistente).
En VS Code: `prepare_model.prepare` fija dónde se instrumenta; `model_trace::state`
lee los componentes reales; `model_trace::sent` observa el socket existente;
`model_records`/`assess_model_source` validan contextos sin habilitar gates.


### Integración offline revisada — 2026-10-26, posterior a 5379b30c

Esta sección sustituye las instrucciones de preparación anteriores para la
**variante nueva /3**; no cambia lo que ejecutó el ensayo histórico. No hubo
apertura, captura, disposición aplicada ni movimiento en esta tanda.
[Resultados y hashes de la revisión](../../simulation/ros2_gazebo/results/rover_integration_offline_2026_10_26/f71b76ab-7fcc-4e1c-b613-31f22bcbae62/).

**Causa acreditada del monitor.** La ruta `run → agents → /proc/*/exe`
exigía conocer ejecutables ajenos para vigilar su agente. El ensayo conservó
PermissionError sobre 5418 y5617; no permite saber si eran zombis. La corrección
no los reclasifica. `launch_candidates` descubre roles sólo en los hijos del
launch exacto por cmdline/stat; exe/maps/ascendencia se comprueban para los
roles conocidos y después se supervisan esos mismos PID/start_ticks/boot. No
adopta reemplazos ni ignora permisos sobre roles esenciales. La búsqueda global
de **todos los propietarios de sockets**, con dos barridas, sigue independiente
y sin filtrar propietarios por nombre. No se afirma unicidad global de agentes.

`capture_window(... passive_measurement=True)` y `session_window` admiten una
medición pasiva con supervisión esencial acreditada aunque la propiedad de un
socket sea UNKNOWN/parcial: precisamente se intenta medirla. Conservan los
motivos y presupuestos. El modo estricto anterior sigue por defecto. Esto no
relaja identidad, ejecución o movimiento. Permisos sobre agente/bridge/modelo,
reinicio, pérdida de identidad, trace truncada o presupuesto desconocido siguen
impidiendo el lector. `execute_once` conserva el intento, llama una vez a los
puertos start/admisión/lector/stop/post y no reanuda tras respuesta perdida.
Los tests usan el monitor, serialización, admisión y clasificador reales, /proc
falso y un lector sintético: ninguna recepción real nueva.

**Canales de cierre.** `SEPARATE_CHANNELS_V2` registra por separado
`core_capture_complete` y `socket_capture_complete`; `capture_complete` exige
ambos. CLOSED con core=true no convierte la pérdida terminal de contexto del
inventario en cobertura completa: el retorno sigue1 si sockets=false. El lector
puede analizar el prefijo útil coherente, pero el precheck histórico continúa
BLOCKED mientras falte una disposición revisada. Ni stopSUCCESS ni un PID
ausente acreditan por sí solos una captura completa.

**Disposición V2 sin casos nuevos por UUID.** `verified_closure_archive` exige
manifiesto íntegro (bytes/tamaños/permisos), descriptor/selección/operaciones
exactos, cleanup protegido enlazado al launch, respuesta y retorno de stop,
inventario independiente posterior, guardas y comprobaciones de restricciones,
y cronología posterior al cierre. El scope fija esos originales; no congela
lecturas actuales. apply vuelve a leer bajo exclusión ejecución→registro,
rechaza cambios de contexto, deja claim durable antes de persistir y no reintenta
un parcial. query es lectura/idempotencia, no una autorización de apertura.
Las disposiciones antiguas conservan sus reglas y hashes.

El único dry-run actual de esta tanda, terminado a2026-10-26T21:19:58UTC,
fue DRY_RUN_ELIGIBLE, propietario `f206c00d-b5fd-4ea9-87cf-53f4bbcf872b`,
monitor histórico INCOMPLETE, procesos/restricciones/guardas actuales libres en
esa lectura. ScopeSHA-256:
`c2fc99db11decea614d00e6936c7eee0e1556c5d4399c3b56c0c9dfd7825160e`.
No se aplicó: requiere revisión y autorización aparte. Invocación pendiente:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition apply-reviewed --owner f206c00d-b5fd-4ea9-87cf-53f4bbcf872b --evidence simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801/ --scope-sha256 c2fc99db11decea614d00e6936c7eee0e1556c5d4399c3b56c0c9dfd7825160e --authorization 'AUTHORIZE_DIAGNOSTIC_DISPOSITION f206c00d-b5fd-4ea9-87cf-53f4bbcf872b c2fc99db11decea614d00e6936c7eee0e1556c5d4399c3b56c0c9dfd7825160e'
```

Es declaración local registrada, **no autenticación de Joel**. No sustituir el
digest si cambia la evidencia. La auditoría separada no modifica descriptor,
recibos, monitor INCOMPLETE, reservas ni autorizaciones de vehículo. Un futuro
precheck volverá a leer el estado actual bajo exclusión y exigirá un permiso
independiente de apertura. DRY_RUN_ELIGIBLE no es SATISFIED ni consentimiento.

**Selector completo /3, explícito y apagado por defecto.**
`diagnostic-agent.model.json` fija el par agente/biblioteca /2 y el bridge
anteriores más `/tmp/tfg-model-integrated-build-f71b76ab/libTFGArduPilotIdentity.so`,
SHA-256 `bc94c8367974854e1f48dea15f376284aae57cf57edbeee7624015f7afe82562`.
La nueva copia compiló/enlazó contra gz-sim8/ROS instalados. ELF/source hashes se
revalidaron; no se cargó, instaló ni ejecutó. El overlay ofrece **un solo slot**
`lib/libArduPilotPlugin.so`, que resuelve el filename del SDF existente; no añade
otro plugin ni modifica SDF. configure antepone esa ruta sólo en /3. El monitor
exige el SO exacto en maps y rechaza librerías normales simultáneas, entidades
con instancias duplicadas, contextos distintos y sustitución del proceso.
Normal y variantes /1-/2 conservan la selección anterior y no activan modelo.

`reader.model.json` fija una nueva selección, sin sustituir el lector92884e6b:
`/tmp/tfg-reader-integrated-build-f71b76ab/rover_identity_probe`, SHA-256
`893cc61238bb3573d65a28f9ba8d0806e5349049bf69f7d732e73a9dfd1b3b2e`.
Compiló y enlazó contra headers/tipos/RMW reales; **no se ejecutó**. El formato
`rover-passive-validation/1` de este lector de fuentes es distinto del journal
/3 de odometría histórico. `read_journal`/`analyze_reader` son sus lectores.

**Una sola medición futura propuesta, NO AUTORIZADA.** Después de revisar la
disposición y autorizar separadamente la sesión:

1. Revalidar exclusión, entorno activo exacto y su ejecución, procesos/sesiones,
   restricciones, reservas, fuentes y hashes de ambos manifests. Desplegar sólo
   helpers actuales por el mecanismo protegido existente; no reconstruir al
   encontrar un hash distinto.
2. Abrir una vez por lifecycle `start --headless --profile two_drones_rover
   --diagnostic-agent-manifest tools/rover_xrce_trace/diagnostic-agent.model.json`.
   Es infraestructura pasiva; no GUI ni servicios/control de vehículos. Verificar
   agente único del subtree, SO/bridge/modelo exactos y monitor OBSERVING.
3. Ejecutar admisión fresca con `session_window` y luego una vez el lector fijado:
   `rover_identity_probe --session-id <NUEVO_OWNER> --output <DIRECTORIO_PRIVADO_NUEVO>/journal.jsonl`.
   El driver `passive_trial.LocalPorts` conserva las formas exactas, hashes,
   directorio0700 y salida/retorno; no tiene CLI que arranque al importarse.
   Esta variante incluye exclusivamente el GetParameters de lectura ya preparado
   para MAV_SYSID, no controles ni servicios de armado/modo. Eso deberá constar
   expresamente en la futura autorización de recepción.
4. Pedir stop protegido inmediatamente después del lector, dentro de la ventana;
   conservar journal/recibo/stderr/rc, trace, sockets, monitor/monitor_exit real,
   logs y postlecturas. No ampliar ni repetir por cobertura insuficiente. Una
   respuesta perdida implica consulta/diagnóstico, no volver a arrancar.
5. Analizar exclusivamente la misma sesión: RPC identidad exacta→SYSID efectivo;
   Status/GID→writer→cliente/generación→peer→propietarios completos;
   odom/GID→bridge con maps/config; ECM plugin→entidad→pose/FDM y socket real.
   Rechazar mezclas, ambigüedades y clocks no comparables. Correlación operativa
   en namespace controlado, no autenticación criptográfica ni identidad global.

**Cuotas observables y límites sin aumentar.** 20 muestras/120s siguen fijos:
1Status +3odom +2navsat×3vehículos +2geopose×3 +4Pose_V=20.
Todo salvo Status se retiene DESPUÉS del primer Status. Las muestras por topic
se separan al menos0,5s de su sello de origen; se cuentan descartes por cuota,
espaciado y retrocesos. Pose_V cubre como mínimo1,5s de simulación si completa sus
cuatro muestras. No se infiere cadencia/pérdida del flujo entero de esta selección.
El reader crea un marcador privado y exclusivo de sesión tras el primer Status.
El plugin conserva metadata de instanciación, y DESPUÉS del marcador toma3estados
separados0,5s de simulación más sus sendto reales. Antes, el prefijo de dos estados
al comienzo del arranque no garantizaba solape: ése era un defecto de diseño.
Con tres entidades y dos plugins relevantes cada una:3config+6attached+9pose+
9send=27filas esperadas, dentro de32×4096B; usa el mismo trace512filas/2MiB.
Cualquier duplicado, exceso o registro incompleto mantiene UNKNOWN/BLOCKED.

En admisión se reservan hasta41observaciones futuras de sockets (200s/5s+1),
256KiB/fila, más512KiB de lector y2MiB de trace:12,75MiB nuevos como peor caso.
El diario previo debe caber en los3,25MiB restantes y quedar al menos41de64slots.
Monitor600s, sockets2048lecturas/256KiB/64observaciones/16MiB y consulta0,75s no
cambian. Si tarda demasiado en aparecer Status, el lector cierra por120s sin
prometer los demás streams, y hay que cerrar antes de agotar el monitor.

La cuota permite observar dos referencias aéreas y una referencia rover como
holdout, con pares geodésicos, Pose_V y modelo; **no garantiza que publiquen, que
sus clocks coincidan, su precisión ni que una topología quieta observe todos
los grados de libertad**. Si faltan origen/resolución/cota de error o alineación
con las poses reales del plugin, la transformación sigue UNKNOWN. No rellenar
por nombre de entidad, spawn o una tolerancia arbitraria. Incluso todos los
campos presentes no habilitan transporte físico: faltan políticas dinámicas,
pendiente, parada atribuida y ensayo explícito de movimiento.

En VS Code, seguir `launch_candidates → verify_agent/verify_bridge/
verify_model_library → run`, `capture_window → session_window → execute_once`,
y `classify_last_session → dry_run → assess_disposition`. En C++, `Retention`
selecciona muestras; `Writer::request_model` sincroniza el prefijo diagnóstico;
`model_trace::state/sent` observa la pose y el envío reales. Esta instrumentación
no pertenece al executor de movimiento; lifecycle/exclusión mantienen su contrato.


### Ejecución única /3 y correcciones posteriores — 2026-10-26

[Resultado independiente por requisito](../../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/requirement-matrix.json).
La preparación f71b76ab se verificó sin diferencias. El contenedor ya estaba
activo; no se consumió reactivación. Se aplicó UNA disposición f206c00d con scope
c2fc99db11decea614d00e6936c7eee0e1556c5d4399c3b56c0c9dfd7825160e.
Auditoría DISPOSED_DIAGNOSTICALLY_INCOMPLETE, intentSHA-256
1faacd736d806aa3ee85f3b8eb9b41423accfb8ee7a3897651e162965a22d77a.
Originales/reservas intactos; monitor histórico INCOMPLETE. La consulta posterior
verificó la auditoría; el precheck fresco consumió sólo esa disposición y dio
SATISFIED. No se reutiliza para el descriptor nuevo.

Apertura headless `e837942d-61b0-428e-8505-ef6ddca38037` SUCCESS;
lector893cc612... una vez,120s propios, retorno0 y stderr vacío, footer y recibo
coherentes. Conservó14/20muestras de6/9streams:1Status,3odom,2geopose×3 y4Pose_V.
Los tres NavSat no dieron muestras en la ventana, aunque la traza sí conserva
writers comprometidos correctamente tipados para rt/ap/v1|v2|v3/navsat. No se
atribuyen a topic incorrecto, QoS, cadencia o carga sin datos adicionales.

El modelo emitió27registros; el marker privado0600 contiene el owner exacto.
Primer Status en sello2,348952s; las poses reales se tomaron en2,351/2,851/3,351s,
después del marker, con sus9resultados sendto. Se comprobó maps del SO seleccionado
sin carga simultánea del normal y una instancia por entidad11/67/181. El verificador
consume ahora los IDs exactos del catálogo y Pose_V, no una asociación por nombre
o spawn. Mantiene desconocidos el receptor SITL del FDM y el default odom_topic.

La parada `4fa9de1b-6234-4ba4-8980-dc1ddedd52af` fue SUCCESS a21:59:52,959991UTC,
con cleanup sin errores/remaining/auxiliares. El monitor acabó a21:59:41UTC,
INCOMPLETE/retorno1 realmente observado, error único «Model server exit not
observed by monitor». Cerró antes de la escalada protegida SIGTERM/SIGKILL del
servidor. No fue agotamiento de600s: duró183,946s. Sigue incompleto; no se ha
modificado el recibo ni convertido el cierre de infraestructura en captura completa.
La lectura posterior a22:05:22UTC encontró guards={}, restriction=null y
owned/ambiguous/agents/host_processes vacíos. El precheck de21:59:53 quedó BLOCKED
por ese historial y por fresh_observation=false (lectura superó3s); no se repitió
para obtener elegibilidad. La lectura posterior es inventario de cierre, no token
de arranque ni afirmación indefinida sobre el estado actual.

**Hallazgo de sockets y arreglo exclusivamente posterior.** Se guardaron27filas,
25REPEATED_READS_AGREE y2pérdidas terminales de contexto,243853B; máximo9529B/fila y
26eventos de lectura frente a2048. No hubo agotamiento de presupuesto. Las25filas
conservaron30endpoints y cero inodes relevantes. El helper realmente ejecutado
está en executed-helpers/socket_inventory.py, hash3244aeca...; `Reader.get`
hacía un solo os.read. La API permite un fragmento corto y con líneas completas
sin EOF. Por ello **no quedó probada la lectura completa de las tablas**, aunque
las filas lleven su etiqueta histórica. El tail real no se puede reconstruir y
no se afirma que necesariamente contuviera el peer.

El helper nuevo lee hasta EOF, conserva el mismo límite por archivo,2048lecturas,
0,25s cooperativos y0,75s exteriores. Cuenta cada read adicional contra el mismo
presupuesto; si no llega al EOF, queda INCOMPLETE. `bytes_to_eof` y
`table_scope_*.read_completion` dejan su procedencia comprobable. La regresión
reproduce un primer fragmento legal con los30endpoints observados, más inodes y
un tail **sintéticos**, y recorre captura→archivo→lector→asociación. No se ejecutó
este arreglo en el ensayo, no se desplegó después y no se cambió ningún binario.
Los hashes de helpers de f71b76ab ya no describen el arreglo nuevo: una futura
operación requiere su revisión explícita; no sustituir hashes silenciosamente.

**Análisis de prefijo supervisado, separado del cierre.** analyze_reader permanece
estricto por defecto. El parámetro offline --closure-evidence permite analizar
este caso sólo con cleanup protegido independiente, target CLOSED, observación
activa de las mismas bibliotecas/PID/boot y error final único de salida del modelo.
Su resultado conserva analysis_scope=SUPERVISED_PREFIX_WITH_UNOBSERVED_TERMINAL_MODEL_EXIT,
capture_complete=false, identidad/movimientoBLOCKED. No afecta al clasificador de
lifecycle ni dispone historiales. Cualquier otra pérdida/error/contexto se rechaza.

```bash
.venv/bin/python -m tools.rover_passive_validation analyze-reader simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/reader/journal.jsonl --receipt simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/reader/journal.jsonl.receipt.json --trace simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/container-capture/trace.log --monitor simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/container-capture/monitor.json --closure-evidence simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/closure-analysis-input.json
```

No se hace otra apertura. Próximo paso offline: resolver el contrato request/
related-sample/reply y el GUID nulo del cliente, y acreditar el default del
OdometryPublisher. El lector recibió SYSID3, pero el nativeRPC requestGUID y
replyGUID difieren; sequence1 no identifica al solicitante. La lectura EOF debe
revisarse antes de autorizar una nueva prueba. No se habilitó movimiento y no se
exige transformar POI_A1 para un futuro pulso corporal que no lo utiliza.

### Correcciones posteriores a e837942d — 2026-10-27, sólo offline

[Conclusiones y contrato de cada enlace](../../docs/rover-source-correlation.md#revisión-offline-de-enlaces-e837942d--2026-10-27).
[Evidencia derivada, fuentes y medidas](../../simulation/ros2_gazebo/results/rover_identity_links_offline_2026_10_27/6d8a775a-7ce5-4a6a-bd08-ba8918fdcdba/README.md).
No se aplicó disposición, se abrió sesión, se ejecutó lector ni se desplegaron
helpers en esta revisión. El historial e837942d sigue INCOMPLETE y no se dispone
por esta documentación. Los hashes de f71b76ab siguen describiendo sus originales,
**no estas nuevas fuentes**.

El verificador ya consume los logs originales que resuelven el topic omitido de
OdometryPublisher: `/model/rover1/odometry`, entidad67, bridge atribuido por GID.
La frecuencia omitida no equivale a ruta desconocida; las muestras seleccionadas
no estiman su frecuencia. Tampoco acreditan twist no nulo, reposo o pendiente.

La regla antigua de unir el GUID legacy del cliente al campo post-write del
agente queda retirada. Se recupera el contexto real del replier, pero SYSID=3
permanece recibido sin atribución. Los templates nuevos guardan la identidad
pre-write por valor y las identidades post-write por separado; su preparación
sobre fuentes fijadas y compilación `-S` con headers reales pasaron. **No** hubo
enlace nuevo del agente/wrapper ni ejecución. La fuente exacta del cliente RMW y
un hook por respuesta recibida siguen pendientes: el contrato sintético de
`correlate_rpc_v2` no convierte la API pública actual en una fuente nativa.

SocketRecorder busca la unión de peer XRCE validado y destinos FDM efectivamente
enviados por el plugin atribuido; lee `/proc` hasta EOF y busca todos los owners
dos veces. La observación del receptor FDM se compara con el SITL de la rama XRCE
en la misma fila. El analizador conserva UNKNOWN si faltan namespace, contexto,
EOF, evidencia de localidad o unicidad. UDP conectado debe admitir el emisor del
plugin; varios owners o dual-stack no se reducen a uno. Propiedad de socket no
equivale a recepción del payload. Los ceros históricos no se reinterpretan como
una búsqueda FDM ni como ausencia probada.

El fixture de reconstrucción retenido tras la tanda pasó con1182eventos lógicos,
1292llamadas físicas/146972B: margen756/115172B ante2048/256KiB. El coste no es
latencia real; FDM puede añadir sockets/owners y contexto, no sólo bytes.
1280/160KiB no cubre1292llamadas;64filas×160KiB superaban el antiguo8MiB.
No se amplió el contrato actual2048/256KiB/64/16MiB. Tampoco se omiten lecturas
necesarias para hacerlo pasar. Tabla vacía, error, endpoint en un fragmento final,
truncamiento y presupuestos están cubiertos por regresiones offline.

**Coordinación de parada nueva.** stop_sim_backend propaga el close target exacto
al supervisor. `begin_diagnostic_closure` verifica descriptor/puntero/identidades
y registra closure-request; retiene el monitor y su padre por PID/ticks/boot sin
enviarles las señales destinadas a infraestructura. Cleanup conserva12+5+3=20s
totales y publica cleanup-finished con el resultado físico. El monitor continúa
drenando, observa salidas y finaliza; el padre registra el wait real. No se suma
otra espera de20s. El monitor conserva600s; una interrupción, owner perdido,
observación denegada, servidor persistente o fallo de cierre sigue incompleto.
Un error de coordinación diagnóstica se reporta separado del resultado físico.
El protocolo se selecciona sólo si el monitor declara
`DEFERRED_OBSERVER_SHUTDOWN_V1`; los overlays antiguos no se actualizan en caliente.

La causa e837942d está reproducida: el protocolo antiguo señalaba al monitor al
comenzar SIGINT y éste esperaba10s; cleanup terminó después al escalar el servidor.
Su INCOMPLETE/rc1 es correcto respecto a su ventana, aunque faltaba coordinarla.
No fue un timeout600s ni una prueba de que cleanup SUCCESS completase la captura.
El retorno histórico sí existe en monitor_exit.json; no se reconstruyó otro.

Reproducción **offline**, sin invocar un lector operativo (desde la raíz):

```bash
PYTHONPATH=. .venv/bin/python simulation/ros2_gazebo/results/rover_identity_links_offline_2026_10_27/6d8a775a-7ce5-4a6a-bd08-ba8918fdcdba/reproduce.py
```

La CLI existente `analyze-reader` admite ahora `--launch-log` y `--sockets` para
consumir esos archivos de la misma sesión. No cambia el precheck ni los gates.
El informe conserva capture_complete=false, pérdidas terminales y movimientoBLOCKED.

Antes de solicitar otra sesión: resolver/revisar el hook nativo de respuesta del
cliente, compilar el agente modificado y fijar sus hashes nuevos separadamente;
revisar los helpers actuales (monitor/socket/cleanup) y sus hashes sin sustituir
los autorizados antes. El cambio RPC C++ **sí** exige otro build; el EOF, inventario
y protocolo Python/Bash por sí solos no lo exigen. El colector no cambió.

Los datos mínimos de una futura medición, con autorización independiente, son:
identidades nativas request/response del cliente; destinos FDM reales y búsquedas
EOF de peer/FDM con mismos PID/ticks/boot/ns; cobertura hasta closure-request,
cleanup-finished, monitor final y wait del padre. Status debe recibirse dentro de
las ventanas útiles, con margen de cierre reservado; cualquier pérdida de
supervisión/presupuesto obliga a omitir la recepción y cerrar por lifecycle.
No repetir el default de odometría ya resuelto ni programar una apertura desde
el analizador. Ninguno de estos datos concede movimiento o SYSID por analogía.

En VS Code: `inspect_rpc_exchange/correlate_rpc_v2`,
`correlate_odometry_model → analyze_reader`,
`SocketRecorder.sample → collect/Reader.get → analyze_series/match_fdm_receiver`,
`shutdown → begin_diagnostic_closure/finish_diagnostic_closure → managed_closure/run
→ supervise`. Los primeros son diagnóstico pasivo/offline; shutdown es código
operativo protegido. No se conectó instrumentación a control de vehículos.

**Contraste adicional con the multi-agent subsystem, 2026-10-27.** El informe actual separa bruto65185
y normalizado derivado41470; se verificó la fuente sin_port/get_port fijada y el
ELF/maps conservado de e837942d. La conversión acreditada no es un endpoint leído
en el kernel. `match_peer` informa raw_recorded, transformación, normalized_derived
y kernel_table_matches por separado. Una coincidencia retenida sin EOF en ambas
tablas deja TABLE_COMPLETENESS_NOT_ESTABLISHED: no acredita unicidad. No se probó
otra interpretación para buscar coincidencias ni se reescribieron históricos.
Los informes sellados de la tanda anterior no se regeneraron con este código.
La [actualización de la matriz](../../docs/rover-source-correlation.md#contraste-de-puerto-y-revisión-independiente--2026-10-27)
explica también el default ya resuelto, GUIDED antes del pulso/HOLD al parar y
las barreras vigentes del transporte físico. No hubo otra operación ni build.

## Cierre offline del transporte — 2026-10-27

La selección/persistencia final y su dry-run están documentados en
[el cierre verificable](../../docs/checkpoints/rover-transport-2026-10-27-offline/README.md).
Los tres ELF recuperados coinciden con los hashes registrados, pero falta
procedencia sellada completa del build. `reader.transport.json` queda preparado
con `prepared=false`: el driver lo rechaza antes de abrir. No se seleccionó ni
se ejecutó la variante. Identidad completa y movimiento siguen BLOCKED.
