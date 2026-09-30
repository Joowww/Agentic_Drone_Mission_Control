from agents.mission_editor import (
    parse_mission_update,
)
from editing.mission_update_service import (
    apply_mission_update,
)
from graph.waypoint_mission_graph import (
    waypoint_mission_graph,
)
from inputs.json_saver import (
    save_mission_json,
)
from models.mission_definition import (
    MissionDefinition,
)


def evaluate_structured_mission(
    mission: MissionDefinition,
) -> None:
    print(
        "\n[LANGGRAPH] Running waypoint "
        "mission graph..."
    )

    final_state = (
        waypoint_mission_graph.invoke(
            {
                "mission": mission,
            }
        )
    )

    print(
        "\nAGENT:"
    )

    print(
        final_state[
            "final_report"
        ]
    )


def print_structured_mission_help() -> None:
    print(
        "\nMISSION COMMANDS"
    )

    print(
        "\nWrite a natural-language instruction "
        "to modify the mission."
    )

    print(
        "\nExamples:"
    )

    print(
        "  Change the battery to 70%."
    )

    print(
        "  Set WP2 altitude to 80 meters."
    )

    print(
        "  Set the wind to 18 km/h "
        "coming from the west."
    )

    print(
        "  Add WP4 at latitude 41.2, "
        "longitude 1.9, altitude 30 meters."
    )

    print(
        "\nCommands:"
    )

    print(
        "  show   - show current mission"
    )

    print(
        "  report - validate mission again"
    )

    print(
        "  save   - save current mission"
    )

    print(
        "  reset  - restore session mission"
    )

    print(
        "  help   - show commands"
    )

    print(
        "  menu   - return to main menu"
    )

    print(
        "  exit   - close program"
    )


def run_structured_mission_session(
    mission: MissionDefinition,
) -> bool:
    original_mission = (
        mission.model_copy(
            deep=True
        )
    )

    evaluate_structured_mission(
        mission
    )

    print_structured_mission_help()

    while True:
        try:
            user_input = input(
                "\nYou: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            return False

        if not user_input:
            continue

        command = user_input.lower()

        if command in {
            "exit",
            "quit",
            "salir",
        }:
            return False

        if command == "menu":
            return True

        if command == "help":
            print_structured_mission_help()

            continue

        if command == "show":
            print(
                "\nCURRENT MISSION JSON"
            )

            print(
                mission.model_dump_json(
                    indent=4
                )
            )

            continue

        if command == "report":
            evaluate_structured_mission(
                mission
            )

            continue

        if command == "reset":
            mission = (
                original_mission.model_copy(
                    deep=True
                )
            )

            print(
                "\nMission restored."
            )

            evaluate_structured_mission(
                mission
            )

            continue

        if (
            command == "save"
            or command.startswith(
                "save "
            )
        ):
            parts = user_input.split(
                maxsplit=1
            )

            if len(parts) == 2:
                save_path = (
                    parts[1].strip()
                )

            else:
                save_path = (
                    "missions/edited/"
                    f"{mission.mission_id}.json"
                )

            try:
                saved_path = (
                    save_mission_json(
                        mission,
                        save_path,
                    )
                )

            except Exception as error:  # noqa: BLE001
                print(
                    "\n[SAVE ERROR]"
                )

                print(
                    error
                )

                continue

            print(
                "\nMission saved successfully:"
            )

            print(
                saved_path
            )

            continue

        try:
            update = parse_mission_update(
                user_input=user_input,
                mission=mission,
            )

            updated_mission, changes = (
                apply_mission_update(
                    mission=mission,
                    update=update,
                )
            )

        except Exception as error:  # noqa: BLE001
            print(
                "\n[MISSION UPDATE REJECTED]"
            )

            print(
                error
            )

            continue

        if not changes:
            print(
                "\nNo mission modification "
                "was detected."
            )

            continue

        mission = updated_mission

        print(
            "\n[MISSION UPDATE] "
            "Applied successfully."
        )

        for change in changes:
            print(
                f"- {change}"
            )

        print(
            "\n[LANGGRAPH] "
            "Re-evaluating mission..."
        )

        final_state = (
            waypoint_mission_graph.invoke(
                {
                    "mission":
                        mission,
                }
            )
        )

        print(
            "\nAGENT:"
        )

        print(
            final_state[
                "final_report"
            ]
        )