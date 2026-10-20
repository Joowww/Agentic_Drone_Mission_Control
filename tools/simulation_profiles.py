"""Trusted two-drone settings consumed by lifecycle, backend and readiness.

No operations on import. Only the built-in profile is selectable; this module
never accepts launch paths, commands or vehicle definitions from the caller.
Robot topology/world construction still lives in the ROS launch and is checked
for drift offline. Rover support requires a separate safety/integration review.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileVehicle:
    vehicle_id: str  # logical id, as in tools.simulated_vehicle
    interface: str  # AP_DDS interface name under /ap/
    robot_name: str  # Gazebo model/ROS namespace in the launch file
    launch_model: str  # Vehicle enum member in the launch file
    sitl_executable: str


@dataclass(frozen=True)
class SimulationProfile:
    name: str
    launch_package: str
    launch_file: str
    fixed_launch_arguments: tuple[str, ...]
    world: str
    vehicles: tuple[ProfileVehicle, ...]
    sitl_ports_awaited_before_start: tuple[int, ...]
    expected_process_counts: tuple[tuple[str, int], ...]
    # Facts that only a running simulation can confirm; never asserted offline.
    unverified_offline: tuple[str, ...]

    @property
    def status_topics(self) -> tuple[str, ...]:
        return tuple(f"/ap/{v.interface}/status" for v in self.vehicles)

    @property
    def prearm_services(self) -> tuple[str, ...]:
        return tuple(f"/ap/{v.interface}/prearm_check" for v in self.vehicles)

    @property
    def bindings(self) -> tuple[tuple[str, str], ...]:
        return tuple((v.vehicle_id, v.interface) for v in self.vehicles)


TWO_DRONES = SimulationProfile(
    name="two_drones",
    launch_package="ardupilot_gz_bringup",
    launch_file="tfg_demo_2drones.launch.py",
    fixed_launch_arguments=("rviz:=false",),  # gui:= is chosen per start request
    world="runway",
    vehicles=(
        ProfileVehicle("drone_01", "v1", "drone1", "IRIS", "arducopter"),
        ProfileVehicle("drone_02", "v2", "drone2", "IRIS", "arducopter"),
    ),
    sitl_ports_awaited_before_start=(5760, 5770),
    expected_process_counts=(("arducopter", 2),),
    unverified_offline=(
        "robot_to_interface: drone1->v1 and drone2->v2 follow launch order "
        "(sysid = index + 1) and upstream dds_use_ns.parm inside the container",
        "sitl_ports: that instances 0/1 bind 5760/5770 depends on the installed "
        "ArduPilot SITL; the repository only records which ports it awaits",
        "installed_launch: the container copy is overwritten from the host file "
        "at start; its content is not inspected offline",
        "process_counts: readiness counts arducopter processes at runtime only",
    ),
)

PROFILES = {TWO_DRONES.name: TWO_DRONES}
ACTIVE_PROFILE = TWO_DRONES


class UnknownSimulationProfile(ValueError):
    pass


def get_profile(name: str = "two_drones") -> SimulationProfile:
    if not isinstance(name, str) or name not in PROFILES:
        raise UnknownSimulationProfile(f"Unknown simulation profile: {name!r}; expected two_drones")
    return PROFILES[name]


def main():
    """Emit data fields, never shell source or commands."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='two_drones')
    parser.add_argument('field', choices=('launch-package', 'launch-file', 'ports-json',
                                        'status-topics', 'prearm-services', 'process-check', 'world'))
    args = parser.parse_args()
    try:
        profile = get_profile(args.profile)
    except UnknownSimulationProfile as exc:
        parser.error(str(exc))
    values = {
        'launch-package': profile.launch_package,
        'launch-file': profile.launch_file,
        'ports-json': json.dumps(profile.sitl_ports_awaited_before_start),
        'status-topics': '\n'.join(profile.status_topics),
        'prearm-services': '\n'.join(profile.prearm_services),
        'process-check': ' '.join(str(v) for v in profile.expected_process_counts[0]),
        'world': profile.world,
    }
    print(values[args.field])


if __name__ == '__main__':
    main()
