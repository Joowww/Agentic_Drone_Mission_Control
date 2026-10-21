# Standalone passive collector — NOT RUN / NOT AUTHORIZED TO RUN

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
