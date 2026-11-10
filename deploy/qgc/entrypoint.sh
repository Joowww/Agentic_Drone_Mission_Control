#!/bin/sh
# Every start begins from the same settings: all AutoConnect sources disabled (group and keys from
# QGroundControl v5.1.5 src/Settings/AutoConnect.SettingsGroup.json). No settings-version key is
# written, so QGC keeps these values instead of clearing them as an upgrade.
set -eu
mkdir -p "$HOME/.config/QGroundControl"
cp /opt/tfg/QGroundControl.ini "$HOME/.config/QGroundControl/QGroundControl.ini"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-qgc}"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
exec /opt/qgroundcontrol/AppRun "$@"
