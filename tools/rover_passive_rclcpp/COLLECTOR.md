# Standalone passive collector — diagnostic reception, identity BLOCKED

Current status (2026-10-22): initial partial captures are preserved; a later
explicitly authorized reserved-stream trial received both streams with coherent
closure. See the final section; full identity and motion remain BLOCKED. No further run is authorized.
The preparation/build claims below are chronological records as of their dates.

Prepared offline on 2026-10-21. `collector.cpp` is independent source for a future
separately authorized collector. It is not built or installed by the project,
registered as a component, linked to lifecycle/Python worker/control/executor,
exposed through MCP, or used by a mission. No ready-to-run binary is provided.
It never publishes, calls a service, arms or commands a vehicle. During initial preparation no collector execution, ROS build/link or Docker query
was performed. A later authorized syntax-only check of this complete program
passed against real installed headers (recorded below); the collector has still
never been linked or executed.

## Explicit contract

The future program requires exactly these arguments, in this order:
`--output ABSOLUTE_NEW_FILE --max-samples N --duration-s SECONDS`.
This is an interface description, not permission to run it. No ROS argument,
remapping or parameter overrides are accepted from arguments. Limits are explicit:
2–10000 samples **total across both streams** and finite duration in (0,300] s.
The first limit reached stops collection. One high-rate topic can consume the
sample budget; if the other never appears the capture is incomplete. No implicit
warm-up, fixed sleep, retry, respawn, restart or attempt to obtain missing data.

The node uses an isolated Context and SingleThreadedExecutor. ROS-out publishing,
parameter services, parameter-event publishing and intra-process delivery are
disabled through public NodeOptions. The component's only application
subscriptions are `/ap/v3/status` and `/rover1/odometry`, BEST_EFFORT/VOLATILE,
depth 5. It does not use a simulated-time deadline or modify any existing node.

The deadline starts before output creation/ROS initialization. Normal polls use
remaining steady-clock time, at most 50 ms each. A separate wall-clock watchdog
exits **this collector process only** with rc=2 at the deadline, including if a
callback, graph lookup, write or cleanup is blocked. It sends no signals to
vehicles or other processes. Like any userspace watchdog it depends on OS thread
scheduling. It performs no last-second write or fabricated completion. Therefore
a duration-limited run may stop without a footer/receipt and must be treated as
UNCERTAIN; collecting fewer samples is never permission to repeat automatically.

## Output and provenance

The absolute output must not exist, including as a symlink. Its existing parent
must be owned by the caller and private (no group/other permission bits, normally
0700); no directory is created. Every path component is opened with no-follow
semantics. The new file is created exclusively with mode 0600 (or stricter due to
umask). Existing files are never appended to, overwritten, deleted or repaired.

JSONL consists of `start`, `sample`, and (if reached) `end`. Each append completes
positive partial writes and confirms fsync of file/directory; a write/fsync error
stops immediately, without retrying a failed record. Final fsync/close must also
succeed. Errors can leave a partial or even syntactically truncated last line:
preserve it and mark the capture uncertain. There is no resume path.

Each sample separates:

- Callback receipt: system Unix nanoseconds and process-local steady nanoseconds.
  These do not prove source age or comparability with another host/process.
- Header stamp and frame copied from the message. Status records vehicle_type,
  armed and flying; Odometry records child_frame_id. This is an **identity
  diagnostic subset**, not a full Status/Odometry dump or motion measurement.
- Raw message GID and RMW implementation identifier from **that MessageInfo**,
  their source label, availability state and from_intra_process. This is not a
  claim about the process's loaded RMW library/version or an authenticated
  publisher. Zero/missing/intra-process metadata stays UNKNOWN.
- Graph discovery candidates, their names/namespaces/endpoint GIDs, independent
  receipt and source. Even one matching candidate never supplies or verifies a
  sample's GID. Failed discovery leaves UNKNOWN and preserves the sample.

No attributed publisher identity is serialized. Strings are encoded reversibly
as byte escapes (`string_encoding=byte_escape_u00`): to recover original non-ASCII
UTF-8 bytes, decode U+0000..U+00FF back to bytes before interpreting UTF-8. Quotes,
control bytes and malformed UTF-8 cannot break JSON framing. GIDs are hex of the
raw storage array, meaningful only with implementation and capture context.

