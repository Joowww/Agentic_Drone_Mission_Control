from graph.mission_graph import (
    memory,
    mission_graph,
)

THREAD_ID = "drone-mission-session"

config = {
    "configurable": {
        "thread_id": THREAD_ID,
    }
}


def main() -> None:
    print(
        "AGENTIC DRONE MISSION CONTROL"
    )

    print(
        "\nDescribe the drone mission."
    )

    print(
        "You can update mission parameters in later messages."
    )

    print(
        "Write 'reset' to start a new mission."
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
                "\nClosing Agentic Drone Mission Control..."
            )
            break

        if not user_input:
            continue

        if user_input.lower() in {
            "exit",
            "quit",
            "salir",
        }:
            print(
                "\nClosing Agentic Drone Mission Control..."
            )
            break

        if user_input.lower() == "reset":
            memory.delete_thread(
                THREAD_ID
            )

            print(
                "\nMission reset."
            )

            continue

        print(
            "\n[LANGGRAPH] Running mission graph..."
        )

        try:
            final_state = mission_graph.invoke(
                {
                    "user_input": user_input,
                },
                config=config,
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
            final_state["final_report"]
        )


if __name__ == "__main__":
    main()