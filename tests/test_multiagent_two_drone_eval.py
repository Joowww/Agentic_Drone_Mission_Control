"""The offline evaluation's declared cases (the full run is the evidence generator)."""
import json

from multiagent.benchmark import two_drone_eval as ev


def test_the_camera_cases_are_one_valid_and_ten_refusals_each_with_its_reason():
    rows = ev._camera_cases()
    assert [r["case"] for r in rows if r["status"] == "OBSERVED"] == ["valid"]
    refused = {r["case"]: r["reason"] for r in rows if r["status"] == "REFUSED"}
    assert len(refused) == 10 and refused["ambiguous"] == "DETECTION_AMBIGUOUS" and refused["other_drone"] == "OTHER_DRONE"


def test_every_negative_mutation_differs_from_the_sealed_plan():
    sealed = json.loads(ev.SEALED.read_text())
    muts = ev._mutations(sealed)
    assert len(muts) == 7 and all(m != sealed for m in muts.values())
    assert json.loads(ev.SEALED.read_text()) == sealed          # the sealed file is only read
