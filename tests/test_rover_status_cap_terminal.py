"""Offline cap replay and native main/real pipes; synthetic session, no DDS."""
import json
import os
from pathlib import Path

import pytest

from tests.fixtures.rover_receiver_protocol_native import SESSION_STUB, build
from tests.test_rover_receiver_protocol import Protocol
from tools.rover_xrce_trace.monitor import Drain

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / 'evaluation/operations/rover_status_authorized_window_2026_10_31/8a4d30bd-ed13-45bc-b181-fd24f1f4dc5c'


def test_original_agent_cap_is_retained_and_rejected(tmp_path):
    raw = (HISTORY / 'preserved/sdk/overlay/capture/trace.log').read_bytes()
    caps = [json.loads(line.split(b' ', 1)[1]) for line in raw.splitlines()
            if b'"event":"status_limit"' in line]
    assert len(caps) == 1 and caps[0]['incomplete'] and caps[0]['lost'] == 0
    with (tmp_path / 'trace').open('xb') as output:
        drain = Drain(output, status_diagnostic=True)
        drain.feed(raw)
        drain.finish()
    assert (tmp_path / 'trace').read_bytes() == raw
    assert drain.errors == ['Native diagnostic reports incomplete coverage']
    monitor = json.loads((HISTORY / 'preserved/sdk/overlay/capture/monitor.json').read_text())
    assert monitor['phase'] == 'INCOMPLETE' and not monitor['capture_complete']
    assert drain.errors[0] in monitor['errors']


@pytest.fixture(scope='module')
def failing_native(tmp_path_factory):
    # The real main, Output and terminal are compiled. Only Session and
    # middleware are doubles: this reproduces propagation, not the missing
    # historical snapshot, file reads or original process context.
    stub = '#include <cstdlib>\n#include <stdexcept>\n' + SESSION_STUB
    stub = stub.replace('void check()const{}', '''void check()const{
      if(const char* path=std::getenv("TFG_SYNTHETIC_SESSION_FAILURE")){
        std::ifstream file(path);std::string reason;
        if(std::getline(file,reason)){
          if(reason=="Diagnostic cap reached")throw DiagnosticExhausted();
          throw std::runtime_error(reason);
        }
      }
    }''')
    return build(tmp_path_factory.mktemp('cap-terminal'), source_root=ROOT, session_stub=stub)


@pytest.mark.parametrize('reason,code', [
    ('Monitor unavailable', 'MONITOR_UNAVAILABLE'),
    ('Stale monitor observation', 'STALE_MONITOR'),
    ('Session execution/selection changed', 'SESSION_EXECUTION_CHANGED'),
    ('Output budget exhausted', 'OUTPUT_BUDGET'),
    ('unreviewed text /secret\nforged message', 'UNCLASSIFIED_STD_EXCEPTION'),
])
def test_exception_reason_survives_failed_close_without_footer(failing_native, tmp_path, monkeypatch, reason, code):
    failure = tmp_path / 'session-failure'
    monkeypatch.setenv('TFG_SYNTHETIC_SESSION_FAILURE', str(failure))
    p = Protocol(failing_native)
    try:
        p.source._next(1)  # header before a synthetic monitor/context failure
        failure.write_text(reason)
        with pytest.raises(Exception, match='disconnected/truncated'):
            p.source._next(2)
        with pytest.raises(Exception):
            p.source.close(timeout_s=1)
        result = p.source.close_result
        assert result['return_code'] == 2 and not p.source.closed and not p.source.footer
        stderr = p.source.frames.stderr
        assert b'reason=EXCEPTION stage=RECEPTION rc=2' in stderr
        assert f'detail={code}\n'.encode() in stderr
        assert len(stderr) <= 192 and b'/secret' not in stderr and b'forged' not in stderr
        assert not any(row['event'] == 'footer' for row in p.records())
    finally:
        p.finish()


def test_cap_closes_native_context_without_success_footer(failing_native, tmp_path, monkeypatch):
    failure=tmp_path/'failure';shutdown=tmp_path/'shutdown'
    monkeypatch.setenv('TFG_SYNTHETIC_SESSION_FAILURE',str(failure))
    monkeypatch.setenv('TFG_SYNTHETIC_SHUTDOWN_FILE',str(shutdown))
    p=Protocol(failing_native)
    try:
        p.source._next(1)
        failure.write_text('Diagnostic cap reached')
        with pytest.raises(Exception,match='disconnected/truncated'):p.source._next(2)
        with pytest.raises(Exception):p.source.close(timeout_s=1)
        assert shutdown.read_text()=='SYNTHETIC_RCLCPP_SHUTDOWN\n'
        assert p.source.close_result['return_code']==2
        assert b'reason=DELIBERATE stage=DIAGNOSTIC_CAP rc=2' in p.source.frames.stderr
        assert not p.source.footer and not p.source.closed
        assert not any(r['event']=='footer' for r in p.records())
    finally:p.finish()
