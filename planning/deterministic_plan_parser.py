import re

from models.mission_plan_draft import (
    MissionPlanDraft,
)

OBJECTIVE_PATTERNS = {
    "precision_agriculture": [
        r"\bprecision\s+agriculture\b",
        r"\bprecision\s+farming\b",
    ],
    "inspection": [
        r"\binspection\b",
        r"\binspect\b",
    ],
    "survey": [
        r"\bsurvey\b",
        r"\bmapping\b",
    ],
    "transit": [
        r"\btransit\b",
        r"\btransport\b",
    ],
}


VEHICLE_PATTERNS = {
    "multirotor": [
        r"\bmultirotor\b",
        r"\bmulticopter\b",
        r"\bquadcopter\b",
        r"\bquadrotor\b",
    ],
    "fixed_wing": [
        r"\bfixed[\s-]?wing\b",
    ],
    "vtol": [
        r"\bvtol\b",
    ],
    "ugv": [
        r"\bugv\b",
        r"\bground vehicle\b",
    ],
}


def _extract_objective_type(
    text: str,
) -> str | None:
    for objective_type, patterns in (
        OBJECTIVE_PATTERNS.items()
    ):
        for pattern in patterns:
            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                return objective_type

    return None


def _extract_vehicle_type(
    text: str,
) -> str | None:
    for vehicle_type, patterns in (
        VEHICLE_PATTERNS.items()
    ):
        for pattern in patterns:
            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                return vehicle_type

    return None


def _extract_objective_target(
    text: str,
) -> str | None:
    target_match = re.search(
        (
            r"\b(field|sector|area)"
            r"[\s_-]*"
            r"([A-Za-z0-9]+)\b"
        ),
        text,
        flags=re.IGNORECASE,
    )

    if not target_match:
        return None

    prefix = (
        target_match
        .group(1)
        .lower()
    )

    identifier = (
        target_match
        .group(2)
        .lower()
    )

    return (
        f"{prefix}_{identifier}"
    )


def _extract_return_to_home(
    text: str,
) -> bool | None:
    rtl_pattern = (
        r"\b("
        r"return\s+to\s+home|"
        r"return\s+home|"
        r"rtl"
        r")\b"
    )

    if not re.search(
        rtl_pattern,
        text,
        flags=re.IGNORECASE,
    ):
        return None

    disable_pattern = (
        r"\b("
        r"no|"
        r"not|"
        r"disable|"
        r"disabled|"
        r"without|"
        r"do\s+not|"
        r"don't"
        r")\b"
    )

    if re.search(  # noqa: SIM103
        disable_pattern,
        text,
        flags=re.IGNORECASE,
    ):
        return False

    return True


def parse_deterministic_plan_fields(
    user_input: str,
) -> MissionPlanDraft:
    text = user_input.strip()

    draft = MissionPlanDraft()

    objective_type = (
        _extract_objective_type(
            text
        )
    )

    if objective_type is not None:
        draft.objective_type = (
            objective_type
        )

    vehicle_type = (
        _extract_vehicle_type(
            text
        )
    )

    if vehicle_type is not None:
        draft.vehicle_type = (
            vehicle_type
        )

    if re.search(
        r"\bpx4\b",
        text,
        flags=re.IGNORECASE,
    ):
        draft.autopilot = "PX4"

    elif re.search(
        r"\bardupilot\b",
        text,
        flags=re.IGNORECASE,
    ):
        draft.autopilot = (
            "ArduPilot"
        )

    objective_target = (
        _extract_objective_target(
            text
        )
    )

    if objective_target is not None:
        draft.objective_target = (
            objective_target
        )

    return_to_home = (
        _extract_return_to_home(
            text
        )
    )

    if return_to_home is not None:
        draft.return_to_home = (
            return_to_home
        )

    return draft