"""Launch a single ArduRover (rover1) in the runway world, without the lidar.

Lightweight profile for ground navigation work. Differences from tfg_demo.launch.py:

- Only rover1 is spawned; no drones.
- The plain ``wildthumper`` model is used instead of ``wildthumper_with_lidar``.
  The two SDF files differ only in the ``gpu_lidar`` sensor, which is not needed
  for position, odometry, navigation or safety checks. The IMU, navsat,
  magnetometer, odometry publisher and ArduPilot plugin are identical.
- instance=2 and sysid=3 are kept explicitly, so the identity is unchanged:
  AP_DDS namespace /ap/v3, ROS namespace /rover1, Gazebo model rover1,
  SITL primary tcp 5780, RC udp 5521, FDM udp 9022.
- The rover is the only vehicle, so this file launches the single micro_ros_agent
  itself on UDP 2019. robot.launch.py would put its agent on 2019 + 10*instance
  (2039 for instance 2), while ArduRover sends DDS to DDS_UDP_PORT 2019 from
  dds_udp.parm. As for instances 1 and 2 in tfg_demo.launch.py, the robot is
  launched with use_dds_agent False, so only one agent exists.

Installed package files are not modified; the SDF substitutions mirror the
installed robots/wildthumper.launch.py.
"""
import os
import tempfile
from pathlib import Path

from ament_index_python.packages import get_package_share_directory

from launch import LaunchContext
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.actions import OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

ROBOT_NAME = "rover1"
INSTANCE = "2"
SYSID = "3"
POSITION = ("0.0", "-3.0", "0.195", "0", "0", "1.5708")  # same spawn as tfg_demo.launch.py
DDS_AGENT_PORT = "2019"  # must equal DDS_UDP_PORT in the dds_udp.parm loaded by the rover
DDS_PARAMS = ("rover.parm", "rover-skid.parm", "dds_udp.parm", "dds_use_ns.parm")


def dds_udp_port(parm_text):
    """DDS_UDP_PORT declared in an ArduPilot .parm text; None when absent or ambiguous."""
    values = [line.split()[1] for line in parm_text.splitlines()
              if len(line.split()) >= 2 and line.split()[0] == "DDS_UDP_PORT"]
    return values[0] if len(values) == 1 else None


def require_matching_dds_port(parm_texts):
    """Fail the launch at once instead of waiting for /ap/v3 that can never appear."""
    declared = [port for port in (dds_udp_port(text) for text in parm_texts) if port is not None]
    if declared != [DDS_AGENT_PORT]:
        raise RuntimeError(
            f"rover_only DDS mismatch: agent UDP {DDS_AGENT_PORT}, rover DDS_UDP_PORT {declared or 'absent'}")


def generate_launch_description():
    """Generate a launch description for one lidar-free wild thumper rover."""
    pkg_project_bringup = get_package_share_directory("ardupilot_gz_bringup")
    pkg_project_gazebo = get_package_share_directory("ardupilot_gz_gazebo")
    pkg_ros_gz_sim = get_package_share_directory("ros_gz_sim")
    pkg_ardupilot_sitl = get_package_share_directory("ardupilot_sitl")
    pkg_models = get_package_share_directory("ardupilot_sitl_models")

    def generate_launch_actions(context: LaunchContext, *args, **kwargs):
        sdf_file = os.path.join(pkg_models, "models", "wildthumper", "model.sdf")
        with open(sdf_file, "r") as infp:
            robot_desc = infp.read()
        robot_desc = robot_desc.replace(
            "model://wildthumper", "package://ardupilot_sitl_models/models/wildthumper"
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sdf") as modified:
            modified.write(robot_desc)

        params = Path(pkg_ardupilot_sitl) / "config" / "default_params"
        require_matching_dds_port([(params / name).read_text() for name in DDS_PARAMS])
        defaults = ",".join(str(params / name) for name in DDS_PARAMS)
        x, y, z, roll, pitch, yaw = POSITION
        robot = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                f'{Path(pkg_project_bringup) / "launch" / "robots" / "robot.launch.py"}'
            ),
            launch_arguments={
                "namespace": ROBOT_NAME,
                "use_gz_tf": "true",
                "sdf_file": modified.name,
                "bridge_config_file": str(
                    Path(pkg_project_bringup) / "config" / "wildthumper_bridge.yaml"
                ),
                "command": "ardurover",
                "robot_name": ROBOT_NAME,
                "world_name": "runway",
                "model": "json",
                "defaults": defaults,
                "synthetic_clock": "True",
                "sim_address": "127.0.0.1",
                "x": x, "y": y, "z": z, "R": roll, "P": pitch, "Y": yaw,
                "instance": INSTANCE,
                "sysid": SYSID,
                "use_instance_dir": "True",
                "use_dds_agent": "False",
            }.items(),
        )
        return [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(f'{Path(pkg_ros_gz_sim) / "launch" / "gz_sim.launch.py"}'),
                launch_arguments={
                    "gz_args": f'-v4 -s -r {Path(pkg_project_gazebo) / "worlds" / "runway.sdf"}'
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(f'{Path(pkg_ros_gz_sim) / "launch" / "gz_sim.launch.py"}'),
                launch_arguments={"gz_args": "-v1 -g"}.items(),
                condition=IfCondition(LaunchConfiguration("gui")),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    f'{Path(pkg_ardupilot_sitl) / "launch" / "micro_ros_agent.launch.py"}'
                ),
                launch_arguments={
                    "micro_ros_agent_ns": ROBOT_NAME,
                    "transport": "udp4",
                    "port": DDS_AGENT_PORT,
                }.items(),
            ),
            robot,
        ]

    return LaunchDescription([
        DeclareLaunchArgument("rviz", default_value="false", description="Unused; kept for the profile arguments."),
        DeclareLaunchArgument("gui", default_value="true", description="Run the Gazebo GUI client."),
        OpaqueFunction(function=generate_launch_actions),
    ])
