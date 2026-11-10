"""M4 integrated pilot OFFLINE: a fake Ollama transport answers as the three roles (the real adapter code runs). Budget
(total and per role), criteria evaluation, fallback labelling, sealing; nothing reaches a network or a vehicle."""
import json

import pytest

from multiagent.benchmark import m4_pilot
from multiagent.simulated_llm import integrated_orchestrator
from tests.test_multiagent_agents_pilot import OK, good_reply
from tests.test_multiagent_qwen_pilot import Ollama

M = json.loads(m4_pilot.MANIFEST.read_text())
PROBES = {**OK, "model": lambda: {"name": "qwen3:4b", "digest": M["model"]["digest"]}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no real network or process")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


def reply(prompt):
    if "PROMPT_ID: agent_" in prompt:
        return good_reply(prompt)
    return integrated_orchestrator(prompt)  # a brief /2 for the integrated request


def test_the_manifest_fixes_case_budget_and_criteria():
    assert M["budget"]["max_real_llm_calls"] == 6 and M["budget"]["per_role"] == 2
    assert set(M["criteria"]) >= {"C1_supervisor", "C2_drone", "C3_rover_wait", "C4_rover_plan", "C5_integrated"}
    assert M["agents"]["drone_swarm_agent"]["prompt_id"] == "agent_drone_single/3"
    assert M["agents"]["rover_agent"]["prompt_id"] == "agent_rover_single/3"


def test_m4_offline_end_to_end(tmp_path):
    fake = Ollama(reply)
    r = m4_pilot.run(tmp_path / "m4", allow_model_calls=True, probes=PROBES, transport=fake)
    assert r["status"] == "RUN" and r["budget"]["real_calls_used"] == len(fake.requests) <= 6
    assert all(n <= 2 for n in r["budget"]["per_role"].values())
    assert r["budget"]["per_role"] == {"mission_orchestrator": 1, "drone_swarm_agent": 1, "rover_agent": 2}
    c = r["criteria"]
    assert all(c[k] for k in ("C1_supervisor", "C2_drone", "C3_rover_wait", "C4_rover_plan", "C5_integrated"))
    assert c["C2_drone_phase"] == "FIRST_ROUND" and not any(c["fallbacks"].values())
    assert r["commands_sent"] == 0 and r["physical_effect"] is False
    assert len((tmp_path / "m4/exchanges.jsonl").read_text().splitlines()) == r["budget"]["real_calls_used"]
    assert (tmp_path / "m4/demo/scene.png").is_file() and (tmp_path / "m4/SHA256SUMS").is_file()


def test_a_wrong_supervisor_brief_fails_c1_without_hiding_it(tmp_path):
    def bad(prompt):
        if "PROMPT_ID: agent_" in prompt:
            return good_reply(prompt)
        return json.dumps({"schema": "tfg.multiagent.mission-brief/2", "aerial_objectives": [
            {"objective_id": "A1", "point_id": "POI_1", "required_sensor": "rgb"}], "ground_objectives": [
            {"objective_id": "G1", "point_id": "POI_3", "after_aerial": True}], "rover": "rover_01"})
    r = m4_pilot.run(tmp_path / "m4", allow_model_calls=True, probes=PROBES, transport=Ollama(bad))
    assert r["criteria"]["C1_supervisor"] is False and r["classification"] != "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"


def test_preconditions_failing_spend_no_call(tmp_path):
    fake = Ollama(error=AssertionError("must not be called"))
    r = m4_pilot.run(tmp_path / "x", allow_model_calls=True, probes={**PROBES, "gpu_apps": lambda: ["1, x, 9 MiB"]},
                     transport=fake)
    assert r["status"] == "NOT_RUN_PRECONDITIONS" and fake.requests == []


# ------------------------------------------------------------------------------------------------- M4b --
MB = json.loads(m4_pilot.MANIFESTS["m4b"].read_text())


def test_m4b_is_a_new_experiment_with_its_own_sealed_manifest():
    assert MB["pilot_id"] == "m4b_integrated_v1" != M["pilot_id"]
    assert MB["agents"]["mission_orchestrator"]["prompt_id"] == "interpret_brief/3" and MB["safety_policy"] == "safety/4"
    assert MB["budget"]["max_real_llm_calls"] == 6 and MB["budget"]["retries"] == 0
    assert MB["budget"]["per_role"] == {"mission_orchestrator": 2, "drone_swarm_agent": 2, "rover_agent": 2}
    assert MB["model"] == M["model"] and MB["generation"] == M["generation"]  # same model, digest and parameters
    from multiagent import supervisor_prompts
    from multiagent.simulated_llm import INTEGRATED_TEXT
    assert MB["prompt_hashes"]["interpret_brief/3"] == supervisor_prompts.TEMPLATE_SHA256
    assert MB["dataset"]["text"] == INTEGRATED_TEXT and len(MB["expected_chain"]) == 11
    assert m4_pilot.MANIFEST.name == "m4_integrated_v1.json"  # the M4 manifest is still the sealed one


def test_m4b_offline_end_to_end(tmp_path):
    fake = Ollama(reply)
    r = m4_pilot.run(tmp_path / "m4b", allow_model_calls=True, probes=PROBES, transport=fake,
                     manifest_path=m4_pilot.MANIFESTS["m4b"])
    assert r["status"] == "RUN" and r["safety_policy"] == "safety/4"
    sup_prompt = json.loads((tmp_path / "m4b/exchanges.jsonl").read_text().splitlines()[0])["prompt"]
    assert "Stages: you only INTERPRET" in sup_prompt  # prompt /3 was sent
    assert r["budget"]["per_role"] == {"mission_orchestrator": 1, "drone_swarm_agent": 1, "rover_agent": 2}
    c = r["criteria"]
    assert all(c[k] for k in ("C0_safety", "C1_supervisor", "C2_drone", "C3_rover_wait", "C4_rover_plan", "C5_integrated"))
    assert set(r["role_outcomes"].values()) == {"MODEL_SUCCESS_FIRST_ROUND"}
    assert r["commands_sent"] == 0 and r["physical_effect"] is False


def test_m4b_an_m4_like_overflag_is_an_incorrect_rejection_and_stops_the_mission(tmp_path):
    def overflag(prompt):
        if "PROMPT_ID: agent_" in prompt:
            raise AssertionError("no specialist may be called after a refusal")
        b = json.loads(integrated_orchestrator(prompt))
        return json.dumps({**b, "unsafe_requests": ["send rover_01 to the point it indicates"]})
    r = m4_pilot.run(tmp_path / "m4b", allow_model_calls=True, probes=PROBES, transport=Ollama(overflag),
                     manifest_path=m4_pilot.MANIFESTS["m4b"])
    assert r["budget"]["per_role"] == {"mission_orchestrator": 1}
    assert r["role_outcomes"]["mission_orchestrator"] == "INCORRECT_REJECTION"
    assert r["role_outcomes"]["drone_swarm_agent"] == "NOT_REACHED" and r["role_outcomes"]["rover_agent_phase_a"] == "NOT_REACHED"
    assert r["classification"] == "MISSION_REFUSED_BY_SUPERVISOR" and r["criteria"]["C0_safety"] is False


def test_m4b_per_role_caps_hold(tmp_path):
    def always_wrong(prompt):  # the drone agent keeps proposing an unknown drone: its 2 calls, then the gate's fallback
        if "PROMPT_ID: agent_drone" in prompt:
            return json.dumps({"proposal": {"assignments": {"drone_99": ["A1", "A2"]}}, "verify": [], "explanation": "x"})
        return reply(prompt)
    r = m4_pilot.run(tmp_path / "m4b", allow_model_calls=True, probes=PROBES, transport=Ollama(always_wrong),
                     manifest_path=m4_pilot.MANIFESTS["m4b"])
    assert r["budget"]["per_role"]["drone_swarm_agent"] <= 2 and r["budget"]["real_calls_used"] <= 6
    assert r["role_outcomes"]["drone_swarm_agent"] in ("FALLBACK_SUCCESS", "MODEL_FAILURE")
    assert r["criteria"]["C2_drone"] is False


def test_m4b_refuses_a_changed_prompt(tmp_path, monkeypatch):
    from multiagent import supervisor_prompts
    monkeypatch.setattr(supervisor_prompts, "TEMPLATE_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="changed after the manifest"):
        m4_pilot.run(tmp_path / "m4b", allow_model_calls=True, probes=PROBES, transport=Ollama(reply),
                     manifest_path=m4_pilot.MANIFESTS["m4b"])


# ------------------------------------------------------------------------------------------------- M4c --
MC = json.loads(m4_pilot.MANIFESTS["m4c"].read_text())


def reply_v4(prompt):
    from multiagent.simulated_llm import integrated_orchestrator_v4
    if "PROMPT_ID: agent_" in prompt:
        return good_reply(prompt)
    return integrated_orchestrator_v4(prompt)


def test_m4c_is_a_new_experiment_with_its_own_manifest():
    from multiagent import brief_provenance
    assert MC["pilot_id"] == "m4c_integrated_v1" and MC["agents"]["mission_orchestrator"]["prompt_id"] == "interpret_brief/4"
    assert MC["prompt_hashes"] == {"interpret_brief/4": brief_provenance.TEMPLATE_SHA256}
    assert MC["budget"]["per_role"] == {"mission_orchestrator": 2, "drone_swarm_agent": 2, "rover_agent": 2}
    assert MC["budget"]["max_real_llm_calls"] == 6 and MC["model"] == M["model"] and MC["generation"] == M["generation"]
    assert MC["safety_policy"] == "safety/4" and MC["dataset"]["text"] == MB["dataset"]["text"]


def test_m4c_offline_end_to_end(tmp_path):
    r = m4_pilot.run(tmp_path / "m4c", allow_model_calls=True, probes=PROBES, transport=Ollama(reply_v4),
                     manifest_path=m4_pilot.MANIFESTS["m4c"])
    assert r["status"] == "RUN" and r["classification"] == "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"
    c = r["criteria"]
    assert all(c[k] for k in ("C0_safety", "C0b_provenance", "C1_supervisor", "C2_drone", "C3_rover_wait",
                              "C4_rover_plan", "C5_integrated"))
    assert set(r["role_outcomes"].values()) == {"MODEL_SUCCESS_FIRST_ROUND"} and r["commands_sent"] == 0


def test_m4c_an_m4b_like_invention_is_a_deterministic_correction_not_an_llm_success(tmp_path):
    def inventing(prompt):
        if "PROMPT_ID: agent_" in prompt:
            return good_reply(prompt)
        body = json.loads(reply_v4(prompt))
        body["stated"] = [{"field": "drones", "value": "drone_01", "quote": "Inspect POI_1 with the RGB camera"},
                          {"field": "availability", "vehicle_id": "rover_01", "value": "UNKNOWN", "quote": "rover_01"}]
        return json.dumps(body)
    r = m4_pilot.run(tmp_path / "m4c", allow_model_calls=True, probes=PROBES, transport=Ollama(inventing),
                     manifest_path=m4_pilot.MANIFESTS["m4c"])
    assert r["criteria"]["C0b_provenance"] is False
    assert r["role_outcomes"]["mission_orchestrator"] == "DETERMINISTIC_CORRECTION_SUCCESS"
    assert r["classification"] == "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"


def test_m4c_refuses_a_changed_prompt(tmp_path, monkeypatch):
    from multiagent import brief_provenance
    monkeypatch.setattr(brief_provenance, "TEMPLATE_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="interpret_brief/4 changed"):
        m4_pilot.run(tmp_path / "m4c", allow_model_calls=True, probes=PROBES, transport=Ollama(reply_v4),
                     manifest_path=m4_pilot.MANIFESTS["m4c"])


# ---------------------------------------------------------------------- M4c-r1: resource isolation profile --
from multiagent.benchmark import agents_pilot as ap  # noqa: E402

MR1 = json.loads(m4_pilot.MANIFESTS["m4c_r1"].read_text())
R1_PROBES = {**PROBES, "ollama_ps": lambda: [], "pilot_processes": lambda: [], "operational": lambda: [],
             "meminfo": lambda: {"available_mib": 9000, "total_mib": 15869}, "contract_pinned": lambda: True,
             "manifest_integrity": lambda: {"ok": True}, "cpu": lambda: {"cpus": 16, "loadavg": (2.0, 1.5, 1.2)},
             "activity": lambda: ["tools/rover_pipe_worker.py"]}  # the other checkout IS active: not a gate any more


def test_m4c_r1_is_an_explicit_revision_with_the_same_science():
    assert MR1["pilot_id"] == "m4c_r1_integrated_v1" and MR1["isolation_profile"] == ap.ISOLATION_PROFILE
    for key in ("model", "generation", "budget", "agents", "prompt_hashes", "safety_policy", "criteria", "dataset",
                "expected_chain"):
        assert MR1[key] == MC[key], key
    import hashlib
    assert MR1["revision_of"]["manifest_sha256"] == hashlib.sha256(m4_pilot.MANIFESTS["m4c"].read_bytes()).hexdigest()
    assert "isolation_profile" not in MC  # the original M4c manifest is untouched


def test_resource_isolation_passes_with_an_active_but_harmless_other_checkout():
    pre = ap.resource_isolation(MR1, probes=R1_PROBES)
    assert pre["ok"], {k: v for k, v in pre["checks"].items() if not v}
    assert pre["facts"]["other_checkout_recent_files_INFORMATIONAL"] == ["tools/rover_pipe_worker.py"]


def test_a_test_runner_is_cpu_load_not_a_simulation_session():
    pytest_line = "915998 .venv/bin/python .venv/bin/pytest -q tests/test_simulation_lifecycle.py tests/test_rover_x.py"
    pre = ap.resource_isolation(MR1, probes={**R1_PROBES, "sampled": lambda: [pytest_line]})
    assert pre["checks"]["2_no_gazebo_or_sitl_session"] and pre["facts"]["sim_processes_ignored_test_runners"]
    real = "4242 gz sim -s -r orchard.sdf"
    pre = ap.resource_isolation(MR1, probes={**R1_PROBES, "sampled": lambda: [pytest_line, real]})
    assert not pre["checks"]["2_no_gazebo_or_sitl_session"] and not pre["ok"]


@pytest.mark.parametrize("override, check", [
    ({"ollama_ps": lambda: [{"name": "qwen3:4b"}]}, "1_no_concurrent_llm_experiment"),
    ({"pilot_processes": lambda: ["77 python -m multiagent.benchmark.agents_pilot --run"]}, "1_no_concurrent_llm_experiment"),
    ({"container": lambda: {"status": "RUNNING", "matches": ["1 arducopter --model JSON"]}}, "2_no_gazebo_or_sitl_session"),
    ({"gpu": lambda: {"status": "MEASURED", "memory_used_mib": 6000.0, "memory_total_mib": 8192.0, "utilization_pct": 0}},
     "3_gpu_memory_sufficient"),
    ({"meminfo": lambda: {"available_mib": 900}}, "3b_host_memory_sufficient"),
    ({"gpu_apps": lambda: ["123, python, 900 MiB"]}, "4_no_incompatible_gpu_load"),
    ({"gpu": lambda: {"status": "MEASURED", "memory_used_mib": 10.0, "memory_total_mib": 8192.0, "utilization_pct": 60}},
     "4_no_incompatible_gpu_load"),
    ({"reservations": lambda: ["v3.json"]}, "5_no_protected_operation"),
    ({"locks": lambda: ["rover_01.lock"]}, "5_no_protected_operation"),
    ({"operational": lambda: ["88 python tools/rover_pipe_worker.py --session s"]}, "5_no_protected_operation"),
    ({"git": lambda: " M multiagent/x.py"}, "6_contracts_pinned_and_tree_clean"),
    ({"contract_pinned": lambda: False}, "6_contracts_pinned_and_tree_clean"),
    ({"manifest_integrity": lambda: {"ok": False}}, "10_manifest_and_criteria_intact"),
    ({"model": lambda: {"name": "qwen3:4b", "digest": "0" * 64}}, "model_installed_with_expected_digest"),
])
def test_each_resource_condition_blocks(override, check):
    pre = ap.resource_isolation(MR1, probes={**R1_PROBES, **override})
    assert pre["checks"][check] is False and pre["ok"] is False


def test_m4c_r1_offline_end_to_end_and_no_call_when_blocked(tmp_path):
    r = m4_pilot.run(tmp_path / "r1", allow_model_calls=True, probes=R1_PROBES, transport=Ollama(reply_v4),
                     manifest_path=m4_pilot.MANIFESTS["m4c_r1"])
    assert r["status"] == "RUN" and r["classification"] == "PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION"
    pre = json.loads((tmp_path / "r1/preconditions.json").read_text())
    assert pre["profile"] == ap.ISOLATION_PROFILE
    fake = Ollama(error=AssertionError("must not be called"))
    r = m4_pilot.run(tmp_path / "blocked", allow_model_calls=True, transport=fake, manifest_path=m4_pilot.MANIFESTS["m4c_r1"],
                     probes={**R1_PROBES, "ollama_ps": lambda: [{"name": "other"}]})
    assert r["status"] == "NOT_RUN_PRECONDITIONS" and fake.requests == []


def test_the_real_tool_list_offered_to_llms_is_planning_only():
    pre = ap.resource_isolation(MR1, probes=R1_PROBES)
    assert pre["checks"]["8_llm_tools_planning_only"] and "drone_capabilities" in pre["facts"]["llm_tool_names"]


def test_the_real_ollama_ps_path_parses_the_service_reply():
    """Regression: the first live check failed closed with NOT_MEASURED (TypeError: the reply was parsed twice)."""
    assert ap.ollama_loaded_models(lambda url: {"models": []}) == []
    assert ap.ollama_loaded_models(lambda url: {"models": [{"name": "qwen3:4b"}]}) == [{"name": "qwen3:4b"}]
    pre = ap.resource_isolation(MR1, probes={k: v for k, v in R1_PROBES.items() if k != "ollama_ps"})
    assert pre["checks"]["1_no_concurrent_llm_experiment"] is False  # network refused offline -> NOT_MEASURED blocks
    assert pre["facts"]["ollama_loaded_models"][0].startswith("NOT_MEASURED")


def test_the_checking_process_and_its_launchers_are_not_a_concurrent_experiment():
    """Regression: the live --check counted its own 'bash -c ... m4_pilot' and 'timeout ...' parents."""
    lines = ["10 5 /bin/bash -c timeout 300 python -m multiagent.benchmark.m4_pilot --check | grep x",
             "13 10 /bin/bash -c timeout 300 python -m multiagent.benchmark.m4_pilot --check | grep x",  # pipe subshell
             "11 10 timeout 300 python -m multiagent.benchmark.m4_pilot --check",
             "12 11 python -m multiagent.benchmark.m4_pilot --check",
             "98 5 /bin/bash -c python -m multiagent.benchmark.m4_pilot --run --allow-model-calls",    # another command
             "99 98 python -m multiagent.benchmark.agents_pilot --run --allow-model-calls"]
    assert ap.concurrent_pilots(lines, {"10", "11", "12"}) == [lines[4], lines[5]]
    assert str(__import__("os").getpid()) in ap.own_lineage()