All records state BLOCKED, source_association_verified=false and
movement_authorized=false. Missing stream, invalid stamp, wrong Status vehicle
type, missing odometry frames or incomplete metadata/discovery prevent a positive
data-completeness receipt. They never authorize motion.

The file footer contains `capture_complete:null`: it cannot attest to its own
successful close. Only a final stdout receipt plus **rc=0** after confirmed
writes/close indicates `capture_state=DATA_RECORDED`, `capture_complete=true`.
This means only both streams were recorded without detected missing fields.
It still says BLOCKED and does not verify identities. rc=2, absent/truncated
receipt, interrupted cleanup or any ambiguity means UNCERTAIN, regardless of
previous sample records or a footer. A watchdog abort or signal may produce no
final stdout; absence is never success. No automated retry may follow.

## Verification and remaining work

Offline tests compile core/file helpers against explicit fake ROS headers and
run a helper harness with no ROS API execution. They exercise sample/time limits,
interruption, missing stream/metadata, escaped JSON, GID/graph separation,
write/fsync-style/close failures, exclusive 0600 files, private parent and symlink
rejection. A separate **syntax-only** compile of collector.cpp uses fake public
ROS declarations; the collector itself is never executed by tests.

Real ROS headers remain unavailable on the host. In the later authorized check,
the matching container was already running and provided the installed compiler
and headers; the complete program passed syntax-only compilation. Linking and
execution remain untested. A future separately authorized step must check linkage
and review the exact binary, environment and output location before any run.
Do not install dependencies or start services just to make that pass.

A later passive run still needs its own authorization, current environment/process
identity, and RMW identification. GID by sample does not demonstrate the complete
publisher↔XRCE session/SYSID↔SITL v3↔active bridge binary/YAML↔Gazebo model chain.
None of the preparation, compilation, data receipt or completeness states opens
the project's movement policy or changes its existing gates and reservations.


## Authorized real-header syntax check and added regressions — 2026-10-21

The container remained running and matched full ID
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`,
image `sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`
and engine `2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99`. Only metadata was queried
before invoking the compiler; no container or simulation was started/restarted.

`observer.hpp`, `collector_core.hpp`, `private_journal.hpp` and `collector.cpp`
were concatenated on stdin, removing only their mutual local include lines and
adding #line labels. The direct command was `docker exec -i <full-id>
/usr/bin/c++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -pthread -fsyntax-only
-x c++ <installed include roots> -`. Include roots were the same Humble roots
listed in the real Observer check in README.md plus the installed ardupilot_msgs
include directory. **rc=0, stdout/stderr empty.** No file, object or binary was
created in the container, no linking occurred, and the collector was not run.
This covers parsing/type-checking of the new Context, NodeOptions and executor
calls as well as Observer, the public MessageInfo callback, types and POSIX helper.
It does not verify ABI/linkage, middleware delivery, limits under real scheduling
or filesystem behavior, loaded RMW, or source/model association.

To reproduce source assembly in that compile-only recipe, replace its source
construction with the following and add `-pthread` to the compiler arguments:

```python
chunks = []
for name in ("observer.hpp", "collector_core.hpp", "private_journal.hpp", "collector.cpp"):
    text = (root / name).read_text()
    for local in ("observer.hpp", "collector_core.hpp", "private_journal.hpp"):
        text = text.replace('#include "' + local + '"', '')
    chunks.append('#line 1 "' + name + '"\n' + text)
