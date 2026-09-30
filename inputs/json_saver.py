import json
from pathlib import Path

from models.mission_definition import (
    MissionDefinition,
)


def save_mission_json(
    mission: MissionDefinition,
    file_path: str,
) -> Path:
    path = Path(
        file_path
    )

    if path.suffix.lower() != ".json":
        path = path.with_suffix(
            ".json"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = mission.model_dump(
        mode="json"
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False,
        )

        file.write(
            "\n"
        )

    return path