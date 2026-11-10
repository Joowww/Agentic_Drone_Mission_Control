"""Readiness diagnostics with a temporary local script; no Docker/ROS."""
import subprocess
from datetime import datetime
from unittest.mock import Mock

import pytest

from tools import simulation_status as status


def test_timeout_preserves_real_partial_output(tmp_path, monkeypatch):
    script = tmp_path / 'check.sh'
    # Emit both streams, then block without spawning a child left behind by Bash.
    script.write_text('echo "[1/5] Docker container..."\n'
                      'echo "diagnostic before completion" >&2\n'
                      'exec python3 -c "import signal; signal.pause()"\n')
    monkeypatch.setattr(status, 'CHECK_SCRIPT', script)
    monkeypatch.setattr(status, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(status, 'READINESS_TIMEOUT_S', 0.5)
    result = status.check_simulation_ready()
    assert result['ready'] is False and result['status'] == 'ERROR'
    assert result['return_code'] is None
    assert result['timed_out'] and result['partial_output']
    assert result['stdout'] == '[1/5] Docker container...\n'
    assert result['stderr'] == 'diagnostic before completion\n'
    assert result['error_type'] == 'TimeoutExpired'
    assert result['command'] == ['bash', str(script)]
    assert result['cwd'] == str(tmp_path) and result['profile'] == 'two_drones'
    assert result['timeout_s'] == 0.5 and result['duration_wall_s'] >= 0
    assert datetime.fromisoformat(result['started_at_utc']).tzinfo is not None
    assert datetime.fromisoformat(result['finished_at_utc']).tzinfo is not None
    assert 'completed_checks' not in result  # a heading is not a completed check


@pytest.mark.parametrize('stdout,stderr,expected', [
    (b'partial\xff\n', b'error\n', 'partial\ufffd\n'),
    (None, None, ''),
    ('[PASS] partial check\n', 'still pending', '[PASS] partial check\n'),
    (b'SIMULATION HEALTHY\n', b'', 'SIMULATION HEALTHY\n'),
])
def test_timeout_is_never_ready_even_if_output_looks_successful(monkeypatch, stdout, stderr, expected):
    run = Mock(side_effect=subprocess.TimeoutExpired('fake-check', 180, output=stdout, stderr=stderr))
    monkeypatch.setattr(status.subprocess, 'run', run)
    result = status.check_simulation_ready()
    assert result['ready'] is False and result['return_code'] is None
    assert result['stdout'] == expected
    assert result['timeout_s'] == 180 == run.call_args.kwargs['timeout']
    assert result['partial_output'] is True


@pytest.mark.parametrize('code,ready', [(0,True),(1,False)])
def test_normal_return_contract_and_timeout_unchanged(monkeypatch, code, ready):
    run = Mock(return_value=subprocess.CompletedProcess('fake-check',code,'check output\n',''))
    monkeypatch.setattr(status.subprocess, 'run',run)
    result=status.check_simulation_ready()
    assert result['ready'] is ready and result['return_code']==code
    assert result['output']=='check output'
    assert run.call_args.kwargs['timeout']==180