source = '\n'.join(chunks)
```

Additional offline regressions cover late callbacks at the duration boundary,
zero GID, intra-process and missing RMW/graph metadata, plus the actual
PrivateJournal code with POSIX calls intercepted by deterministic fault injectors:
positive partial write, failure after partial bytes, first write failure, file/
parent fsync, final fsync/parent fsync and close failure. Partial files stay
unchanged; no failed record is retried and no completion is produced. These run
only stdlib/fake-ROS harnesses in temporary directories, **not the collector**.
The collector test module has 27 passing cases; the combined passive/identity
regression run has 79 passing cases. These counts overlap, not separate evidence.

## Future bounded reception (separate authorization required)

1. Authorize only a passive check with exact binary/hash, environment, new private
   output path and explicit sample/time limits. First inspect current container,
   processes and project restrictions read-only. Stop if identity differs, the
   environment is stopped, or restrictions/owners are uncertain; do not start,
   recover, reconcile or release anything to make this test possible.
2. Verify linkage separately, establish the actual loaded RMW and review the node
   options/no-control scope. Missing dependency or changed headers/binary blocks
   the attempt; do not install, change configuration or guess compatibility.
3. Only after that authorization, perform one bounded reception with the described
   arguments (for example 20 samples / 10 s in a reviewed, fresh output file).
   No repeat is implied if discovery or samples are absent. Preserve stdout,
   stderr, rc and partial output; do not use this source as a lifecycle command.
4. Stop on the first error, limit, incomplete metadata or interrupted run. Treat
   rc!=0, missing receipt, failed durability or a truncated record as UNCERTAIN.
   Even rc=0/DATA_RECORDED stays BLOCKED: it demonstrates at most reception of
   diagnostic fields with sample metadata, not publisher→XRCE/SYSID→SITL v3→
   effective bridge/model association. No movement, service or flight test follows.

## Standalone CMake build/link — 2026-10-22

The independent `CMakeLists.txt` adds only `rover_passive_collector`, using
`ament_cmake`, `rclcpp`, `ardupilot_msgs`, `nav_msgs` and Threads. It has no install,
autorun, lifecycle or control target. Configure and build in a **fresh temporary
build directory**, against the existing ROS installation; never run the binary
as a build check. No downloads or package installation are part of this target.

After the separately authorized read-only check, the documented container was
already active and matched the full ID, image and engine recorded above. Source
copies were placed only under `/tmp/tfg-rover-link-g9agzigc/src` in that container.
The reproducible configure/build commands in that environment are:

```bash
# SRC is a reviewed copy of this directory; BUILD is a new temporary build path.
# These are build commands, not permission to start a container or receive ROS.
CMAKE_PREFIX_PATH=/root/ardu_ws/install/ardupilot_msgs:/opt/ros/humble \
AMENT_PREFIX_PATH=/root/ardu_ws/install/ardupilot_msgs:/opt/ros/humble \
PYTHONPATH=/opt/ros/humble/local/lib/python3.10/dist-packages:/opt/ros/humble/lib/python3.10/site-packages \
cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build "$BUILD" --target rover_passive_collector --parallel 2
```

The first configure attempt lacked ROS's Python search path and failed importing
`ament_package`; no package was missing or installed. With the existing Python
package paths above, **configure rc=0 and compile/link rc=0**. The actual probe
also passed `-DPYTHON_EXECUTABLE=/usr/bin/python3`, which CMake warned was unused;
Python3 was discovered as `/usr/bin/python3` (3.10.12). The recipe omits that unused
option. Observed: GNU C++ 11.4.0, ament_cmake 1.3.14, rclcpp 16.0.19,
nav_msgs 4.9.2, ardupilot_msgs 0.0.0, default RMW selection rmw_fastrtps_cpp 6.2.10.
A CMake default is **not** a loaded runtime RMW observation.

Linked file (not executed):
`/tmp/tfg-rover-link-g9agzigc/build/rover_passive_collector`, SHA-256
`141f4882ff931f8eca1db7e1f486396b800cd5a4d010e97a71b249d8abdb32c5`.
Temporary paths may disappear. Rebuilds can have different hashes (debug paths,
toolchain); this is a repeatable build procedure, not a byte-reproducibility claim.
Host build transcript: `/tmp/tfg-rover-build-output.txt` (temporary, not historical
runtime evidence). No collector/node was run. Linking resolves build symbols but
does not demonstrate runtime library loading, middleware delivery or identity.
Tests with fake headers and the earlier real-header syntax check remain separate.

## Offline journal analysis and exact future invocation

`tools/rover_passive_journal.py` reads `tfg.rover.passive-capture/1` JSONL only;
there are no ROS imports or connections. It checks framing/duplicate keys,
start/end ordering, versions/limits, metadata, footer counts and safety fields.
It retains raw per-sample GID/RMW, original header timestamps, receipt clock values
and separate graph candidates. Topic counts/spans, GID changes and timestamp
regressions are diagnostics with **no cause assigned**. Byte-escaped strings retain
the journal's `byte_escape_u00` convention. Receipt monotonic spans are not source
age, time in motion, or comparable with header/host clocks.

A complete-looking footer cannot attest to close/fsync. Without the matching
external stdout receipt **and** rc=0 the analysis remains UNCERTAIN. Even a
consistent DATA_RECORDED result always has identity/movement BLOCKED. Receipt
association with that invocation must be preserved externally; the analyzer does
not authenticate it or infer it from matching counts. Matching graph GID never
credits source association. Partial bytes are read as-is, never repaired.

**Future reception requires separate authorization.** First inspect the current
container/engine/image, passive processes, relevant restrictions and loaded RMW
read-only. Stop on unknown/changed identity or uncertain restrictions; do not start
or recover the environment to make the check pass. Verify the reviewed binary
hash and library availability without running a collector as a probe. Use a fresh
0700 directory, a new output filename, explicit limits and exactly one invocation.
The following is the exact command pattern for a later authorized shell **inside
the already accredited ROS environment**, with reviewed absolute `BIN` and a fresh
absolute `OUT` path selected in that authorization:

```bash
umask 077
mkdir -m 700 -- "$OUT" || exit 1
"$BIN" --output "$OUT/journal.jsonl" --max-samples 20 --duration-s 10 \
  > "$OUT/receipt.json" 2> "$OUT/stderr.txt"
