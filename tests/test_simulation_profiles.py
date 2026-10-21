"""Offline drift checks against calls and branches, not text-presence claims.

Only this test module is executable here. ROS launch objects, Popen and Docker
are doubles. Bash runs copied scripts in temporary projects; its host lifecycle
verifier/flock/sleep are doubles too. No real Docker, ROS or simulator is invoked.
This is not a general Bash interpreter or proof about installed upstream files.
"""
import ast
from enum import Enum
import json
from pathlib import Path
import shlex
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import tools.simulated_vehicle as selection
from tools import simulation_profiles as profiles
from tools.simulation_profiles import ACTIVE_PROFILE, PROFILES, TWO_DRONES

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulation" / "ros2_gazebo"
SIM_PROCESSES = SIM / "scripts" / "sim_processes.py"
START_BACKEND = SIM / "scripts" / "start_sim_backend.sh"
CHECK_SIM = SIM / "scripts" / "check_sim.sh"
LAUNCH = SIM / "launch" / TWO_DRONES.launch_file


def _function(source, name, namespace):
    """Compile only the named definition; never import an operational module."""
    tree = ast.parse(source)
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(definitions) == 1
    exec(compile(ast.Module(body=definitions, type_ignores=[]), '<offline-definition>', 'exec'), namespace)
    return namespace[name]


def _assert_popen(source, root):
    for setting in (None, 'true', 'false'):
        env = {} if setting is None else {'TFG_SIM_GUI': setting}
        popen = Mock(return_value=SimpleNamespace(pid=123))
        save = Mock()
        namespace = dict(
            get_profile=profiles.get_profile, Path=Path, Process=object, LOG_FILE=root/'launch.log', PID_FILE=root/'launch.pid',
            os=SimpleNamespace(environ=env), MARKER='TFG_SIM_PROJECT', PROJECT='offline-project',
            signal=SimpleNamespace(signal=Mock(), SIGINT=2, SIG_DFL=0),
            snapshot=lambda: {}, remembered_identities=set, select_owned=lambda *a: {},
            unattributed_auxiliaries=lambda *a: [], subprocess=SimpleNamespace(Popen=popen, DEVNULL=-3, STDOUT=-2),
            read_process=lambda pid: SimpleNamespace(identity=(pid, 17), start_ticks=17),
            save_state=save,
        )
        # Fresh temporary log avoids the unrelated existing-log rotation branch.
        (root/'launch.log').unlink(missing_ok=True)
        _function(source, 'start', namespace)()
        popen.assert_called_once()
        args, kwargs = popen.call_args
        assert len(args) == 1 and isinstance(args[0], list)
        command = args[0]
        assert command[:4] == ['ros2', 'launch', TWO_DRONES.launch_package, TWO_DRONES.launch_file]
        # Ordering of independent launch assignments is irrelevant; extras and
        # duplicates are not. No AST expression is silently discarded.
        assignments = command[4:]
        assert len(assignments) == len(TWO_DRONES.fixed_launch_arguments) + 1
        assert sorted(assignments) == sorted([
            *TWO_DRONES.fixed_launch_arguments,
            'gui:=' + ('false' if setting == 'false' else 'true'),
        ])
        tree = ast.parse(source)
        roots = [n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(getattr(t, 'id', None) == 'LAUNCHES' for t in n.targets)]
        assert len(roots) == 1
        namespace['LAUNCHES'] = ast.literal_eval(roots[0])
        recognizes = _function(source, 'is_project_launch', namespace)
        assert recognizes(SimpleNamespace(argv=tuple(command)))
        assert not recognizes(SimpleNamespace(argv=('ros2', 'launch', 'other_package', command[3])))
        assert kwargs['env']['TFG_SIM_PROJECT'] == 'offline-project'
        assert kwargs['start_new_session'] is True
        save.assert_called_once_with({(123, 17)})


# This executable only records arguments and returns synthetic data. It never
# evaluates a docker-exec payload or invokes any external tool.
_FAKE_DOCKER = r'''
import json, os, sys, shlex
from pathlib import Path
a = sys.argv[1:]
with open(os.environ['OFFLINE_CALLS'], 'a') as f:
    f.write(json.dumps(a) + '\n')
if a[:1] == ['inspect']:
    print('true' if os.environ.get('OFFLINE_CONTAINER', '1') == '1' else 'false')
    sys.exit(0)
if a[:1] in (['start'], ['cp']): sys.exit(0)
if a[:1] != ['exec']: sys.exit(90)
i = 1; variables = {}
while a[i].startswith('-'):
    if a[i] == '-e':
        key, value = a[i+1].split('=',1); variables[key] = value; i += 2
    else: i += 1
assert a[i] == 'tfg-ardupilot-gazebo'
payload = a[i+1:]
command = payload[2] if payload[:2] == ['bash','-lc'] else ' '.join(payload)
params = payload[4:] if payload[:2] == ['bash','-lc'] else []
if 'pgrep -f' in command:
    sys.exit(0 if os.environ.get('OFFLINE_GAZEBO', '1') == '1' else 1)
if 'pgrep -x' in command and params == ['arducopter']:
    print(os.environ.get('OFFLINE_COUNT', '2')); sys.exit(0)
if 'pgrep -x' in command and params == ['ardurover']:
    print(os.environ.get('OFFLINE_ROVER_COUNT', '1')); sys.exit(0)
if 'ros2 topic list' in command:
    print(os.environ.get('OFFLINE_TOPICS', '/ap/v1/status\n/ap/v2/status')); sys.exit(0)
if 'ros2 service call' in command:
    assert len(params)==1
    print('response:\nstd_srvs.srv.Trigger_Response(success=' + ('False' if params[0] == os.environ.get('OFFLINE_BAD_SERVICE') else 'True') + ", message='synthetic response')")
    sys.exit(0)
if payload == ['python3', '-']:
    Path(os.environ['OFFLINE_PORTS_LOG']).write_text(json.dumps({
        'ports':json.loads(variables['TFG_SIM_PORTS']), 'source':sys.stdin.read()}))
    sys.exit(0)
if ('/tmp/tfg_sim_processes.py' in command or 'ros2 pkg prefix' in command
        or payload[:2] == ['mkdir','-p']): sys.exit(0)
sys.exit(91)
'''


