#!/usr/bin/env bash
# Run only in the already-verified container. Builds; NEVER runs an agent.
set -euo pipefail
if [[ $# != 2 ]]; then echo 'usage: build.sh PATCHED_NATIVE_SOURCE NEW_BUILD_ROOT' >&2; exit 2; fi
native=$(realpath "$1")
root=$2
[[ "$root" = /tmp/* && ! -e "$root" ]] || { echo 'New /tmp build root required' >&2; exit 2; }
mkdir -m 700 "$root"
root=$(realpath "$root")
# Existing prefixes only, no superbuild, downloads or dependency installation.
set +u
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash
set -u
cmake -S "$native" -B "$root/native-build" \
 -DCMAKE_BUILD_TYPE=Release -DUAGENT_SUPERBUILD=OFF \
 -DUAGENT_USE_SYSTEM_FASTDDS=ON -DUAGENT_USE_SYSTEM_FASTCDR=ON \
 -DUAGENT_USE_SYSTEM_LOGGER=ON -DUAGENT_CED_PROFILE=OFF \
 -DUAGENT_P2P_PROFILE=OFF -DUAGENT_FAST_PROFILE=ON \
 -DUAGENT_BUILD_EXECUTABLE=OFF -DUAGENT_BUILD_TESTS=OFF
cmake --build "$root/native-build" --target microxrcedds_agent --parallel 2
# Copy ROS wrapper source, preserve its callbacks and graph implementation.
cp -a /root/ardu_ws/src/micro_ros_agent/micro_ros_agent "$root/ros-agent"
cat >> "$root/ros-agent/CMakeLists.txt" <<'CMAKE'

# Diagnostic build only: bind the copied wrapper to the copied native library.
set_target_properties(microxrcedds_agent PROPERTIES
 IMPORTED_LOCATION "${TFG_NATIVE_BUILD}/libmicroxrcedds_agent.so"
 IMPORTED_LOCATION_RELEASE "${TFG_NATIVE_BUILD}/libmicroxrcedds_agent.so")
target_include_directories(micro_ros_agent BEFORE PRIVATE
 "${TFG_NATIVE_SOURCE}/include" "${TFG_NATIVE_BUILD}/include")
set_target_properties(micro_ros_agent PROPERTIES BUILD_RPATH "${TFG_NATIVE_BUILD}")
CMAKE
cmake -S "$root/ros-agent" -B "$root/agent-build" \
 -DMICROROSAGENT_SUPERBUILD=OFF -DCMAKE_BUILD_TYPE=Release \
 -DTFG_NATIVE_SOURCE="$native" -DTFG_NATIVE_BUILD="$root/native-build" \
 -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3
cmake --build "$root/agent-build" --target micro_ros_agent --parallel 2
# Static inspection only. Do not use ldd or run --help on the agent.
sha256sum "$root/agent-build/micro_ros_agent" "$root/native-build/libmicroxrcedds_agent.so"
readelf -d "$root/agent-build/micro_ros_agent"