rc=$?
printf '%s\n' "$rc" > "$OUT/returncode.txt"
sha256sum -- "$BIN" "$OUT"/* > "$OUT/SHA256SUMS"
# Stop here on rc!=0, missing receipt/footer, write error or incomplete metadata.
# Preserve partial files; no repeat/restart is authorized by this procedure.
```

The watchdog can terminate at the duration boundary without footer/receipt; this
is UNCERTAIN. No cleanup, retry or automatic follow-on movement is allowed. Copy
files byte-for-byte for offline analysis and preserve their hashes. From this
repository, after choosing the copied paths, the read-only command is:

```bash
.venv/bin/python -m tools.rover_passive_journal "$JOURNAL" \
  --receipt "$RECEIPT" --returncode "$RC"
```

Exit 0 confirms only consistent recorded data plus the supplied successful
completion evidence; exit 2 means uncertainty. Missing/truncated/contradictory
records, either stream absent, zero/intra-process GID or missing metadata stop
the assessment. A successful passive capture would demonstrate actual reception
and per-sample MessageInfo availability in that run. It would still not establish
publisher↔XRCE session/SYSID↔SITL v3↔active bridge binary/YAML↔Gazebo model,
source authenticity, independent ground state or permission to move. Those
require separate public source/config/process evidence and review; no connection
to worker, executor, lifecycle, MCP or missions is introduced here.

Offline verification on 2026-10-22: **72 tests passed** in the selected journal,
collector and observer modules (37 reader cases, 27 collector cases, 8 observer
cases). The reader regressions include bytes emitted by the actual C++ serializer
inside a fake-ROS helper, not reception by the collector. Python AST and whitespace
checks, including new source/test/CMake files, passed. No full suite or operational
capture was run. The 198 pre-existing untracked simulation-result paths remain
outside this increment; no historical evidence was modified.

## First authorized reception and offline deadline correction — 2026-10-22

One protected GUI start, one collector invocation (20 samples / 10 s), and one
protected stop were performed. Exact evidence and original compiled sources:
[bd6e2715](../../simulation/ros2_gazebo/results/rover_passive_reception_2026_10_22/bd6e2715-878a-4d6f-8dde-b90438276b88/README.md).
The old binary recorded **10 odometry samples**, nonzero per-message GID with
`rmw_fastrtps_cpp`, `from_intra_process=false`, frames `odom` / `base_link`.
No Status sample was recorded by C++. No footer or final stdout receipt exists;
rc=2, stderr empty: capture UNCERTAIN, not DATA_RECORDED. The Python worker's later
Status snapshot is separate evidence, still without per-message GID, and does not
fill this journal's gap. Graph matching and bridge YAML/process evidence remain
separate, without crediting complete source/model identity. Joel reported no GUI
window; the launch log contains a rendering-window exception, without proving its
underlying cause or explaining missing Status. Stop succeeded; post-stop process
snapshot was clear, container active. No prearm/services or motion commands used.

Code inspection after closure found the old watchdog's relative deadline began
before ROS setup, while `collect` created another full relative interval after
setup. The observed empty receipt is compatible with hard-watchdog termination;
there is no captured watchdog reason, so that is not asserted as a proven sole
cause. The offset is independently reproducible offline and now corrected:
`capture_deadlines` shares the original steady-clock budget; collection ends up
to 50 ms (10% for very short budgets) **inside** that same duration to allow normal
finalization. `DeadlineGuard` waits until the absolute original deadline, so thread
scheduling cannot renew it. The hard cap is not increased; blocked fsync/cleanup
can still exhaust it and must remain uncertain. Setup consuming the collection
window yields no polls or renewed duration. No fixed warm-up/sleep was added.

A deterministic fake-ROS regression checks delayed setup, a setup-exhausted
window, normal durable finalization within the cap and small durations. Selected
observer/collector/journal/deadline tests: **73 passed**. Syntax of the modified
program was checked with fake public ROS declarations by the existing tests.
This corrected source has **not** been rebuilt/linked against real ROS or executed;
the earlier real link and actual capture used the preserved old sources/hash.
Any future build/reception needs separate authorization; this attempt was not
repeated. Source identity and motion remain BLOCKED.

## Shared-deadline real link and Status review — 2026-10-22 (later)

The corrected source now passed real Humble compile/link in the already active,
identity-matched container, without running the binary. New path
`/tmp/tfg-rover-deadline-link-ju21k1sq/build/rover_passive_collector`, SHA-256
`995d1bc573d4057209b27495b1192267057a5206b03d1aebf054ce81f5f703a6`.
The earlier “not rebuilt” statements describe the previous phase only; no new
capture occurred. See [Status follow-up](../../docs/rover-passive-status-followup.md)
for separate build sources/logs, local AP_DDS cadence/clock evidence, precise
window comparison, unbalanced-cap regression and proposed unchanged 20/10 trial.
The original 120-entry evidence is untouched. A larger duration/quota change is
not implemented or implicitly authorized. Missing-stream normal closure is tested;
a blocked hard-timeout path remains uncertain. Identity/movement stay BLOCKED.

## Opt-in reserved-stream diagnostic — 2026-10-22 (later)

`--reserve-streams` selects journal `tfg.rover.passive-capture/2`; without the flag
the previous global-cap behavior/schema v1 remains. Both modes keep the same two
subscriptions and requested BEST_EFFORT/VOLATILE/depth-5 QoS. Duration and total
stored sample limits remain explicit. The authorized exploratory run used 20
stored samples / **120 wall seconds maximum**, not a guaranteed publish period or
performance benchmark. The quota does not extend that shared hard deadline.

While Status has not been stored, at most N-1 odometry samples are stored; while
odometry is missing the converse holds. Once both have been stored, the ordinary
total cap applies. Quota-excluded callbacks increment `omitted_status_quota` or
`omitted_odometry_quota`, without being serialized as sample records or counted
as stored samples. Footer and stdout receipt carry those counters; missing footer
means unknown final counters, not zero. Callbacks rejected at/after the deadline
are not claimed as quota omissions or a count of network messages/losses.

A separate `discovery` record per topic is written before the footer via public
`Node.get_publishers_info_by_topic`, even when no message was received for that
topic. Candidate GIDs, topic types and public endpoint QoS are distinct from
per-message GID. QoS preserves RMW enum integers for reliability/durability/history
and reported depth; other policies are explicitly NOT_CAPTURED. Unavailable
fields stay null/UNKNOWN. Discovery never creates a sample, fills coverage or
credits identity. Discovery/write stalls still face the original hard cap.
The offline reader supports both schema versions, validates reserved capacity,
footer/receipt quota counts and keeps discovery separate.

Tests: **79 passed** with fake ROS/helpers, including delayed/missing Status,
symmetric reservation, exact omitted counts, explicit incomplete footer, separate
discovery, public type/QoS metadata and schema/counter contradictions. The final
source compiled/linked against real installed Humble dependencies, then underwent
exactly one authorized reception. An intermediate build with graph metadata only
was never executed and is retained separately; there was no trial retry.

Final binary SHA-256:
`43d5b5eb4d13d78ef83d60f4b9eb6fa9868111d8efefe2d6c8fe373866f7c58c`.
Actual command:

```text
/tmp/tfg-rover-quota-link-12wwmnu4/build/rover_passive_collector --output /tmp/tfg_rover_capture_40e8c751-6d70-4280-b94b-b1512e1e2802/journal.jsonl --max-samples 20 --duration-s 120 --reserve-streams
```

Result: **1 Status + 19 odometry**, rc=0, coherent SAMPLE_LIMIT footer and
DATA_RECORDED receipt, stderr empty; about 16.872 s wrapper wall time. Both
per-message GIDs and rmw_fastrtps_cpp identifiers were captured. Omissions: **0**
for each stream, so this real run does not establish that quota reservation was
necessary. Status was the third stored sample, about 0.235 s after the first
stored C++ sample; this is not a measured initialization or whole-window latency.
No counterfactual claim about why earlier windows lacked Status is made.

Public graph offered Status RELIABLE/TRANSIENT_LOCAL, odometry RELIABLE/VOLATILE;
both reported history UNKNOWN and depth 0. The preserved installed `rmw/types.h`
is the enum interpretation source. Reported 0 with unknown history is **not** proof
of effective queue depth, and source defaults are not substituted for discovery.
Identity remains BLOCKED: graph matches do not certify XRCE/SYSID/SITL/bridge/model.
No movement/control/lifecycle/MCP integration was added. Protected start/stop both
succeeded; post-stop process/guard snapshot clear, container active. Joel's GUI
confirmation is separate human evidence. Old manifests were reverified unchanged.

[Exact evidence](../../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/README.md).
No additional run is authorized by this documentation.

Post-trial contract check: reserved mode now explicitly rejects requested maxima
above 20 before node initialization; legacy mode retains its prior bound. The
actual authorized run already requested 20. This final input-validation change
and reader bound were tested offline (79 passing tests, latest 11.32 s) and
compiled/linked against real ROS, **without another reception**. The unexecuted
final-validation binary is `/tmp/tfg-rover-quota-cap-link-fefyp58g/build/rover_passive_collector`,
SHA-256 `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93`.
`post_trial_cap_build/` preserves its separate sources/logs. The actual reception
claims above remain scoped to executed hash `43d5b5eb...`, not this later binary.

## Formato `/3`: campos de odometría opcionales — 25/10/2026

`--odometry-fields` es una opción explícita. Va después de `--reserve-streams` si se usan las dos.
Con ella, cada muestra de `/rover1/odometry` conserva la pose, la orientación, el twist y las dos
covarianzas tal como llegan en `nav_msgs/Odometry`. Los NaN e infinitos se escriben como `null` y
se listan en `nonfinite`; nunca se rellenan con cero. El esquema es `tfg.rover.passive-capture/3`.

Sin la opción, la salida es byte a byte idéntica a la anterior. El GID por muestra, los
metadatos, los límites y las banderas `BLOCKED` no cambian. Las unidades y los marcos no se
validan, y ninguna pose se atribuye a un modelo.

Build aislado y no ejecutado: `.../build/rover_passive_collector`, SHA-256
`637f2c3e3475983146b9891a058760cc6ece0ae6ea22e37d2484cd7f46e4d464`. El binario `94c0a9dd…` y el
manifest del selector no cambian.

Tamaños, fuentes, hashes, receta y traspaso:
[evidencia del build](../../simulation/ros2_gazebo/results/rover_passive_odometry_fields_build_2026_10_25/README.md).
