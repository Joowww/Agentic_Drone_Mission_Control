"""REPLAY of sealed pilots: verified evidence only, no model call, refused when tampered, modes kept apart."""
import io
import shutil

import pytest

from multiagent import demo, replay
from multiagent.benchmark import run as bench

RES = bench.ROOT / "multiagent/benchmark/results"
M4C_R1 = RES / "m4c_r1_integrated_v1_2026-11-07_f1ec396c9"


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a replay must never reach a model or the network")
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("socket.socket.connect", refuse)



def require_sealed_registration():
    """Replaying sealed evidence verifies it against the commit that registered its manifest (pinned revision)."""
    from multiagent.historical_identifiers import PILOT_MANIFEST_REGISTRATIONS
    from tests.history_requirements import require_commits
    require_commits(PILOT_MANIFEST_REGISTRATIONS["m4c_r1_integrated_v1"])

def run(path):
    buf = io.StringIO()
    return replay.replay(path, out=buf), buf.getvalue()


def test_the_m4c_r1_replay_shows_the_recorded_events_of_the_three_agents():
    require_sealed_registration()
    r, text = run(M4C_R1)
    assert r["status"] == "REPLAYED" and r["llm_calls"] == 4 and text.startswith("[replay] mode          REPLAY (of sealed evidence)")
    assert text.count(" llm_call  #") == 4 and "drone_swarm_agent      MODEL_SUCCESS_FIRST_ROUND" in text
    assert "resolved by the deterministic deconfliction" in text and "commands sent 0" in text
    assert "phase-A rover tool results (requested in its reply) were not written by this run" in text
    order = [line.split("#")[1].split(":")[0] for line in text.splitlines() if " llm_call  #" in line]
    assert order == ["1 mission_orchestrator", "2 drone_swarm_agent", "3 rover_agent", "4 rover_agent"]


def test_a_failed_pilot_replays_as_it_was():
    r, text = run(RES / "m4b_integrated_v1_2026-11-06_07db60a37")
    assert r["status"] == "REPLAYED" and r["llm_calls"] == 1 and "MISSION_NEEDS_CLARIFICATION" in text


def test_tampered_evidence_is_refused(tmp_path):
    copy = tmp_path / M4C_R1.name
    shutil.copytree(M4C_R1, copy)
    (copy / "demo/result.json").write_text((copy / "demo/result.json").read_text().replace('"commands_sent": 0',
                                                                                            '"commands_sent": 1'))
    r, text = run(copy)
    assert r["status"] == "REFUSED_UNVERIFIED" and text.startswith("REFUSED")


def test_the_cli_replay_and_the_existing_commands(capsys):
    require_sealed_registration()
    assert demo.main(["--replay", str(M4C_R1)]) == 0
    assert "REPLAY (of sealed evidence)" in capsys.readouterr().out
    assert demo.main(["--list-scenarios"]) == 0
    assert len([l for l in capsys.readouterr().out.splitlines() if l.strip()]) == 17
    assert demo.main(["--scenario", "red_target"]) == 0
    out = capsys.readouterr().out
    assert "OFFLINE_DETERMINISTIC: scripted test doubles" in out and "---- [10/10] final state ----" in out
    assert "set by the deterministic deconfliction, not by the drone agent" in out


def test_the_replay_shows_the_recorded_tools_and_what_is_missing():
    require_sealed_registration()
    r, text = run(M4C_R1)
    assert "drone agent          drone_capabilities=OK, validate_route=OK, validate_route=OK, check_separation=OK" in text
    assert "rover agent phase A  NOT RECORDED in this run" in text
    assert "rover agent phase B  rover_capabilities=OK, validate_ground_target=OK" in text


def test_the_cli_rover_handoff_option(capsys, tmp_path):
    from multiagent import rover_handoff as rh
    try:
        snap = rh.ensure_snapshot(tmp_path / "snap")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover contract commit not available: {exc}")
    assert demo.main(["--scenario", "red_target", "--rover-snapshot", str(snap)]) == 0
    out = capsys.readouterr().out
    assert "[rover]         executor_admit    BLOCKED" in out and "commands 0; movement executed False" in out
    assert "rover_route" in out and "tools         drone agent tool calls" in out
    assert demo.main(["--scenario", "no_target", "--rover-snapshot", str(snap)]) == 0
    assert "nothing to hand off" in capsys.readouterr().out
    with pytest.raises(SystemExit):  # the reviewed patch exists only for a historical snapshot
        demo.main(["--battery", "--rover-reviewed"])


def test_the_cli_rover_handoff_uses_this_repository_rover_code(capsys):
    assert demo.main(["--scenario", "red_target", "--rover-handoff"]) == 0
    out = capsys.readouterr().out
    assert "imported in-process" in out and "immutable snapshot" not in out
    assert "[rover]         executor_admit    BLOCKED" in out and "commands 0; movement executed False" in out


def test_the_cli_shows_conversion_payload_and_envelope_on_the_reviewed_snapshot(capsys, tmp_path):
    from multiagent import rover_handoff as rh
    try:
        snap = rh.ensure_snapshot(tmp_path / "rev", reviewed=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover snapshot unavailable: {exc}")
    assert demo.main(["--scenario", "red_target", "--rover-snapshot", str(snap), "--rover-reviewed"]) == 0
    out = capsys.readouterr().out
    assert "converted once by multiagent.frames2d" in out and "schema errors 0" in out
    assert "READY_TO_SUBMIT_NOT_EXECUTED (not a command)" in out and "SYNTHETIC_SENSOR" in out
