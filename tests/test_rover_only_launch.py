"""rover_only launch: one DDS agent on UDP 2019, rover identity kept. Static analysis only (no ROS on host)."""
import ast
from pathlib import Path

import pytest

from tools.rover_xrce_trace import present_resources
from tools.simulation_profiles import get_profile

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / 'simulation/ros2_gazebo/launch/tfg_rover_only.launch.py'
TREE = ast.parse(LAUNCH.read_text())


def constants():
    names = {}
    for node in TREE.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                names[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return names


def pure_functions():
    namespace = {}
    for node in TREE.body:
        keep = (isinstance(node, ast.FunctionDef) and node.name in {'dds_udp_port', 'require_matching_dds_port'}
                or isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in {'DDS_AGENT_PORT', 'DDS_PARAMS'}
                                                         for t in node.targets))
        if keep:
            exec(compile(ast.Module([node], []), str(LAUNCH), 'exec'), namespace)
    return namespace


def includes():
    """(target file, launch_arguments dict as source text keys -> source text values) per include."""
    found = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'IncludeLaunchDescription':
            target = next((name for name in ('micro_ros_agent.launch.py', 'robot.launch.py', 'gz_sim.launch.py',
                                             'sitl_dds_udp.launch.py', 'wildthumper.launch.py')
                           if name in ast.unparse(node.args[0])), None)
            arguments = {}
            for keyword in node.keywords:
                if keyword.arg == 'launch_arguments':
                    mapping = keyword.value.func.value
                    arguments = {ast.literal_eval(k): ast.unparse(v) for k, v in zip(mapping.keys, mapping.values)}
            found.append((target, arguments))
    return found


C = constants()


def by_target(name):
    return [args for target, args in includes() if target == name]


def test_exactly_one_dds_agent_on_udp_2019_for_rover1():
    agents = by_target('micro_ros_agent.launch.py')
    assert C['DDS_AGENT_PORT'] == '2019' and len(agents) == 1
    assert agents[0] == {'micro_ros_agent_ns': 'ROBOT_NAME', 'transport': "'udp4'", 'port': 'DDS_AGENT_PORT'}
    assert by_target('sitl_dds_udp.launch.py') == [] and by_target('wildthumper.launch.py') == []


def test_robot_does_not_start_its_own_agent_and_keeps_instance_2_sysid_3():
    robots = by_target('robot.launch.py')
    assert len(robots) == 1
    robot = robots[0]
    assert robot['use_dds_agent'] == "'False'"
    assert robot['instance'] == 'INSTANCE' and robot['sysid'] == 'SYSID'
    assert robot['namespace'] == robot['robot_name'] == 'ROBOT_NAME' and robot['command'] == "'ardurover'"
    assert (C['INSTANCE'], C['SYSID'], C['ROBOT_NAME']) == ('2', '3', 'rover1')
    assert len(by_target('gz_sim.launch.py')) == 2  # server + optional GUI


def test_identity_ports_match_profile_and_resource_scope():
    # Same offsets as the installed robot.launch.py: 5760/5501/9002 + 10*instance.
    offset = 10 * int(C['INSTANCE'])
    master, rc, fdm = 5760 + offset, 5501 + offset, 9002 + offset
    rover = get_profile('rover_only')
    assert rover.sitl_ports_awaited_before_start == (master,) == (5780,)
    assert rover.bindings == (('rover_01', 'v3'),) and rover.status_topics == ('/ap/v3/status',)
    assert rover.expected_process_counts == (('ardurover', 1),)
    endpoints = {(e['protocol'], e['port']): e['role'] for e in present_resources.expected_scope()['endpoints']}
    assert endpoints[('tcp', master)].startswith('rover1') and endpoints[('udp', rc)].startswith('rover1')
    assert endpoints[('udp', fdm)].startswith('rover1')
    assert endpoints[('udp', int(C['DDS_AGENT_PORT']))] == 'single micro_ros_agent udp4'


@pytest.mark.parametrize('texts', [['DDS_ENABLE 1\nDDS_UDP_PORT 2019\n'],
                                   ['SERIAL0_BAUD 115', 'DDS_ENABLE 1\nDDS_UDP_PORT 2019']])
def test_matching_dds_port_is_accepted(texts):
    pure_functions()['require_matching_dds_port'](texts)


@pytest.mark.parametrize('texts', [['DDS_UDP_PORT 2039'], ['DDS_ENABLE 1'], [],
                                   ['DDS_UDP_PORT 2019', 'DDS_UDP_PORT 2019'],
                                   ['DDS_UDP_PORT 2019\nDDS_UDP_PORT 2039'], ['DDS_UDP_PORT']])
def test_mismatched_absent_or_ambiguous_dds_port_fails_the_launch(texts):
    with pytest.raises(RuntimeError, match='rover_only DDS mismatch'):
        pure_functions()['require_matching_dds_port'](texts)


def test_launch_checks_the_same_parameter_files_it_passes_as_defaults():
    source = LAUNCH.read_text()
    assert C['DDS_PARAMS'] == ('rover.parm', 'rover-skid.parm', 'dds_udp.parm', 'dds_use_ns.parm')
    check = source.index('require_matching_dds_port([(params / name).read_text() for name in DDS_PARAMS])')
    assert check < source.index('defaults = ",".join(str(params / name) for name in DDS_PARAMS)')


def test_existing_profiles_and_their_shared_agent_scheme_are_unchanged():
    two, three = get_profile('two_drones'), get_profile('two_drones_rover')
    assert (two.launch_file, three.launch_file) == ('tfg_demo_2drones.launch.py', 'tfg_demo.launch.py')
    assert two.bindings == (('drone_01', 'v1'), ('drone_02', 'v2'))
    assert three.bindings == (('drone_01', 'v1'), ('drone_02', 'v2'), ('rover_01', 'v3'))
    for name in ('tfg_demo.launch.py', 'tfg_demo_2drones.launch.py'):
        text = (ROOT/'simulation/ros2_gazebo/launch'/name).read_text()
        assert 'if instance > 0:' in text and '"use_dds_agent": "False"' in text
