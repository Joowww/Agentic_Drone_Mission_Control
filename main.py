from graph.mission_graph import mission_graph


def main() -> None:
    print(
        "AGENTIC DRONE MISSION CONTROL"
    )

    print(
        "\nDescribe the drone mission."
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

        print(
            "\n[LANGGRAPH] Running mission graph..."
        )

        try:
            final_state = mission_graph.invoke(
                {
                    "user_input": user_input,
                }
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