def _run_shell(tmp_path, source, *, start=False, gui=True, catalog_source=None, **settings):
    """Run original control flow with synthetic observations in a fresh project.

    Only the fixed /tmp lifecycle-lock pathname is redirected into the temporary
    project. No condition, command or exit branch is removed or rewritten.
    """
    import tempfile
    root = Path(tempfile.mkdtemp(dir=tmp_path))
    scripts = root/'simulation/ros2_gazebo/scripts'
    scripts.mkdir(parents=True)
    chosen = PROFILES.get(settings.get('TFG_SIM_PROFILE'), TWO_DRONES)
    launch = root/'simulation/ros2_gazebo/launch'/chosen.launch_file
    launch.parent.mkdir(); launch.write_text('offline placeholder, never executed')
    script = scripts/('start_sim_backend.sh' if start else 'check_sim.sh')
    source = source.replace('/tmp/tfg_simulation_control.lock', str(root/'lifecycle.lock'))
    script.write_text(source)
    tools = root/'tools'; tools.mkdir()
    (tools/'__init__.py').touch()
    (tools/'prearm_diagnostics.py').write_bytes((ROOT/'tools/prearm_diagnostics.py').read_bytes())
    (tools/'simulation_profiles.py').write_text(
        catalog_source if catalog_source is not None else (ROOT/'tools/simulation_profiles.py').read_text())
    bin_dir = root/'bin'; bin_dir.mkdir()
    docker = bin_dir/'docker'
    docker.write_text(f'#!{sys.executable}\n' + _FAKE_DOCKER); docker.chmod(0o755)
    for name in ('sleep', 'flock'):
        p = bin_dir/name; p.write_text('#!/bin/sh\nexit 0\n'); p.chmod(0o755)
    verifier = root/'.venv/bin/python'; verifier.parent.mkdir(parents=True)
    verifier.write_text('#!/bin/sh\nif [ "$*" = "-m tools.simulation_lifecycle verify" ]; then exit 0; fi\nexec '+shlex.quote(sys.executable)+' "$@"\n')
    verifier.chmod(0o755)
    log = root/'calls.jsonl'
    # Minimal environment: no personal Docker settings or Python startup paths.
    env = {'PATH': str(bin_dir) + ':/usr/bin:/bin', 'OFFLINE_CALLS': str(log),
           'TFG_SIM_START_CONTEXT': json.dumps({'synthetic': 'offline backend propagation only'}),
           'TFG_SIM_GUI': 'true' if gui else 'false', 'OFFLINE_PORTS_LOG': str(root/'ports.json'), **settings}
    result = subprocess.run(['bash', str(script)], cwd=root, env=env,
                            capture_output=True, text=True, timeout=30)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert all(c[0] in {'inspect', 'start', 'cp', 'exec'} for c in calls)
    return result, calls, root


def _assert_backend(source, tmp_path):
    for gui in (False, True):
        result, calls, root = _run_shell(tmp_path, source, start=True, gui=gui)
        assert result.returncode == 0, result.stdout + result.stderr
        copies = [c[1:] for c in calls if c[0] == 'cp']
        package = TWO_DRONES.launch_package
        container = 'tfg-ardupilot-gazebo:'
        expected = [
            [str(root/'simulation/ros2_gazebo/scripts/sim_processes.py'), container+'/tmp/tfg_sim_processes.py'],
            [str(root/'tools/simulation_profiles.py'), container+'/tmp/tfg_simulation_profiles.py'],
            [str(root/'simulation/ros2_gazebo/launch'/TWO_DRONES.launch_file),
             container+f'/root/ardu_ws/src/ardupilot_gz/{package}/launch/{TWO_DRONES.launch_file}'],
            [str(root/'simulation/ros2_gazebo/launch'/TWO_DRONES.launch_file),
             container+f'/root/ardu_ws/install/{package}/share/{package}/launch/{TWO_DRONES.launch_file}'],
        ]
        assert sorted(copies) == sorted(expected)
        starts = [c for c in calls if c[0] == 'exec' and
                  'exec python3 /tmp/tfg_sim_processes.py start' in ' '.join(c)]
        assert len(starts) == 1
        assert starts[0][1:6] == ['-e', 'TFG_SIM_GUI='+('true' if gui else 'false'),
                                   '-e', 'TFG_SIM_PROFILE=two_drones', 'tfg-ardupilot-gazebo']
        assert json.loads((root/'ports.json').read_text())['ports'] == list(TWO_DRONES.sitl_ports_awaited_before_start)
        assert 'SIMULATION READY' in result.stdout
    # Both topic conditions must contribute to the actual successful branch.
    for topics in ('/ap/v1/status', '/ap/v2/status', ''):
        result, _, _ = _run_shell(tmp_path, source, start=True, OFFLINE_TOPICS=topics)
        assert result.returncode != 0
        assert 'SIMULATION READY' not in result.stdout


