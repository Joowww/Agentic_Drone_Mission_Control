import json
from pathlib import Path

from pydantic import ValidationError

from models.mission_definition import (
    MissionDefinition,
)


def load_mission_json(
    file_path: str,
) -> MissionDefinition:
    path = Path(
        file_path
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Mission file not found: {file_path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Mission path is not a file: {file_path}"
        )

    if path.suffix.lower() != ".json":
        raise ValueError(
            "Mission file must use the .json extension."
        )

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(
                file
            )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON: {error}"
        ) from error

    try:
        mission = MissionDefinition.model_validate(
            data
        )

    except ValidationError as error:
        raise ValueError(
            f"Invalid mission definition:\n{error}"
        ) from error

    return mission