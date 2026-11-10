"""The experimental comparison and the review sheet are generated from conserved evidence only (REAL records,
read-only). Denominators, keys and sources must match the acceptances recorded at the time."""
import hashlib
import json

import pytest

from reporting import agri_experiment_comparison as comparison


@pytest.fixture(scope="module")
def result():
    return comparison.comparison()


def test_turn_rows_keep_denominators_failed_keys_and_sources(result):
    h1, h3, h3b = result["turns"]
    assert (h1["acceptance"], h1["structured"]["match"], h1["structured"]["total"]) == ("BOUND", 2, 2)
    assert (h3["acceptance"], h3["structured"]["match"], h3["structured"]["total"]) == ("NOT_VALIDATED", 22, 23)
    assert h3["structured"]["failed"] == ["r1_movement_authorized"] and h3["critical"] is None
    assert h3["structured"]["presence_only"] == ["evidence_source", "explanation"]
    assert (h3b["structured"]["match"], h3b["structured"]["total"], h3b["critical"]["match"],
            h3b["critical"]["total"]) == (23, 23, 12, 12)
    for row in (h1, h3, h3b):
        assert row["invocations"] == 1 and row["plugin_llm_errors"] == 0
        assert all(source.startswith("evaluation/observability/") for source in row["sources"].values())


def test_pilot_keeps_protocol_segments_and_never_pools_cases(result):
    pilot = result["pilot"]
    assert pilot["segments"]["protocolo original"]["structured_validated"] == "1/2"
    assert pilot["segments"]["tras enmienda 01"]["structured_validated"] == "5/8"
    rows = {r["case"]: r for r in pilot["rows"]}
    assert rows["pilot-real-r02"]["answer"] == "NO_ANSWER_TECHNICAL" and rows["pilot-real-r02"]["failed_attempts"] == 4
    assert rows["pilot-real-r03"]["structured"] is None  # unparseable: nothing compared
    assert rows["pilot-real-r08"]["critical"]["failed"] == ["claims.current_permissions_checked",
                                                             "claims.detections_made", "claims.images_captured",
                                                             "claims.speed_commanded", "claims.speed_measured"]
    assert pilot["pilot_report_denominators"]["structured_validated_of_attempted"] == "6/10"
    text = comparison.render(result)
    assert "no se agregan en una tasa" in text and "solo descriptivo" in text


def test_review_sheet_keeps_literal_texts_hashes_and_leaves_human_review_pending():
    sheet = comparison.render_review_sheet()
    assert "**Revisión humana: PENDIENTE.**" in sheet and "Análisis retrospectivo" in sheet
    accepted = json.loads(comparison.H3.joinpath("accept_h3.json").read_text())
    text = accepted["answer"]["explanation"]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() in sheet
    assert hashlib.sha256(comparison.H3.joinpath("accept_h3.json").read_bytes()).hexdigest() in sheet
    criteria = [c for _, c, _, _, _ in comparison.RUBRIC]
    rows = [line for line in sheet.splitlines() if any(line.startswith(f"| {c} |") for c in criteria)]
    assert rows and all(line.endswith("|  |  |") for line in rows)  # both human columns left empty
    # H3, H3b and the pilot keys with an analysable explanation (r02: no answer; r03: not JSON)
    assert sheet.count("Revisor: ________") == len(rows) // len(criteria) == 2 + 8
    assert len(comparison.RUBRIC) == 7


def test_cli_never_overwrites_generated_files(tmp_path):
    target = tmp_path / "comparison.md"
    target.write_text("existing")
    with pytest.raises(SystemExit):
        comparison.main(["comparison", "--out", str(target)])
    assert target.read_text() == "existing"


def test_r06_is_rejected_by_form_with_equivalent_content_and_keeps_its_acceptance(result):
    rows = {r["case"]: r for r in result["pilot"]["rows"]}
    r06 = rows["pilot-real-r06"]
    assert r06["acceptance"] == "NOT_VALIDATED" and r06["original_acceptance_error"] is True
    assert r06["form_only_keys"] == ["runs[2f7db1f6].reached_points", "runs[febf7c4f].reached_points"]
    assert all(not r["form_only_keys"] for k, r in rows.items() if k != "pilot-real-r06")
    assert "por **forma**" in comparison.render(result) and "21/23 (2 por forma)" in comparison.render(result)


def test_r02_attempts_are_reported_as_recorded_without_asserting_four_retries(result):
    r02 = {r["case"]: r for r in result["pilot"]["rows"]}["pilot-real-r02"]
    errors = [a for a in r02["attempt_sequence"] if a["event_type"] == "llm_error"]
    assert [a["retry_count"] for a in errors] == [0, 1, 2, 0] and r02["retry_counter_monotonic"] is False
    assert len({a["api_request_ref"] for a in r02["attempt_sequence"]}) == 1
    assert r02["attempt_sequence"][-1]["finish_reason"] == "tool_calls"
    text = comparison.render(result)
    assert "| 4 | 4? |" in text and "no permiten afirmar cuántos" in text


def test_h1_is_described_as_artifact_generation_from_a_complete_specification(result):
    h1 = result["turns"][0]
    assert h1["protocol"].startswith("generación y validación de artefactos de misión")
    assert "planificación" not in h1["protocol"] and h1["decisions"]["by_hermes"]
    text = comparison.render(result)
    assert "**22/23**" in text and "**24/25**" in text