def _assert_readiness(source, tmp_path):
    result, calls, _ = _run_shell(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    world_calls = [c for c in calls if c[0] == 'exec' and any('pgrep -f' in p for p in c)]
    assert len(world_calls) == 1 and world_calls[0][-1] == TWO_DRONES.world
    payloads = [p for p in world_calls[0] if 'pgrep -f' in p]
    assert len(payloads) == 1
    payload = payloads[0]
    tokens = shlex.split(payload)
    assert tokens[:2] == ['pgrep', '-f']
    assert re.search(tokens[2].replace('${1}', TWO_DRONES.world), 'gz sim -s /catalog/worlds/'+TWO_DRONES.world+'.sdf')
    assert not re.search(tokens[2].replace('${1}', TWO_DRONES.world), 'gz sim -s /catalog/worlds/other.sdf')
    services = [c[-1] for c in calls if any('ros2 service call' in part for part in c)]
    assert len(services) == len(TWO_DRONES.prearm_services)
    for expected in TWO_DRONES.prearm_services:
        assert sum(expected in s for s in services) == 1
    # Failure injections exercise the real if/exit branches and their order.
    scenarios = [
        ({'OFFLINE_CONTAINER': '0'}, 'container'),
        ({'OFFLINE_GAZEBO': '0'}, 'gazebo'),
        ({'OFFLINE_COUNT': '1'}, 'count'),
        ({'OFFLINE_COUNT': '3'}, 'count'),
        ({'OFFLINE_TOPICS': '/ap/v1/status'}, 'topics'),
        ({'OFFLINE_TOPICS': '/ap/v2/status'}, 'topics'),
        *[({'OFFLINE_BAD_SERVICE': s}, 'prearm') for s in TWO_DRONES.prearm_services],
    ]
    for settings, stage in scenarios:
        result, calls, _ = _run_shell(tmp_path, source, **settings)
        assert result.returncode != 0, (stage, result.stdout)
        assert 'SIMULATION HEALTHY' not in result.stdout
        text = '\n'.join(' '.join(c) for c in calls)
        if stage == 'container':
            assert not any(c[0] == 'exec' for c in calls)
        if stage in {'container', 'gazebo'}:
            assert 'pgrep -x' not in text
        if stage in {'container', 'gazebo', 'count'}:
            assert 'ros2 topic list' not in text
        if stage != 'prearm':
            assert 'ros2 service call' not in text


def _assert_launch(source, profile=TWO_DRONES):
    for gui in (False, True):
        def include(location, **kwargs):
            return dict(kind='include', location=location,
                        arguments=dict(kwargs.get('launch_arguments', ())),
                        enabled=kwargs.get('condition', True))
        namespace = dict(
            Path=Path, Enum=Enum, LaunchContext=object,
            get_package_share_directory=lambda p: '/catalog/'+p,
            DeclareLaunchArgument=lambda *a, **k: dict(kind='declare', args=a, **k),
            IncludeLaunchDescription=include, PythonLaunchDescriptionSource=lambda p: p,
            LaunchDescription=lambda actions: actions, OpaqueFunction=lambda function: function,
            LaunchConfiguration=lambda n: {'gui': gui, 'rviz': False}[n],
            IfCondition=bool, PathJoinSubstitution=lambda parts: str(Path(*parts)),
            get_default_launch_arguments=lambda *a: {},
            Node=lambda **kwargs: dict(kind='node', **kwargs),
        )
        # Only local enum/data and launch factory; no ROS imports or child launch.
        tree = ast.parse(source)
        data = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Vehicle'
                or isinstance(n, ast.Assign) and any(getattr(t, 'id', None) == 'VEHICLE_PATHS' for t in n.targets)]
        exec(compile(ast.Module(body=data, type_ignores=[]), '<offline-launch-data>', 'exec'), namespace)
        factory = _function(source, 'generate_launch_description', namespace)
        actions = factory()[0](object())
        includes = [a for a in actions if a.get('kind') == 'include']
        gz = [a for a in includes if 'gz_args' in a['arguments']]
        assert len(gz) == 2
        server = next(a for a in gz if '-s' in shlex.split(a['arguments']['gz_args']))
        client = next(a for a in gz if '-g' in shlex.split(a['arguments']['gz_args']))
        assert shlex.split(server['arguments']['gz_args']) == [
            '-v4', '-s', '-r', '/catalog/ardupilot_gz_gazebo/worlds/'+profile.world+'.sdf']
        assert server['enabled'] is True
        assert shlex.split(client['arguments']['gz_args']) == ['-v1', '-g']
        assert client['enabled'] is gui
        robots = [a for a in includes if a not in gz]
        assert [(a['arguments']['robot_name'], a['arguments']['namespace'], a['arguments']['world_name'])
                for a in robots] == [(v.robot_name, v.robot_name, profile.world) for v in profile.vehicles]
        assert [(a['arguments']['instance'], a['arguments']['sysid']) for a in robots] == [(str(i), str(i+1)) for i in range(len(profile.vehicles))]
        for action, vehicle in zip(robots, profile.vehicles):
            model = getattr(namespace['Vehicle'], vehicle.launch_model)
            child = namespace['VEHICLE_PATHS'][model]['launch']
            assert action['location'] == [f'/catalog/{profile.launch_package}/launch/robots/{child}']
        assert all(a.get('condition') is False for a in actions if a.get('kind') == 'node')


