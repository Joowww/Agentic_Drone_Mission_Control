from pathlib import Path

import pytest

from inputs.qgroundcontrol_adapter import (
    load_qgroundcontrol_plan,
)
from models.qgc_import import (
    QGroundControlImportContext,
)

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


@pytest.fixture
def qgc_plan_path() -> Path:
    return (
        PROJECT_ROOT
        / "missions"
        / "qgroundcontrol_examples"
        / "simple_field_mission.plan"
    )


@pytest.fixture
def qgc_context() -> QGroundControlImportContext:
    return QGroundControlImportContext(
        battery_percent=82.0,
        battery_consumption_percent_per_minute=0.8,
        wind_speed_kmh=12.0,
        wind_direction_from_deg=0.0,
        minimum_battery_reserve_percent=20.0,
        maximum_wind_speed_kmh=30.0,
        maximum_altitude_m=120.0,
    )


@pytest.fixture
def qgc_import_result(
    qgc_plan_path,
    qgc_context,
):
    return load_qgroundcontrol_plan(
        file_path=str(
            qgc_plan_path
        ),
        context=qgc_context,
    )


@pytest.fixture
def qgc_mission(
    qgc_import_result,
):
    return (
        qgc_import_result
        .mission
        .model_copy(
            deep=True
        )
    )