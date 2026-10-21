# Passive MessageInfo prototype — OFFLINE ONLY

`observer.hpp` is a header-only component, with no executable, package registration,
CMake target, CLI/MCP route or lifecycle wiring. It never initializes or spins ROS.
A future authorized harness would own an existing node and executor, construct
`tfg::rover_passive::Observer(node, sink)`, and consume typed `Sample` records. This
is an API sketch, not an operational invocation or authorization. No control code
imports this component. It has no publishers or service clients.

The public signature is message plus `const rclcpp::MessageInfo &`, observed in
installed Humble rclcpp **16.0.19** headers during the read-only collection of
2026-10-21. `get_rmw_message_info().publisher_gid` supplies the bytes associated
with that callback, including the RMW implementation identifier. rmw **6.1.3**
defines the structure; Fast RTPS **6.2.10** was installed. No active bridge process
was present during that collection, so its loaded RMW remains UNKNOWN. Header
observations support the API choice, not runtime behavior or binary provenance.
A syntax-only compile against real installed headers passed on 2026-10-21
(see below). No ROS build system, link or runtime test has been performed.

Subscriptions are limited to `/ap/v3/status` (`ardupilot_msgs/msg/Status`) and
`/rover1/odometry` (`nav_msgs/msg/Odometry`), depth 5, BEST_EFFORT, VOLATILE. The
prototype does not add parameters/services, alter QoS of existing components or
subscribe from the Python worker. Normal node-internal ROS facilities belong to
the caller's node; this component never creates additional nodes or controls.
The caller must stop/drain callbacks before destroying the Observer; it must
keep the node alive for the observer lifetime and serialize calls/sink access
(e.g. its existing mutually exclusive callback group). No respawn or retry.

Each Sample separates:

- `message_publisher_gid` and `rmw_implementation_identifier`: copied directly
  from this callback's MessageInfo, never populated from discovery. Raw zero GIDs
  remain raw zero bytes; their usability is UNKNOWN. A missing identifier or an
  intra-process sample also remains UNKNOWN. Otherwise the label is only
  OBSERVED_NOT_ACCREDITED. GIDs are not authenticated globally unique identities.
- `graph_candidates`: endpoint GID/name/namespace from public discovery, with a
  separate receipt and source. Even one matching candidate does not populate
  `attributed_publisher_identity`. Graph failure leaves UNKNOWN, preserving the
  received message. Discovery may be stale and its duration is not bounded by
  this component; it must not be used for real-time control.
- `receipt`: system-clock Unix nanoseconds and process-local steady-clock
  nanoseconds at callback entry; neither is the source generation time.
- `message`: exact typed copy, retaining header timestamp and frames. Status
  retains vehicle_type/armed/flying and other native fields; Odometry retains
  pose/twist/covariance and frames, with ROS contract units, without conversion.
  Header time is not compared to system/steady time. Rewinds are preserved, not
  repaired. No stationary, ground contact or identity inference is performed.

`status` is always BLOCKED, `source_association_verified` and
`movement_authorized` are false, and attributed publisher identity stays absent.
There is no threshold or flag that verifies identity. The Python GID stays None;
no output here feeds its guard, binding, executor or reservations.

The sink receives a value record; no file or network sink is supplied. A future
collector must bound collection, preserve provenance, record process/container
identity and versions, and handle sink failure explicitly. Exceptions from the
sink propagate; no automatic retry. Graph exception text is not retained.

## Offline checks and remaining work

`tests/test_rover_passive_rclcpp.py` compiles a C++17 harness against **fake** headers
and a fake node with only subscription/discovery methods. It runs only that test
binary, never a ROS build/node. It checks both callbacks, source GID differing
from graph candidates, several candidates, graph failure, missing/zero metadata,
intra-process handling, wrong vehicle type, source replacement/rewind, typed
message copies and unconditional blocking. If no C++17 compiler exists, those
checks skip explicitly. They do not establish ABI or middleware compatibility.

