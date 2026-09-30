from agents.mission_planner import (
    extract_mission_plan_draft,
)
from graph.mission_graph import (
    memory,
    mission_graph,
)
from inputs.json_loader import (
    load_mission_json,
)
from inputs.qgroundcontrol_adapter import (
    load_qgroundcontrol_plan,
)
from models.mission_plan_draft import (
    MissionPlanDraft,
)
from models.qgc_import import (
    QGroundControlImportContext,
)
from planning.mission_plan_service import (
    build_mission_from_draft,
    get_missing_planning_fields,
    merge_mission_plan_drafts,
)
from sessions.structured_mission_session import (
    run_structured_mission_session,
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
        "\nAGENTIC DRONE MISSION CONTROL"
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
        "3. AI Mission Planner"
    )

    print(
        "4. QGroundControl .plan"
    )

    print(
        "5. Exit"
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


def run_json_mission() -> bool:
    print(
        "\nJSON MISSION"
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

    return (
        run_structured_mission_session(
            mission
        )
    )


def run_ai_mission_planner() -> bool:
    print(
        "\nAI MISSION PLANNER"
    )

    print(
        "\nDescribe the mission you want "
        "the system to create."
    )

    print(
        "The planner will never invent "
        "missing operational data."
    )

    print(
        "\nWrite 'menu' to return."
    )

    print(
        "Write 'exit' to close."
    )

    draft = MissionPlanDraft()

    while True:
        try:
            user_input = input(
                "\nPlanner: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):
            return False

        if not user_input:
            continue

        command = user_input.lower()

        if command == "menu":
            return True

        if command in {
            "exit",
            "quit",
            "salir",
        }:
            return False

        try:
            new_draft = (
                extract_mission_plan_draft(
                    user_input=user_input,
                    current_draft=draft,
                )
            )

            draft = (
                merge_mission_plan_drafts(
                    current=draft,
                    new=new_draft,
                )
            )

        except Exception as error:  # noqa: BLE001
            print(
                "\n[PLANNER ERROR]"
            )

            print(
                error
            )

            continue

        missing = (
            get_missing_planning_fields(
                draft
            )
        )

        if missing:
            print(
                "\n[PLANNER] Additional "
                "information required:"
            )

            for field in missing:
                print(
                    f"- {field}"
                )

            continue

        try:
            mission = (
                build_mission_from_draft(
                    draft
                )
            )

        except Exception as error:  # noqa: BLE001
            print(
                "\n[MISSION PLAN REJECTED]"
            )

            print(
                error
            )

            continue

        print(
            "\n[MISSION PLANNER] "
            "MissionDefinition created."
        )

        print(
            f"Mission ID: "
            f"{mission.mission_id}"
        )

        print(
            f"Mission name: "
            f"{mission.name}"
        )

        print(
            f"Waypoints: "
            f"{len(mission.route.waypoints)}"
        )

        return (
            run_structured_mission_session(
                mission
            )
        )


def _read_float(
    label: str,
) -> float:
    while True:
        value = input(
            f"{label}: "
        ).strip()

        try:
            return float(
                value
            )

        except ValueError:
            print(
                "Please enter a numeric value."
            )


def run_qgroundcontrol_mission() -> bool:
    print(
        "\nQGROUNDCONTROL MISSION"
    )

    try:
        file_path = input(
            "\n.plan path: "
        ).strip()

    except (
        KeyboardInterrupt,
        EOFError,
    ):
        return False

    if not file_path:
        return True

    print(
        "\nQGroundControl provides the route, "
        "but runtime safety information "
        "must be provided separately."
    )

    try:
        context = (
            QGroundControlImportContext(
                battery_percent=(
                    _read_float(
                        "Battery %"
                    )
                ),

                battery_consumption_percent_per_minute=(
                    _read_float(
                        "Battery consumption %/min"
                    )
                ),

                wind_speed_kmh=(
                    _read_float(
                        "Wind speed km/h"
                    )
                ),

                wind_direction_from_deg=(
                    _read_float(
                        "Wind direction FROM degrees"
                    )
                ),

                minimum_battery_reserve_percent=(
                    _read_float(
                        "Minimum battery reserve %"
                    )
                ),

                maximum_wind_speed_kmh=(
                    _read_float(
                        "Maximum safe wind km/h"
                    )
                ),

                maximum_altitude_m=(
                    _read_float(
                        "Maximum altitude m"
                    )
                ),
            )
        )

        result = (
            load_qgroundcontrol_plan(
                file_path=file_path,
                context=context,
            )
        )

    except Exception as error:  # noqa: BLE001
        print(
            "\n[QGC IMPORT ERROR]"
        )

        print(
            error
        )

        return True

    print(
        "\n[QGC] Mission imported successfully."
    )

    print(
        "Source mission items: "
        f"{result.source_item_count}"
    )

    print(
        "Imported waypoints: "
        f"{result.imported_waypoint_count}"
    )

    print(
        "Planned HOME AMSL: "
        f"{result.planned_home_amsl_m} m"
    )

    if result.warnings:
        print(
            "\nQGC IMPORT WARNINGS"
        )

        for warning in result.warnings:
            print(
                f"- {warning}"
            )

    return (
        run_structured_mission_session(
            result.mission
        )
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
            break

        if option == "1":
            keep_running = (
                run_natural_language_mission()
            )

        elif option == "2":
            keep_running = (
                run_json_mission()
            )

        elif option == "3":
            keep_running = (
                run_ai_mission_planner()
            )

        elif option == "4":
            keep_running = (
                run_qgroundcontrol_mission()
            )

        elif option == "5":
            break

        else:
            print(
                "\nInvalid option."
            )

            continue

        if not keep_running:
            break

    print(
        "\nClosing Agentic Drone "
        "Mission Control..."
    )


if __name__ == "__main__":
    main()