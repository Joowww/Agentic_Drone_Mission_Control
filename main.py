from agents.mission_editor import (
    parse_mission_update,
)
from editing.mission_update_service import (
    apply_mission_update,
)
from graph.mission_graph import (
    memory,
    mission_graph,
)
from graph.waypoint_mission_graph import (
    waypoint_mission_graph,
)
from inputs.json_loader import (
    load_mission_json,
)
from inputs.json_saver import (
    save_mission_json,
)

NATURAL_LANGUAGE_THREAD_ID = (
    "natural-language-mission-session"
)


NATURAL_LANGUAGE_CONFIG = {
    "configurable": {
        "thread_id":
            NATURAL_LANGUAGE_THREAD_ID,
    }
}


def print_main_menu() -> None:
    print(
        "\n"
        "AGENTIC DRONE MISSION CONTROL"
    )

    print(
        "\nChoose mission input:"
    )

    print(
        "\n1. Natural language mission"
    )

    print(
        "2. JSON mission"
    )

    print(
        "3. Exit"
    )


def run_natural_language_mission() -> bool:
    memory.delete_thread(
        NATURAL_LANGUAGE_THREAD_ID
    )

    print(
        "\nNATURAL LANGUAGE MISSION"
    )

    print(
        "\nDescribe the drone mission."
    )

    print(
        "You can update mission parameters "
        "in later messages."
    )

    print(
        "Write 'reset' to start a new mission."
    )

    print(
        "Write 'menu' to return to the main menu."
    )

    print(
        "Write 'exit' to close the program."
    )

    while True:
        try:
            user_input = input(
                "\nYou: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            print(
                "\nClosing Agentic Drone "
                "Mission Control..."
            )

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

        if command == "reset":
            memory.delete_thread(
                NATURAL_LANGUAGE_THREAD_ID
            )

            print(
                "\nMission reset."
            )

            continue

        print(
            "\n[LANGGRAPH] Running "
            "mission graph..."
        )

        try:
            final_state = (
                mission_graph.invoke(
                    {
                        "user_input":
                            user_input,
                    },
                    config=(
                        NATURAL_LANGUAGE_CONFIG
                    ),
                )
            )

        except Exception as error:  # noqa: BLE001
            print(
                "\n[ERROR]"
            )

            print(
                error
            )

            continue

        print(
            "\nAGENT:"
        )

        print(
            final_state[
                "final_report"
            ]
        )


def evaluate_json_mission(
    mission,
) -> None:
    print(
        "\n[LANGGRAPH] Running waypoint "
        "mission graph..."
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


def show_json_mission(
    mission,
) -> None:
    print(
        "\nCURRENT MISSION JSON"
    )

    print(
        mission.model_dump_json(
            indent=4
        )
    )


def print_json_help() -> None:
    print(
        "\nJSON MISSION COMMANDS"
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
        "  Set the battery reserve to 25%."
    )

    print(
        "  Change WP3 speed to 20 km/h."
    )

    print(
        "\nCommands:"
    )

    print(
        "  show"
        "   - show the current mission JSON"
    )

    print(
        "  report"
        " - run mission validation again"
    )

    print(
        "  save"
        "   - save the edited mission"
    )

    print(
        "  reset"
        "  - reload the original JSON file"
    )

    print(
        "  help"
        "   - show these commands"
    )

    print(
        "  menu"
        "   - return to the main menu"
    )

    print(
        "  exit"
        "   - close the program"
    )


def run_json_mission() -> bool:
    print(
        "\nJSON MISSION"
    )

    print(
        "\nEnter the mission JSON path."
    )

    print(
        "Example:"
    )

    print(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    try:
        file_path = input(
            "\nJSON path: "
        ).strip()

    except (
        KeyboardInterrupt,
        EOFError,
    ):
        return False

    if not file_path:
        print(
            "\nNo JSON file selected."
        )

        return True

    try:
        mission = load_mission_json(
            file_path
        )

    except Exception as error:  # noqa: BLE001
        print(
            "\n[JSON ERROR]"
        )

        print(
            error
        )

        return True

    print(
        "\n[JSON] Mission loaded successfully."
    )

    print(
        f"Mission: {mission.name}"
    )

    print(
        f"Mission ID: {mission.mission_id}"
    )

    evaluate_json_mission(
        mission
    )

    print_json_help()

    while True:
        try:
            user_input = input(
                "\nYou: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            print(
                "\nClosing Agentic Drone "
                "Mission Control..."
            )

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
            print_json_help()

            continue

        if command == "show":
            show_json_mission(
                mission
            )

            continue

        if command == "report":
            evaluate_json_mission(
                mission
            )

            continue

        if command == "reset":
            try:
                mission = load_mission_json(
                    file_path
                )

            except Exception as error:  # noqa: BLE001
                print(
                    "\n[JSON ERROR]"
                )

                print(
                    error
                )

                continue

            print(
                "\nMission restored from "
                "the original JSON file."
            )

            evaluate_json_mission(
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

        except Exception as error:  # noqa: BLE001
            print(
                "\n[MISSION EDITOR ERROR]"
            )

            print(
                error
            )

            continue

        try:
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

            print(
                "Write 'help' to see examples."
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

        try:
            final_state = (
                waypoint_mission_graph.invoke(
                    {
                        "mission":
                            mission,
                    }
                )
            )

        except Exception as error:  # noqa: BLE001
            print(
                "\n[ERROR]"
            )

            print(
                error
            )

            continue

        print(
            "\nAGENT:"
        )

        print(
            final_state[
                "final_report"
            ]
        )


def main() -> None:
    while True:
        print_main_menu()

        try:
            option = input(
                "\nSelect option: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            print(
                "\nClosing Agentic Drone "
                "Mission Control..."
            )

            break

        if option == "1":
            keep_running = (
                run_natural_language_mission()
            )

            if not keep_running:
                break

        elif option == "2":
            keep_running = (
                run_json_mission()
            )

            if not keep_running:
                break

        elif option == "3":
            break

        else:
            print(
                "\nInvalid option."
            )

    print(
        "\nClosing Agentic Drone "
        "Mission Control..."
    )


if __name__ == "__main__":
    main()