# TFG Command Cheatsheet

## Start Docker container

From WSL:

```bash
docker ps -a --filter name=tfg-ardupilot-gazebo
docker start -ai tfg-ardupilot-gazebo
```

Alternative:

```bash
docker start tfg-ardupilot-gazebo
docker exec -it tfg-ardupilot-gazebo bash
```

## Load ROS 2 environment

Inside the container:

```bash
cd ~/ardu_ws
source /opt/ros/humble/setup.bash
source ~/ardu_ws/install/setup.bash
```

## Gazebo / WSL environment

```bash
export GZ_VERSION=harmonic

mkdir -p /tmp/runtime-root
chmod 700 /tmp/runtime-root
export XDG_RUNTIME_DIR=/tmp/runtime-root

export QT_QPA_PLATFORM=xcb
export QT_X11_NO_MITSHM=1

export LD_LIBRARY_PATH="/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"

export SDF_PATH="/root/ardu_ws/install/ardupilot_gazebo/share:${GZ_SIM_RESOURCE_PATH:-}"
```

## Start stable simulation

```bash
ros2 launch ardupilot_gz_bringup tfg_demo.launch.py \
  rviz:=false \
  gui:=true
```

## Open control terminal

```bash
docker exec -it tfg-ardupilot-gazebo bash
```

Then:

```bash
cd ~/ardu_ws
source /opt/ros/humble/setup.bash
source ~/ardu_ws/install/setup.bash
```

## Vehicle aliases

```bash
export DRONE1_AP=/ap/v1
export DRONE2_AP=/ap/v2
export ROVER_AP=/ap/v3
```

## Check autopilot processes

```bash
ps -ef | grep -E "arducopter|ardurover|arduplane" | grep -v grep
```

Expected:

```text
2 x arducopter
1 x ardurover
0 x arduplane
```

## Check status topics

```bash
ros2 topic list | grep '/status$' | sort
```

## Check pre-arm services

```bash
ros2 service list | grep '/prearm_check$' | sort
```

## Drone 1 pre-arm

```bash
ros2 service call \
  "$DRONE1_AP/prearm_check" \
  std_srvs/srv/Trigger \
  "{}"
```

## Drone 2 pre-arm

```bash
ros2 service call \
  "$DRONE2_AP/prearm_check" \
  std_srvs/srv/Trigger \
  "{}"
```

## ArduCopter GUIDED mode

Mode number:

```text
4
```

Drone 1:

```bash
ros2 service call \
  "$DRONE1_AP/mode_switch" \
  ardupilot_msgs/srv/ModeSwitch \
  "{mode: 4}"
```

Drone 2:

```bash
ros2 service call \
  "$DRONE2_AP/mode_switch" \
  ardupilot_msgs/srv/ModeSwitch \
  "{mode: 4}"
```

## Arm Drone 1

```bash
ros2 service call \
  "$DRONE1_AP/arm_motors" \
  ardupilot_msgs/srv/ArmMotors \
  "{arm: true}"
```

## Arm Drone 2

```bash
ros2 service call \
  "$DRONE2_AP/arm_motors" \
  ardupilot_msgs/srv/ArmMotors \
  "{arm: true}"
```

## Takeoff Drone 1 to 5 m

```bash
ros2 service call \
  "$DRONE1_AP/experimental/takeoff" \
  ardupilot_msgs/srv/Takeoff \
  "{alt: 5.0}"
```

## Takeoff Drone 2 to 7 m

```bash
ros2 service call \
  "$DRONE2_AP/experimental/takeoff" \
  ardupilot_msgs/srv/Takeoff \
  "{alt: 7.0}"
```

## Check altitude

```bash
ros2 topic echo "$DRONE1_AP/pose/filtered" --once
ros2 topic echo "$DRONE2_AP/pose/filtered" --once
```

Relevant field:

```text
pose.position.z
```

## Rover pre-arm

```bash
ros2 service call \
  "$ROVER_AP/prearm_check" \
  std_srvs/srv/Trigger \
  "{}"
```

## Rover GUIDED mode

Mode number:

```text
15
```

```bash
ros2 service call \
  "$ROVER_AP/mode_switch" \
  ardupilot_msgs/srv/ModeSwitch \
  "{mode: 15}"
```

## Arm Rover

```bash
ros2 service call \
  "$ROVER_AP/arm_motors" \
  ardupilot_msgs/srv/ArmMotors \
  "{arm: true}"
```

## Check Rover cmd_vel subscriber

```bash
ros2 topic info "$ROVER_AP/cmd_vel" -v
```

Expected:

```text
Subscription count: 1
```

## Move Rover

```bash
timeout 30s ros2 topic pub -r 10 \
  "$ROVER_AP/cmd_vel" \
  geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: 'base_link'}, twist: {linear: {x: 0.5, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}}"
```

## Stop Rover

```bash
ros2 topic pub --once \
  "$ROVER_AP/cmd_vel" \
  geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: 'base_link'}, twist: {linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}}"
```

## LAND Drone 1

ArduCopter LAND mode is:

```text
9
```

```bash
ros2 service call \
  "$DRONE1_AP/mode_switch" \
  ardupilot_msgs/srv/ModeSwitch \
  "{mode: 9}"
```

## LAND Drone 2

```bash
ros2 service call \
  "$DRONE2_AP/mode_switch" \
  ardupilot_msgs/srv/ModeSwitch \
  "{mode: 9}"
```

## Disarm Rover

```bash
ros2 service call \
  "$ROVER_AP/arm_motors" \
  ardupilot_msgs/srv/ArmMotors \
  "{arm: false}"
```

## Performance

From the WSL host:

```bash
docker stats --no-stream tfg-ardupilot-gazebo
```

## Stop simulation

In the terminal running the ROS 2 launch:

```text
Ctrl+C
```

Then:

```bash
exit
```

Check the container:

```bash
docker ps -a --filter name=tfg-ardupilot-gazebo
```

If still running:

```bash
docker stop tfg-ardupilot-gazebo
```
