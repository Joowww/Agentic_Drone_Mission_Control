# Status follow-up and next passive trial — 2026-10-22

**Prepared, not authorized to run by this document. Identity and movement BLOCKED.**
No second start or reception was performed in this follow-up. The original
[120-entry evidence](../simulation/ros2_gazebo/results/rover_passive_reception_2026_10_22/bd6e2715-878a-4d6f-8dde-b90438276b88/README.md)
is unchanged; every size/SHA-256 was reverified. New build and analysis records:
[48329700](../simulation/ros2_gazebo/results/rover_passive_followup_2026_10_22/48329700-a0ed-49fc-956c-25be19815f65/README.md).

## Corrected binary: real compile/link, no execution

The already running container, full ID/image/engine identical to the documented
environment, was revalidated. CMake configure and compile/link **both rc=0**, with
GNU 11.4.0 and existing Humble dependencies. No installations, nodes, simulation,
services or collector execution. `build_sources/`, `source_hashes.json`, commands,
stdout/stderr and `binary.json` record this separate build.

- New corrected binary:
  `/tmp/tfg-rover-deadline-link-ju21k1sq/build/rover_passive_collector`.
- SHA-256: `995d1bc573d4057209b27495b1192267057a5206b03d1aebf054ce81f5f703a6`.
- Historical executed binary remains hash
  `141f4882ff931f8eca1db7e1f486396b800cd5a4d010e97a71b249d8abdb32c5`.

Real link is now verified for the shared-deadline correction. It still does not
verify library loading/delivery or successful closure under real ROS scheduling.
Temporary binaries may disappear; no fallback to the old hash is permitted.

## What the sources actually say about Status

Available reference sources are in
`/home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot/`; exact copies/hashes are in the new
`reference_sources/` and `reference_sources.json`. These are reference source,
**not proven provenance of the previously running ArduRover executable**.
Compile-time overrides and historical effective publishing intervals remain UNKNOWN.

- `libraries/AP_DDS/AP_DDS_Client.cpp:41–42,152`: default
  `AP_DDS_DELAY_STATUS_TOPIC_MS=100`, guarded with `#ifndef`.
- `:2025–2031`: check Status when `AP_HAL::millis64() - last_check > 100`.
- `:791–846`: changed tracked state can trigger publication at that check; when
  unchanged, publish when `timestamp - last_publish > 5*100`.
  The comment says 2 Hz, but the actual strict inequalities, update scheduling,
  XRCE state and transport determine delivery; this is not a 500 ms wall timer.
- `libraries/AP_HAL_SITL/system.cpp:207–223`: micros64 uses scheduler's stopped
  simulation clock when nonzero, otherwise monotonic elapsed; millis64 divides it.
  `SITL_State.cpp:284–285` updates that clock from simulation state.timestamp_us.
- Status header stamp is a **different selection**:
  `AP_DDS_Client.cpp:273–288` prefers external `/clock` if received, otherwise RTC,
  then AP_HAL micros64. A header is not proof of its scheduling clock.
- `AP_DDS_Topic_Table.h:339–357` declares Status writer
  RELIABLE/TRANSIENT_LOCAL/KEEP_LAST depth 1. The actual C++ Observer requests
  BEST_EFFORT/VOLATILE/depth 5. Weaker requested reliability/durability is not,
  by itself, an incompatible QoS pair; VOLATILE does not request historical replay.
  No QoS change was made. Runtime offered QoS was not recorded in this attempt.

Thus a long wall interval need not span an unchanged-Status publication interval
in AP_HAL time. This is a supported explanation to investigate, **not a proven
cause**. The captured odometry header domain has not been independently equated
to AP_HAL's scheduling clock. Discovery delay, delivery/loss, scheduling and
binary/config differences have not been excluded. The graphical exception does
not establish any of these causes; no CPU/renderer/rover attribution is made.

## Exact historical window and limits of the comparison

`status_window_review.json` preserves numbers and clock assumptions:

- Wrapper Python monotonic start `61687.683750822` s, elapsed
  `10.04702108100173` s, end `61697.730771903` s. Its recorded wall interval differs;
  wall timestamps are not used for elapsed calculations.
- Ten C++ odometry receipts span **5,153,162,247 steady-clock ns**. Their header
  stamps are 6.520, 6.540, …, 6.700 s: **0.180 source seconds**. One receipt gap is
  about 4.185 s despite a 20 ms header increment. No cause or whole-run RTF follows
  from this: buffered delivery, source timing and scheduling are not separated.
- The single later Python worker Status snapshot was received at
  `61785.559683921` monotonic s, about **87.829 s after wrapper completion**,
  header 8.414180 s, no per-message GID. These two Python monotonic readings are
  from the same Linux container/boot and API. This comparison does not equate
  C++ steady epochs, simulated/header timestamps or Docker wall clocks.
