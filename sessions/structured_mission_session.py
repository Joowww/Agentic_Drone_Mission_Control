from pathlib import Path

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
from inputs.qgroundcontrol_exporter import (
    export_qgroundcontrol_plan,
)
from models.mission_definition import (
    MissionDefinition,
)


def evaluate_structured_mission(
    mission: MissionDefinition,
    *,
    re_evaluation: bool = False,
) -> dict:
    if re_evaluation:
        print(
            "\n[LANGGRAPH] "
            "Re-evaluating mission..."
        )

    else:
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

    return final_state


def export_validated_mission_plan(
    mission: MissionDefinition,
    final_state: dict,
    *,
    output_directory: str | Path | None = None,
) -> dict:
    """Export a QGroundControl .plan for a validated mission.

    ``output_directory`` defaults to ``missions/generated``.  When
    provided it overrides the destination so callers (e.g. the
    Hermes wrapper and tests) can target a temporary directory.

    Returns a dict with ``execution_status`` (APPROVED / BLOCKED)
    and ``qgc_plan_path`` (Path or None on export failure).
    """
    mission_status = final_state.get(
        "mission_status",
        "UNKNOWN",
    )
    if output_directory is None:
        output_directory = Path(
            "missions/generated"
        )
    else:
        output_directory = Path(
            output_directory
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    approved_path = (
        output_directory
        / f"{mission.mission_id}.plan"
    )

    candidate_path = (
        output_directory
        / (
            f"{mission.mission_id}"
            "_candidate.plan"
        )
    )

    if mission_status == "FEASIBLE":
        file_path = approved_path
        stale_path = candidate_path
        execution_status = "APPROVED"

    else:
        file_path = candidate_path
        stale_path = approved_path
        execution_status = "BLOCKED"

    try:
        saved_path = (
            export_qgroundcontrol_plan(
                mission=mission,
                file_path=file_path,
            )
        )

    except Exception as error:  # noqa: BLE001
        print(
            "\n[QGC EXPORT ERROR]"
        )
        print(
            error
        )
        return {
            "execution_status": execution_status,
            "qgc_plan_path": None,
        }

    stale_path.unlink(
        missing_ok=True
    )

    print(
        "\n[QGC EXPORT] "
        "QGroundControl plan generated."
    )
    print(
        f"Plan: {saved_path}"
    )
    print(
        "Execution status: "
        f"{execution_status}"
    )

    return {
        "execution_status": execution_status,
        "qgc_plan_path": saved_path,
    }


def evaluate_and_export_mission(
    mission: MissionDefinition,
    *,
    re_evaluation: bool = False,
) -> dict:
    final_state = (
        evaluate_structured_mission(
            mission,
            re_evaluation=(
                re_evaluation
            ),
        )
    )

    export_validated_mission_plan(
        mission=mission,
        final_state=final_state,
    )

    return final_state


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

    evaluate_and_export_mission(
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
            evaluate_and_export_mission(
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

            evaluate_and_export_mission(
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

        evaluate_and_export_mission(
            mission,
            re_evaluation=True,
        )