def test_reference_catalog_and_bindings():
    assert set(PROFILES) == {'two_drones', 'two_drones_rover'} and ACTIVE_PROFILE is TWO_DRONES
    assert {v.sitl_executable for v in TWO_DRONES.vehicles} == dict(TWO_DRONES.expected_process_counts).keys()
    assert dict(TWO_DRONES.expected_process_counts) == {'arducopter': len(TWO_DRONES.vehicles)}
    for vehicle_id, interface in TWO_DRONES.bindings:
        assert selection.resolve_vehicle(vehicle_id).simulated_vehicle == interface
        assert selection.logical_vehicle_for_interface(interface) == vehicle_id
    with pytest.raises(selection.VehicleSelectionError):
        selection.validate_interface('v3')
    assert {s.split(':', 1)[0] for s in TWO_DRONES.unverified_offline} == {
        'robot_to_interface', 'sitl_ports', 'installed_launch', 'process_counts'}


def test_effective_popen_and_gui(tmp_path):
    _assert_popen(SIM_PROCESSES.read_text(), tmp_path)


def test_effective_copies_and_backend_gui(tmp_path):
    _assert_backend(START_BACKEND.read_text(), tmp_path)


def test_effective_launch_world_and_gui():
    _assert_launch(LAUNCH.read_text())


def test_effective_readiness_conditions_and_world(tmp_path):
    source = CHECK_SIM.read_text()
    _assert_readiness(source, tmp_path)


@pytest.mark.parametrize('old,new', [
    ('["ros2", "launch",', '["ros2", str(99), "launch",'),
    ('*selected.fixed_launch_arguments, "gui:=" + ("false" if os.environ.get("TFG_SIM_GUI") == "false" else "true")',
     '"rviz:=false", "gui:=true"'),
    ('*selected.fixed_launch_arguments,', '*selected.fixed_launch_arguments, "unexpected:=true",'),
])
def test_popen_mutations_are_rejected(tmp_path, old, new):
    source = SIM_PROCESSES.read_text(); assert old in source
    path = tmp_path/'mutant.py'; path.write_text(source.replace(old, new, 1))
    with pytest.raises(AssertionError):
        _assert_popen(path.read_text(), tmp_path)


@pytest.mark.parametrize('old,new', [
    ('"$HOST_LAUNCH" \\\n"$CONTAINER:$CONTAINER_INSTALL_LAUNCH"',
     '"$HOST_LAUNCH" \\\n"$CONTAINER:/wrong/tfg_demo_2drones.launch.py"'),
    ('docker cp \\\n"$HOST_LAUNCH" \\\n"$CONTAINER:$CONTAINER_SOURCE_LAUNCH" \\\n>/dev/null',
     ': # docker cp removed; declarations remain'),
    ('-e TFG_SIM_GUI="${TFG_SIM_GUI:-true}"', '-e TFG_SIM_GUI=true'),
    ('if [[ "$READY" -eq 1 ]]', 'if true'),
])
def test_backend_mutations_are_rejected(tmp_path, old, new):
    source = START_BACKEND.read_text(); assert old in source
    path = tmp_path/'mutant.sh'; path.write_text(source.replace(old, new, 1))
    with pytest.raises(AssertionError):
        _assert_backend(path.read_text(), tmp_path)


@pytest.mark.parametrize('old,new', [
    ('"runway.sdf"', '"other.sdf"'),
    ('condition=IfCondition(LaunchConfiguration("gui"))', 'condition=True'),
    ('"world_name": "runway"', '"world_name": "other"'),
    ('"name": "drone2"', '"name": "rover1"'),
    ('"model": Vehicle.IRIS,', '"model": Vehicle.IRIS_LIDAR,'),
])
def test_launch_mutations_are_rejected(tmp_path, old, new):
    source = LAUNCH.read_text(); assert old in source
    # The former text-only world test would still find this decoy comment.
    path = tmp_path/'mutant.py'
    path.write_text(source.replace(old, new, 1)+'\n# unused "runway.sdf"\n')
    with pytest.raises(AssertionError):
        _assert_launch(path.read_text())


