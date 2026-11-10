#!/usr/bin/env bash
# Explicit temporary build only. Never installs or executes diagnostic artifacts.
set -euo pipefail
[[ $# == 2 && "$1" = /tmp/* && "$2" = /tmp/* && ! -e "$2" ]] || exit 2
src=$(realpath "$1")
root=$2
mkdir -m 700 "$root"
bash /workspace/tfg/tools/rover_xrce_trace/build.sh "$src/native" "$root/agent"
set +u
source /opt/ros/humble/setup.bash
source /root/ardu_ws/install/setup.bash
set -u
GZ_VERSION=harmonic cmake -S "$src/bridge" -B "$root/bridge" \
 -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
 -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3
cmake --build "$root/bridge" --target parameter_bridge --parallel 2
sha256sum "$root/agent/agent-build/micro_ros_agent" \
 "$root/agent/native-build/libmicroxrcedds_agent.so.2.4.2" \
 "$root/bridge/parameter_bridge" "$root/bridge/libros_gz_bridge.so"
