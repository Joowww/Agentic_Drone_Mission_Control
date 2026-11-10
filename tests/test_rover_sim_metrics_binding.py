"""Simulation metrics bound to the exact execution: acquisition (rover_sim_metrics.collect) and consumption
(rover_first_navigation.cadence_from_metrics).

No Docker or container is used: ``run`` and the execution reader are doubles. Reproduces the counterexample of the
review (same container id, another lifecycle accepted) and the other ways a sample can be old or ambiguous."""
from __future__ import annotations

import copy
import json
import types

import pytest

from tools import rover_first_navigation as nav
from tools import rover_sim_metrics as metrics_tool
from tools.reconciliation_environment import ActiveExecutionReadError
from tools.rover_control import RoverControlError
from tests.test_rover_sitl_preparation import EXECUTION, LIFECYCLE

BOOT = EXECUTION['container_boot_id']
CONTAINER = EXECUTION['persistent_identity']['container_id']
END = 5_000_000_000_000
NOW = END + 10**9


def stream(rate_wall=1.2, rate_sim=2.0):
    return {'fresh': True, 'stamps_strictly_increasing': True, 'rate_per_wall_s': rate_wall, 'rate_per_sim_s': rate_sim}


def sample(boot=BOOT):
    return {'wall_start_ns': END - 20 * 10**9, 'wall_end_ns': END, 'boot_id': boot, 'seen': {}}


def run_double(raw, *, stats_code=0, exec_code=0, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd[:2])
        if cmd[1] == 'stats':
            return types.SimpleNamespace(returncode=stats_code, stdout=json.dumps({'Container': CONTAINER}), stderr='')
        return types.SimpleNamespace(returncode=exec_code, stdout=json.dumps(raw) + '\n', stderr='sampler error')
    return run


def reader(*executions):
    """The execution reader returning each value in turn (an exception instance is raised)."""
    queue = list(executions)

    def inspect():
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)
    return inspect


def summary_ok(raw, docker_stats):
    return {'schema': metrics_tool.SCHEMA, 'docker_stats': docker_stats, 'stale_streams': [], 'status': stream(),
            'odometry': {'fresh': True}, 'real_time_factor': 0.6, 'window_wall_s': 20.0}


@pytest.fixture
def acquire(monkeypatch):
    monkeypatch.setattr(metrics_tool, 'summarize', summary_ok)

    def go(*, lifecycle=LIFECYCLE, executions=(EXECUTION, EXECUTION), raw=None, **kw):
        out = metrics_tool.collect(CONTAINER, lifecycle_id=lifecycle, run=run_double(raw or sample(), **kw),
                                   inspect_execution=reader(*executions))
        raw_out, summary, binding = out
        return {'summary': summary, 'raw': raw_out, 'binding': binding}
    return go


def consume(metrics, *, lifecycle=LIFECYCLE, execution=EXECUTION):
    return nav.cadence_from_metrics(metrics, lifecycle_id=lifecycle, environment_execution=execution,
                                    host_boot_id=BOOT, now_monotonic_ns=NOW)


# ------------------------------------------------------------- acquisition --
def test_acquired_sample_is_sealed_to_lifecycle_and_execution_and_accepted(acquire):
    metrics = acquire()
    assert metrics['binding'] == {'schema': metrics_tool.BINDING_SCHEMA, 'lifecycle_id': LIFECYCLE,
                                  'environment_execution': EXECUTION}
    parsed = consume(metrics)
    assert parsed['lifecycle_id'] == LIFECYCLE and parsed['container_id'] == CONTAINER and parsed['rtf'] == 0.6


@pytest.mark.parametrize('lifecycle', ['', None])
def test_acquisition_requires_a_lifecycle(acquire, lifecycle):
    with pytest.raises(ValueError, match='lifecycle_id'):
        acquire(lifecycle=lifecycle)


def test_acquisition_refuses_another_container():
    other = copy.deepcopy(EXECUTION)
    other['persistent_identity']['container_id'] = 'd' * 64
    calls = []
    with pytest.raises(RuntimeError, match='not the active container execution'):
        metrics_tool.collect(CONTAINER, lifecycle_id=LIFECYCLE, run=run_double(sample(), calls=calls),
                             inspect_execution=reader(other))
    assert calls == []  # nothing sampled from a container that is not the active execution


