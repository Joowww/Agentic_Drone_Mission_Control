#!/usr/bin/env bash
# SYNTHETIC loader/hook check. Enables the plugin in tfg-capture-test only for this run.
set -euo pipefail
W=/tmp/tfg-loader-hooks-20261020T161004Z
P=$HOME/.hermes/profiles/tfg-capture-test
R=/home/joelm/TFG/Agentic_Drone_Mission_Control
HROOT=$HOME/.hermes/hermes-agent
PY=$HOME/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3

# Plugin copy must equal the committed plugin.
for f in __init__.py capture.py plugin.yaml event.schema.json; do
  cmp -s <(git -C "$R" show "HEAD:observability/hermes_capture/$f") "$P/plugins/tfg-observability-capture/$f" \
    || { echo "plugin copy differs from HEAD: $f" >&2; exit 3; }
done
git -C "$R" rev-parse HEAD > "$W/evidence/plugin_source_commit.txt"
(cd "$P/plugins/tfg-observability-capture" && sha256sum __init__.py capture.py plugin.yaml event.schema.json) \
  > "$W/evidence/plugin_files.sha256"

cp -p "$P/config.yaml" "$W/config.yaml.before"
restore() { cp -p "$W/config.yaml.before" "$P/config.yaml"; sed -n '/^plugins:/,/^[^ ]/p' "$P/config.yaml" > "$W/evidence/plugins_section_after_restore.txt"; }
trap restore EXIT
sed -i 's/^  enabled: \[\]$/  enabled:\n    - tfg-observability-capture/' "$P/config.yaml"
grep -A2 '^plugins:' "$P/config.yaml" > "$W/evidence/plugins_section_during_run.txt"

date -u +%FT%T.%3NZ > "$W/evidence/run_started_utc.txt"
set +e
env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 TERM=dumb NO_COLOR=1 \
  HERMES_HOME="$P" HERMES_DISABLE_LAZY_INSTALLS=1 \
  HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 NO_PROXY=127.0.0.1,localhost \
  TFG_OBSERVABILITY_CAPTURE=1 TFG_OBSERVABILITY_DIR="$W/capture" \
  TFG_OBSERVABILITY_RUN_ID=SYNTHETIC-loader-hooks-20261020 TFG_OBSERVABILITY_CASE_ID=SYNTHETIC-fixtures \
  timeout 180 "$PY" -I -B -c '
import atexit, ipaddress, json, socket, sys
attempts = []
def _loopback(address):
    try:
        return ipaddress.ip_address(address[0]).is_loopback
    except Exception:
        return address[0] in ("localhost",)
_connect = socket.socket.connect
def guarded(self, address):
    if self.family == socket.AF_UNIX or (isinstance(address, tuple) and _loopback(address)):
        return _connect(self, address)
    attempts.append(str(address)[:60])
    raise OSError("non-loopback network blocked by SYNTHETIC loader check")
socket.socket.connect = guarded
atexit.register(lambda: open(sys.argv[2], "w").write(json.dumps({"blocked_non_loopback_connects": attempts})))
sys.path.insert(0, sys.argv[3])
sys._hermes_pin_default_home = True
import hermes_bootstrap  # Hermes real bootstrap, as its launcher does
import runpy
runpy.run_path(sys.argv[1], run_name="__main__")
' "$W/harness.py" "$W/evidence/network_guard.json" "$HROOT" > "$W/evidence/harness_report.json" 2> "$W/evidence/harness.stderr"
rc=$?
set -e
echo "rc=$rc" > "$W/evidence/harness.rc"
date -u +%FT%T.%3NZ > "$W/evidence/run_finished_utc.txt"
exit $rc
