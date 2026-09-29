from agents.mission_parser import parse_mission


def main() -> None:
    user_input = (
    "Plan an 8 km flight with a heading of 135 degrees. "
    "The drone airspeed is 35 km/h. "
    "There is a 18 km/h wind coming from the west. "
    "The battery is currently at 65%. "
    "Maximum safe wind speed is 25 km/h. "
    "Battery consumption is 0.8% per minute "
    "and the required reserve is 15%."
)

    result = parse_mission(
        user_input
    )

    print(
        "\nPARSED MISSION"
    )

    print(
        result
    )


if __name__ == "__main__":
    main()