@pytest.mark.parametrize('old,new', [
    ('"$SITL_COUNT" -ne "$EXPECTED_COUNT"', '"$SITL_COUNT" -ne 3'),
    ('"$SITL_COUNT" -ne "$EXPECTED_COUNT"', '"$SITL_COUNT" -ne 99'),
    ('${1}.sdf', 'other.sdf'),
    ('if [[ "$ALL_TOPICS" -eq 1 ]]', 'if true'),
    ('ALL_ARMABLE=0', 'ALL_ARMABLE=1'),
    ('exit 1', ': # removed effective failure exit'),
    ('if ! docker exec', 'if docker exec'),
])
def test_readiness_mutations_are_rejected(tmp_path, old, new):
    source = CHECK_SIM.read_text(); assert old in source
    path = tmp_path/'mutant.sh'
    path.write_text(source.replace(old, new, 1)+'\n# unrelated OTHER_COUNT" -ne 2 ]]\n')
    with pytest.raises(AssertionError):
        _assert_readiness(path.read_text(), tmp_path)


def test_equivalent_formatting_and_argument_order_are_accepted(tmp_path):
    # Change quoting and independent cp ordering, keeping command semantics.
    backend = START_BACKEND.read_text()
    first = 'docker cp \\\n"$HOST_LAUNCH" \\\n"$CONTAINER:$CONTAINER_SOURCE_LAUNCH" \\\n>/dev/null'
    second = first.replace('CONTAINER_SOURCE_LAUNCH', 'CONTAINER_INSTALL_LAUNCH')
    assert first in backend and second in backend
    backend = backend.replace(first, '__OFFLINE_COPY__').replace(second, first).replace('__OFFLINE_COPY__', second)
    backend = backend.replace('grep -qxF "$TOPIC"', 'grep -Fqx "$TOPIC"')
    _assert_backend(backend, tmp_path)
    readiness = CHECK_SIM.read_text().replace('"$SITL_COUNT" -ne "$EXPECTED_COUNT"', '${SITL_COUNT}   -ne   ${EXPECTED_COUNT}')
    readiness = readiness.replace('grep -qxF "$TOPIC"', 'grep -Fqx "$TOPIC"')
    _assert_readiness(readiness, tmp_path)
    process = SIM_PROCESSES.read_text()
    tree = ast.parse(process)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'start')
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == 'Popen')
    # Extract a local command variable while retaining every argument/expression.
    command = call.args[0]
    command.elts[-2:] = list(reversed(command.elts[-2:]))
    assign = ast.Assign(targets=[ast.Name(id='command', ctx=ast.Store())], value=command)
    call.args[0] = ast.Name(id='command', ctx=ast.Load())
    idx = next(i for i,n in enumerate(fn.body) if isinstance(n, ast.With))
    fn.body.insert(idx, assign)
    _assert_popen(ast.unparse(ast.fix_missing_locations(tree)), tmp_path)
    _assert_launch(ast.unparse(ast.parse(LAUNCH.read_text())))


@pytest.mark.parametrize('name', ['rover', 'three_vehicles', '../two_drones', 'two_drones;echo bad', '', None])
def test_unknown_profile_blocks_python_entries_before_operations(tmp_path, monkeypatch, name):
    from tools import simulation_lifecycle as lifecycle
    from tools import simulation_status as status
    backend = Mock(side_effect=AssertionError('no backend for unknown profile'))
    mutex = Mock(side_effect=AssertionError('no mutex files for unknown profile'))
    run = Mock(side_effect=AssertionError('no readiness process for unknown profile'))
    monkeypatch.setattr(lifecycle, '_backend', backend)
    monkeypatch.setattr(lifecycle.locks, 'file_mutex', mutex)
    monkeypatch.setattr(status.subprocess, 'run', run)
    for action in ('start', 'stop', 'restart'):
        assert lifecycle.run_lifecycle(action, profile=name)['status'] == 'BLOCKED'
    assert status.check_simulation_ready(profile=name)['status'] == 'BLOCKED'
    backend.assert_not_called(); mutex.assert_not_called(); run.assert_not_called()


@pytest.mark.parametrize('start', [False, True])
@pytest.mark.parametrize('name', ['rover', '', 'two_drones;echo bad'])
def test_unknown_profile_in_shell_has_no_docker_calls(tmp_path, start, name):
    source = START_BACKEND.read_text() if start else CHECK_SIM.read_text()
    result, calls, _ = _run_shell(tmp_path, source, start=start, TFG_SIM_PROFILE=name)
    assert result.returncode != 0
    assert 'Unknown simulation profile' in result.stderr
    assert calls == []


def test_supervisor_rejects_unknown_before_process_inspection_or_log_write(tmp_path, monkeypatch):
    import simulation.ros2_gazebo.scripts.sim_processes as supervisor
    scan = Mock(side_effect=AssertionError('unknown profile must not inspect/start'))
    monkeypatch.setattr(supervisor, 'snapshot', scan)
    monkeypatch.setattr(supervisor, 'LOG_FILE', tmp_path/'not-created.log')
    with pytest.raises(profiles.UnknownSimulationProfile):
        supervisor.start('rover')
    scan.assert_not_called()
    assert not (tmp_path/'not-created.log').exists()