Before any real passive receiver: separately authorize a link check and passive
read-only run, identify its loaded RMW and inter/intra-process behavior, and test
multiple publishers on one topic. Preserve GID + implementation identifier and
capture scope/times together; compare endpoints without treating discovery as
attribution. Then establish the public evidence chain to XRCE participant/session,
effective SYSID/DDS namespace, SITL v3, active bridge binary/YAML and Gazebo model.
A per-message GID does not prove that complete chain. None of these future steps
authorizes motion or changes the project's closed rover policy.


## Real-header syntax-only check — 2026-10-21

`compile_contract.cpp` is a translation-unit probe with static assertions, no main
and no node construction. It includes the complete Observer (both public typed
subscription callbacks) and checks the const MessageInfo accessor, rmw_gid_t,
from_intra_process bool, GID storage size and native Status/Odometry header types.

The existing container was running and matched engine
`2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99`, full ID
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`
and image `sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`.
The compiler was invoked directly inside it with source on stdin. No header was
copied into it, no setup script sourced, no packages installed, no services or
nodes started, no binary emitted/executed. Return code **0**, stdout/stderr empty.
This verifies parsing/type checking against its real installed headers, not
linkability, loaded RMW, message delivery or the XRCE/SITL/bridge association.
The observer's BLOCKED semantics are unchanged.

Reproduction of the successful compiler invocation (a compilation recipe, **not**
a runtime entry or permission to execute it). First revalidate the exact container
is already running and matches the inspected environment; if not, stop. From the
repository root, use the existing Python interpreter. No output files are created:

```python
from pathlib import Path
import subprocess

root = Path("tools/rover_passive_rclcpp")
source = ('#line 1 "observer.hpp"\n' + (root / "observer.hpp").read_text()
          + '\n#line 1 "compile_contract.cpp"\n'
          + (root / "compile_contract.cpp").read_text().replace('#include "observer.hpp"', ''))
# Same include roots as the preserved bridge flags.make, restricted to Humble,
# plus the installed ArduPilot message package. No arbitrary compiler flag input.
packages = """rclcpp rclcpp_components builtin_interfaces actuator_msgs geometry_msgs
 gps_msgs nav_msgs rcl_interfaces rosgraph_msgs sensor_msgs std_msgs tf2_msgs
 trajectory_msgs vision_msgs ament_index_cpp libstatistics_collector rosidl_runtime_c
 rcutils rosidl_typesupport_interface fastcdr rosidl_runtime_cpp
 rosidl_typesupport_fastrtps_cpp rmw rosidl_typesupport_fastrtps_c
 rosidl_typesupport_introspection_c rosidl_typesupport_introspection_cpp rcl
 rcl_logging_interface rcl_yaml_param_parser libyaml_vendor tracetools rcpputils
 statistics_msgs rosidl_typesupport_cpp rosidl_typesupport_c class_loader
 composition_interfaces action_msgs unique_identifier_msgs""".split()
includes = ["-isystem", "/root/ardu_ws/install/ardupilot_msgs/include/ardupilot_msgs"]
for package in packages:
    includes += ["-isystem", "/opt/ros/humble/include/" + package]
command = ["docker", "exec", "-i",
           "0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f",
           "/usr/bin/c++", "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
           "-fsyntax-only", "-x", "c++", *includes, "-"]
result = subprocess.run(command, input=source, text=True, capture_output=True, timeout=45)
print(result.returncode, result.stdout, result.stderr)
```

A missing compiler/header or nonzero result is a compile failure to diagnose;
do not install dependencies, start a stopped container, or substitute fake headers
and label that a real-header pass. The separate fake-header tests still test data
flow only. This successful check does not change their scope or prove ABI/runtime.


## Separate collector source (prepared later, not executed)

[COLLECTOR.md](COLLECTOR.md) describes `collector.cpp`, `collector_core.hpp` and
`private_journal.hpp`: bounded standalone collection source, exclusive private
output and uncertain-failure semantics. No executable/target was added to the
project and no runtime wiring changed. The Observer check above remains scoped to Observer/compile_contract.cpp. A later
separate syntax-only check of the complete collector also passed with installed
headers; see COLLECTOR.md for its exact scope and the still-unverified linkage
and reception. Neither check executes a node or proves runtime identity.