def test_acquisition_with_unreadable_execution_is_not_a_sample():
    error = ActiveExecutionReadError('metadata.before', 'status', 'METADATA_NOT_ACTIVE')
    calls = []
    with pytest.raises(ActiveExecutionReadError):
        metrics_tool.collect(CONTAINER, lifecycle_id=LIFECYCLE, run=run_double(sample(), calls=calls),
                             inspect_execution=reader(error))
    assert calls == []


@pytest.mark.parametrize('field,value', [('container_started_at', '2026-11-03T10:00:00Z'),
                                         ('container_boot_id', 'other-boot')])
def test_acquisition_refuses_an_execution_that_changed_during_the_window(acquire, field, value):
    restarted = {**copy.deepcopy(EXECUTION), field: value}
    with pytest.raises(RuntimeError, match='changed or became unreadable'):
        acquire(executions=(EXECUTION, restarted))


def test_acquisition_refuses_an_execution_unreadable_after_the_window(acquire):
    with pytest.raises(ActiveExecutionReadError):
        acquire(executions=(EXECUTION, ActiveExecutionReadError('metadata.before', 'status', 'METADATA_NOT_ACTIVE')))


def test_acquisition_refuses_a_sampler_running_under_another_boot(acquire):
    with pytest.raises(RuntimeError, match='Sampler boot'):
        acquire(raw=sample(boot='other-boot'))


def test_failed_sampler_is_not_a_sample(acquire):
    with pytest.raises(RuntimeError, match='sampler failed'):
        acquire(exec_code=1)


# ------------------------------------------------------------- consumption --
def test_same_container_in_another_lifecycle_is_refused(acquire):
    """The review's counterexample: same container execution, different lifecycle, was ACCEPTED."""
    metrics = acquire()
    with pytest.raises(RoverControlError, match='not bound to this lifecycle'):
        consume(metrics, lifecycle='another-lifecycle')


def test_same_container_id_in_another_execution_is_refused(acquire):
    """Same persistent container restarted within the same host boot: another execution, refused."""
    metrics = acquire()
    restarted = {**copy.deepcopy(EXECUTION), 'container_started_at': '2026-11-03T10:00:00Z'}
    with pytest.raises(RoverControlError, match='not bound to this lifecycle'):
        consume(metrics, execution=restarted)


@pytest.mark.parametrize('mutate', [
    lambda m: m.pop('binding'),
    lambda m: m.__setitem__('binding', None),
    lambda m: m['binding'].__setitem__('schema', 'tfg.rover.sim-metrics-binding/0'),
    lambda m: m['binding'].pop('lifecycle_id'),
    lambda m: m['binding'].pop('environment_execution'),
    lambda m: m['binding']['environment_execution'].pop('container_started_at'),
    lambda m: m['binding']['environment_execution']['persistent_identity'].__setitem__('created_at', 'x'),
], ids=['absent', 'null', 'schema', 'no-lifecycle', 'no-execution', 'no-start', 'other-incarnation'])
def test_missing_or_ambiguous_binding_is_refused(acquire, mutate):
    metrics = acquire()
    mutate(metrics)
    with pytest.raises(RoverControlError, match='not bound to this lifecycle'):
        consume(metrics)


def test_binding_and_sample_boot_must_agree(acquire):
    """A sample re-stamped with the current boot keeps the boot it was bound to: refused."""
    metrics = acquire()
    metrics['binding']['environment_execution']['container_boot_id'] = 'other-boot'
    execution = copy.deepcopy(metrics['binding']['environment_execution'])
    with pytest.raises(RoverControlError, match='not bound to this lifecycle'):
        consume(metrics, execution=execution)


def test_old_sample_of_the_right_execution_is_still_refused(acquire):
    metrics = acquire()
    with pytest.raises(RoverControlError, match='current measurement'):
        nav.cadence_from_metrics(metrics, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                                 host_boot_id=BOOT, now_monotonic_ns=END + int(nav.CADENCE_MAX_AGE_S * 1e9) + 1)


def test_main_requires_the_lifecycle(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['rover_sim_metrics', CONTAINER])
    with pytest.raises(SystemExit):
        metrics_tool.main()
    assert '--lifecycle-id' in capsys.readouterr().err