def test_standalone_container_helper_receives_profile_without_project_imports(tmp_path):
    # Emulate the two files copied into /tmp in the container. Only --profile
    # rejection is executed: never calls the helper's process/control paths.
    import os
    (tmp_path/'tfg_sim_processes.py').write_bytes(SIM_PROCESSES.read_bytes())
    (tmp_path/'tfg_simulation_profiles.py').write_bytes((ROOT/'tools/simulation_profiles.py').read_bytes())
    launcher = "import runpy,sys; sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); sys.argv=[sys.argv[2],'start','--profile','rover']; runpy.run_path(sys.argv[0],run_name='__main__')"
    result = subprocess.run([sys.executable, '-I', '-S', '-c', launcher, str(tmp_path),
                             str(tmp_path/'tfg_sim_processes.py')], cwd=tmp_path,
                            env={'PATH':os.defpath}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)['success'] is False
    assert 'Unknown simulation profile' in result.stdout
    assert not (tmp_path/'tfg_demo.log').exists()


def test_supervisor_uses_selected_arguments_instead_of_old_literals(tmp_path, monkeypatch):
    from dataclasses import replace
    import simulation.ros2_gazebo.scripts.sim_processes as supervisor
    selected = replace(TWO_DRONES, fixed_launch_arguments=('rviz:=false', 'offline_sentinel:=yes'))
    lookup = Mock(return_value=selected)
    popen = Mock(return_value=SimpleNamespace(pid=123))
    monkeypatch.setattr(supervisor, 'get_profile', lookup)
    monkeypatch.setattr(supervisor, 'snapshot', lambda: {})
    monkeypatch.setattr(supervisor, 'remembered_identities', set)
    monkeypatch.setattr(supervisor, 'LOG_FILE', tmp_path/'log')
    monkeypatch.setattr(supervisor, 'PID_FILE', tmp_path/'pid')
    monkeypatch.setattr(supervisor, 'save_state', Mock())
    monkeypatch.setattr(supervisor.signal, 'signal', Mock())
    monkeypatch.setattr(supervisor.subprocess, 'Popen', popen)
    monkeypatch.setattr(supervisor, 'read_process', lambda pid:SimpleNamespace(identity=(pid,1),start_ticks=1))
    assert supervisor.start('two_drones')['success'] is True
    lookup.assert_called_once_with('two_drones')
    assert popen.call_args.args[0][4:6] == list(selected.fixed_launch_arguments)


def test_backend_consumes_ports_from_copied_catalog(tmp_path):
    catalog = (ROOT/'tools/simulation_profiles.py').read_text()
    assert '(5760, 5770)' in catalog
    result, _, root = _run_shell(tmp_path, START_BACKEND.read_text(), start=True,
                                catalog_source=catalog.replace('(5760, 5770)', '(5800, 5810)'))
    assert result.returncode == 0
    captured = json.loads((root/'ports.json').read_text())
    assert captured['ports'] == [5800, 5810]
    # Execute the actual port reader with synthetic proc files and environment.
    # No real /proc or socket reads, and no Docker/ROS subprocess.
    import contextlib
    import io
    from unittest.mock import patch
    raw = 'header\n0: 00000000:16A8 00000000:0000 0A\n'  # 5800 in hex
    with patch.dict('os.environ', {'TFG_SIM_PORTS':json.dumps(captured['ports'])}), \
         patch('builtins.open', side_effect=lambda *a,**k:io.StringIO(raw)), \
         contextlib.redirect_stdout(io.StringIO()) as output:
        exec(compile(captured['source'], '<offline-port-reader>', 'exec'), {})
    assert output.getvalue().strip() == '5800'


def test_readiness_consumes_catalog_count_topics_services_and_world(tmp_path):
    catalog = (ROOT/'tools/simulation_profiles.py').read_text()
    changed = catalog.replace('("arducopter", 2)', '("arducopter", 3)').replace(
        'world="runway"', 'world="offline_world"').replace(
        '"drone_01", "v1"', '"drone_01", "v9"')
    assert changed != catalog
    failed, _, _ = _run_shell(tmp_path, CHECK_SIM.read_text(), catalog_source=changed)
    assert failed.returncode != 0  # nominal fake count=2 is no longer sufficient
    ok, calls, _ = _run_shell(tmp_path, CHECK_SIM.read_text(), catalog_source=changed,
                             OFFLINE_COUNT='3', OFFLINE_TOPICS='/ap/v9/status\n/ap/v2/status')
    assert ok.returncode == 0, ok.stdout+ok.stderr
    assert any(c[-1]=='offline_world' and 'pgrep -f' in ' '.join(c) for c in calls)
    assert any(c[-1]=='/ap/v9/prearm_check' for c in calls)
    assert not any(c[-1]=='/ap/v1/prearm_check' for c in calls)