- The worker snapshot is a last value, not a history. It proves neither presence
  nor absence of Status during the C++ window. No intermediate values are rebuilt.

The global cap is **20 total samples**; the attempt recorded only 10. Therefore
that cap did **not** terminate this historical capture. Separately, offline
regression demonstrates that 20 odometry callbacks *can* exhaust the cap before
Status arrives. This ends collection with missing-stream data, **not a complete
capture**. This design risk is distinct from this attempt's missing footer.

## Minimum next trial and acceptance — proposal only

No evidence supports an exact larger wall timeout or a fixed warm-up. The minimum
regression trial therefore keeps **20 total samples / 10 s**, current topics/QoS
and the newly linked binary. Its limited purpose is to test normal explicit
closure and whether both streams arrive; it cannot guarantee Status receipt.
No duration, allocation or runtime setting is changed automatically.

Acceptance for **recorded diagnostic data**, never identity:

1. At least one sample from **each** expected topic, correct native message type
   and valid header/frames under the existing collector contract.
2. Per-sample nonzero GID with implementation identifier, non-intra-process
   metadata, available separate graph observation, no incomplete samples.
3. Ordered start/end, correct schema/counts, durable journal finalization, final
   stdout receipt consistent with that journal **and rc=0** from the same invocation.
4. Identity/source association and movement remain BLOCKED regardless of result.

With missing Status or odometry, normal SAMPLE_LIMIT/DURATION_LIMIT must still
write end + counts + `data_present_both_streams=false` + `capture_complete=null`
and finish the journal. Stdout must report UNCERTAIN / capture_complete=false,
rc=2. A footer's null does not itself confirm its own close. With blocked setup,
fsync, shutdown, OS scheduling or another hard timeout, closure cannot be guaranteed:
keep any partial bytes, missing receipt and uncertainty; never repair or repeat.
The corrected shared budget reserves at most 50 ms **within** 10 s for normal
closure. It neither extends the hard limit nor promises every filesystem can close.

An allocation alternative, **not implemented or selected**, is reserving one of
20 slots for Status (at most 19 odometry samples while waiting). It could prevent
future odometry-only cap exhaustion, but cannot explain the historical 10 samples
or make Status publish sooner. It would require separate code review/tests and
explicit selection before an authorized run. No quota or longer duration is
silently bundled into this next trial.

Before any future trial: separate authorization; exact environment/process and
restriction inspection; do not join an uncertain existing session. Use only a
protected authorized opening/closure, a fresh private output directory and the
reviewed new hash. The command **inside that accredited ROS environment** would be:

```bash
"/tmp/tfg-rover-deadline-link-ju21k1sq/build/rover_passive_collector" \
  --output "$NEW_PRIVATE_DIR/journal.jsonl" --max-samples 20 --duration-s 10 \
  > "$NEW_PRIVATE_DIR/receipt.json" 2> "$NEW_PRIVATE_DIR/stderr.txt"
rc=$?
printf '%s\n' "$rc" > "$NEW_PRIVATE_DIR/returncode.txt"
```

This block is **not executed**. The caller must create a new 0700 directory,
verify the exact binary/hash, preserve stdout/stderr/return code and hashes, then
analyze a byte-exact copy using the existing offline reader. Stop on any identity,
restriction, write, timeout, missing-stream or contradictory result. No retry or
extra time is implied. Future completion still leaves the chain
publisher↔XRCE/session↔SYSID↔SITL v3↔bridge/model unaccredited.

Offline verification: **73 tests passed**. The deterministic budget regression
now additionally covers odometry-only cap exhaustion and explicit time-limit
closure with missing Status. Existing fake-header syntax checks and offline
reader tests passed. These are separate from the real link and from reception;
no corrected collector was executed.

## Later authorized reserved-stream trial — 2026-10-22

The earlier quota alternative above is now implemented **only when explicitly
selected by `--reserve-streams`**, and Joel separately authorized one exploratory
120 s / 20 stored-sample trial. The old unchanged-20/10 proposal remains historical;
no previously stored capture or authorization was rewritten.

[New evidence](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/README.md):
real compile/link passed, 79 offline tests passed, one protected start/capture/stop.
Actual capture ended at SAMPLE_LIMIT after about 16.872 s, with **1 Status and
19 odometry**, per-message GIDs/rmw_fastrtps_cpp, coherent footer/receipt and rc=0.
Omitted-by-quota counts were zero: reserve logic was verified offline, but was not
shown necessary by this run. Public discovery records types and offered QoS
separately; history was UNKNOWN and reported depth 0 was not reinterpreted as a
known queue configuration. Requested QoS, graphics, models and parameters did not
change. Status is now observed with MessageInfo; the complete
publisher↔XRCE/SYSID↔SITL/bridge/model association and movement remain BLOCKED.
The two prior captures are intact; this outcome does not explain their absences.