def test_lifecycle_default_records_profile_and_transmits_it_to_backend(tmp_path, monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    monkeypatch.setenv('TFG_SIM_PROFILE', 'rover')  # must not override explicit/validated default
    captured = []
    def run(args, **kwargs):
        captured.append((args, kwargs))
        assert (locks.LOCK_ROOT/'lifecycle.json').is_file()
        assert kwargs['env']['TFG_SIM_PROFILE'] == 'two_drones'
        with pytest.raises(locks.VehicleBusy):
            locks.reserve('offline-other', 'fixture', 'v1')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(lifecycle.subprocess, 'run', run)
    result = lifecycle.run_lifecycle('start', gui=False)
    assert result['success'] and result['operation']['profile'] == TWO_DRONES.name
    assert captured[0][1]['env']['TFG_SIM_GUI']=='false'
    assert locks.restriction() is None
    # The direct private backend cannot choose an arbitrary environment profile:
    # its source is the lease under the registry, not a caller command string.
    assert captured[0][1]['env']['TFG_SIM_PROFILE'] == 'two_drones'


def test_readiness_python_default_passes_explicit_profile(monkeypatch):
    from tools import simulation_status as status
    run = Mock(return_value=SimpleNamespace(returncode=0,stdout='offline ready',stderr=''))
    monkeypatch.setattr(status.subprocess, 'run', run)
    result = status.check_simulation_ready()
    assert result['ready'] and result['profile']=='two_drones'
    assert run.call_args.kwargs['env']['TFG_SIM_PROFILE']=='two_drones'


def test_backend_profile_must_match_protected_lease(monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    locks.LOCK_ROOT.mkdir(parents=True)
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json', {'profile':'different','process':{}})
    monkeypatch.setenv('TFG_LIFECYCLE_PROCESS','{}')
    monkeypatch.setenv('TFG_SIM_PROFILE','two_drones')
    with pytest.raises(locks.VehicleBusy,match='profile mismatch'):
        lifecycle.verify_backend()


def test_lifecycle_cli_unknown_profile_does_not_create_locks(monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    enter = Mock(side_effect=AssertionError('unknown profile entered lifecycle exclusion'))
    monkeypatch.setattr(lifecycle.locks, 'file_mutex', enter)
    monkeypatch.setattr(sys, 'argv', ['lifecycle', 'start', '--headless', '--profile', 'rover'])
    assert lifecycle.main() == 1
    enter.assert_not_called()


def test_rover_catalog_matches_historical_launch_and_is_infrastructure_only():
    profile = profiles.TWO_DRONES_ROVER
    assert dict(profile.expected_process_counts) == {'arducopter': 2, 'ardurover': 1}
    assert profile.sitl_ports_awaited_before_start == (5760, 5770, 5780)  # expected, not observed sockets
    assert profile.vehicles[-1].interface == 'v3'
    assert profile.vehicles[-1].mission_executor_supported is False
    _assert_launch((SIM/'launch'/profile.launch_file).read_text(), profile)
    for value in ['rover_01', 'rover1']:
        with pytest.raises(selection.VehicleSelectionError):
            selection.resolve_vehicle(value)
    with pytest.raises(selection.VehicleSelectionError):
        selection.validate_interface('v3')


@pytest.mark.parametrize('gui', [False,True])
def test_rover_backend_selects_copies_ports_and_all_topics(tmp_path, gui):
    result,calls,root = _run_shell(tmp_path, START_BACKEND.read_text(), start=True,gui=gui,
        TFG_SIM_PROFILE='two_drones_rover',OFFLINE_TOPICS='/ap/v1/status\n/ap/v2/status\n/ap/v3/status')
    assert result.returncode == 0, result.stdout+result.stderr
    copies=[c for c in calls if c[0]=='cp']
    assert sum(c[1].endswith('/tfg_demo.launch.py') for c in copies)==2
    assert any(c[2].endswith('/launch/tfg_demo.launch.py') for c in copies)
    assert json.loads((root/'ports.json').read_text())['ports']==[5760,5770,5780]
    start=[c for c in calls if 'exec python3 /tmp/tfg_sim_processes.py start' in ' '.join(c)]
    assert len(start)==1 and 'TFG_SIM_PROFILE=two_drones_rover' in start[0]
    assert 'TFG_SIM_GUI='+str(gui).lower() in start[0]
    failed,_,_=_run_shell(tmp_path,START_BACKEND.read_text(),start=True,TFG_SIM_PROFILE='two_drones_rover')
    assert failed.returncode != 0  # v1/v2 alone cannot complete a rover-profile start


@pytest.mark.parametrize('settings,passes',[
    ({},True),({'OFFLINE_ROVER_COUNT':'0'},False),({'OFFLINE_ROVER_COUNT':'2'},False),
    ({'OFFLINE_COUNT':'1'},False),({'OFFLINE_TOPICS':'/ap/v1/status\n/ap/v2/status'},False),
    ({'OFFLINE_BAD_SERVICE':'/ap/v3/prearm_check'},False),
])
def test_rover_readiness_effective_checks_and_structured_per_vehicle(tmp_path,settings,passes):
    from tools.simulation_status import _vehicle_checks
    opts={'TFG_SIM_PROFILE':'two_drones_rover','OFFLINE_TOPICS':'/ap/v1/status\n/ap/v2/status\n/ap/v3/status',**settings}
    result,calls,_=_run_shell(tmp_path,CHECK_SIM.read_text(),**opts)
    assert (result.returncode==0) is passes, result.stdout+result.stderr
    vehicles=_vehicle_checks(profiles.TWO_DRONES_ROVER,result.stdout)
    assert [v['interface'] for v in vehicles]==['v1','v2','v3']
    assert vehicles[2]['mission_executor_supported'] is False
    if passes:
        assert all(v['status_last_observed']==v['prearm_last_observed']=='PASS' for v in vehicles)
        assert any(c[-1]=='ardurover' for c in calls)
        assert any(c[-1]=='/ap/v3/prearm_check' for c in calls)
    if settings.get('OFFLINE_BAD_SERVICE'):
        assert vehicles[0]['prearm_last_observed']=='PASS'
        assert vehicles[2]['prearm_last_observed']=='FAIL'


def test_rover_profile_consumed_by_supervisor_and_protected_lifecycle(tmp_path,monkeypatch):
    import simulation.ros2_gazebo.scripts.sim_processes as supervisor
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    monkeypatch.setattr(supervisor,'snapshot',lambda:{})
    monkeypatch.setattr(supervisor,'remembered_identities',set)
    monkeypatch.setattr(supervisor,'LOG_FILE',tmp_path/'launch.log')
    monkeypatch.setattr(supervisor,'PID_FILE',tmp_path/'pid')
    monkeypatch.setattr(supervisor,'save_state',Mock())
    monkeypatch.setattr(supervisor.signal,'signal',Mock())
    popen=Mock(return_value=SimpleNamespace(pid=900))
    monkeypatch.setattr(supervisor.subprocess,'Popen',popen)
    monkeypatch.setattr(supervisor,'read_process',lambda p:SimpleNamespace(identity=(p,88),start_ticks=88))
    passive = Mock(return_value={'scope':'READ_ONLY_IDENTITY_NOT_MOVEMENT'})
    monkeypatch.setattr(supervisor,'start_rover_identity',passive)
    supervisor.start('two_drones_rover')
    passive.assert_called_once()
    assert popen.call_args.args[0][:4]==['ros2','launch','ardupilot_gz_bringup','tfg_demo.launch.py']
    phases=[]
    def backend(action,gui,fd,process,log):
        lease=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        assert lease['profile']=='two_drones_rover' and lease['movement_authorized'] is False
        with pytest.raises(locks.VehicleBusy):locks.reserve('foreign','fixture','v1')
        phases.append(action);return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    assert lifecycle.run_lifecycle('start',profile='two_drones_rover')['success']
    assert lifecycle.run_lifecycle('stop',profile='two_drones_rover')['success']
    assert phases==['start','stop'] and locks.restriction() is None


def test_rover_mission_is_blocked_before_any_executor_or_reservation(monkeypatch):
    from tools import simulation_mission_executor as executor
    mission=SimpleNamespace(vehicle=SimpleNamespace(vehicle_id='rover_01'))
    monkeypatch.setattr(executor,'load_mission_json',lambda path:mission)
    control=Mock(side_effect=AssertionError('No rover execution'))
    monkeypatch.setattr(executor,'_execute_resolved_mission',control)
    result=executor.execute_approved_mission('offline-rover.json',vehicle='v3')
    assert result['status']=='BLOCKED' and result['stage']=='VEHICLE_SELECTION'
    control.assert_not_called()


def test_rover_timeout_retains_only_explicit_per_vehicle_observations(monkeypatch):
    from tools import simulation_status as status
    run=Mock(side_effect=subprocess.TimeoutExpired('fake',180,output=
        b'TFG_READINESS_VEHICLE /ap/v1 status PASS\nTFG_READINESS_VEHICLE /ap/v2 status PASS\n[5/5] Pre-arm checks...\n'))
    monkeypatch.setattr(status.subprocess,'run',run)
    result=status.check_simulation_ready('two_drones_rover')
    assert result['ready'] is False and result['timed_out']
    assert result['vehicles'][2]['status_last_observed']=='NOT_OBSERVED'
    assert all(v['prearm_last_observed']=='NOT_OBSERVED' for v in result['vehicles'])
    assert result['movement_authorized'] is False
    assert run.call_args.kwargs['env']['TFG_SIM_PROFILE']=='two_drones_rover'


def test_rover_lifecycle_cannot_bypass_uncertain_drone_reservation(monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    locks.reserve('uncertain-owner','fixture','v2')
    record=json.loads((locks.LOCK_ROOT/'v2.json').read_text())
    locks.atomic_json(locks.LOCK_ROOT/'v2.json',{**record,'state':'UNCONFIRMED'})
    backend=Mock(side_effect=AssertionError('Do not touch simulator'))
    monkeypatch.setattr(lifecycle,'_backend',backend)
    for action in ('start','stop','restart'):
        assert lifecycle.run_lifecycle(action,profile='two_drones_rover')['status']=='BLOCKED'
    backend.assert_not_called()
    assert json.loads((locks.LOCK_ROOT/'v2.json').read_text())['state']=='UNCONFIRMED'
