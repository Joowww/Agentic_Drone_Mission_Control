"""Identifiers that only exist in earlier, pinned revisions and in sealed evidence.

Current code uses neutral, descriptive names. A few earlier names are still needed at run time, and only to interoperate
with code or data that cannot change: rover code extracted from a pinned commit (historical snapshots), bridge sources
read from a pinned commit by the rover bridge contract test, and sealed evidence. They are collected here, so no other
current module repeats them. Reproducing a sealed evidence directory exactly is done at the commit recorded in its name
and README; the mapping below helps to read those records with the current names.
"""
from __future__ import annotations

# provenance.source written by the rover adapter (tools/rover_agent_adapter.py) in the pinned snapshot revisions
# (57a0e303a, 2e206f1fa + reviewed patch, 1514053da). It is part of the plan digest, so a plan scope computed for one
# of those snapshots must use exactly this value.
SNAPSHOT_ADAPTER_PROVENANCE_SOURCE = "claude-rover-executor-bridge"

# The multi-agent bridge sources pinned by tests/test_rover_bridge_contract.py, read with ``git show`` at this commit,
# under their file names AT THAT COMMIT (renamed later; see RENAMED), with the SHA-256 the test requires.
PINNED_BRIDGE_COMMIT = "8fed7dc39770c70eb599c9e41d17c9ede7bb52e8"
PINNED_BRIDGE_SOURCES = {
    "codex_v2_bridge.py": "0b9106fbf8db3eda682ef58a7a85e8f7718d603e9436218d5d304bdaa4ab1685",
    "rover_executor_bridge.py": "2d13cbd98d1e70aeb8d8a41174d9b7e38f4cb8f813d2718e633e88540b1b4e0e",
    "human_authorization.py": "69287460581fc0f4330a7c4940c135d39127e5efeaba0f0f5f8818c52bfb075c",
}
PINNED_V2_BRIDGE_FILE = "codex_v2_bridge.py"

# Commit that registered each sealed pilot's manifest before any model call. Pinned because it is provenance of the
# sealed evidence: the commit that adds the file in the current branch's history can differ (for example after the
# history is consolidated into fewer commits), and the verification compares the manifest with this exact commit.
PILOT_MANIFEST_REGISTRATIONS = {"m4c_r1_integrated_v1": "ac92b087f"}

# The development history of the integration, kept unrewritten in this local annotated tag after main was
# consolidated into one commit, and the tips of the source branches as they were integrated (or deliberately not).
DEVELOPMENT_HISTORY_TAG = "archive/integration-history-2026-11-10"
INTEGRATED_BRANCH_TIPS = {
    "feature/hermes-integration": "83a147dda9065c812e0ff3b931cb22948fe52346",
    "feature/natural-language-qgc-plan": "da70f5f07ac95e20d3da67926e7c681706d029b7",
    "feature/ardupilot-ros2": "7e8855f6a288dd5c5354b7201329b561da89f024",
}

# Earlier name -> current name, for reading sealed evidence and earlier documentation. Not used to accept old values:
# current code emits and accepts only the current names.
RENAMED = {
    "modules": {
        "multiagent/codex_v2_bridge.py": "multiagent/rover_v2_bridge.py",
        "multiagent/codex_snapshot_runner.py": "multiagent/rover_snapshot_runner.py",
        "multiagent/benchmark/codex_adapter_evidence.py": "multiagent/benchmark/rover_adapter_evidence.py",
        "multiagent/fixtures/codex_contract_mission_execution_v1_cases.json":
            "multiagent/fixtures/rover_contract_mission_execution_v1_cases.json",
        "tests/test_rover_claude_bridge_contract.py": "tests/test_rover_bridge_contract.py",
        "tests/test_multiagent_codex_contract.py": "tests/test_multiagent_rover_contract_v1.py",
        "tests/test_multiagent_codex_v2_contract.py": "tests/test_multiagent_rover_v2_contract.py",
        "tests/test_multiagent_codex_integration_v2.py": "tests/test_multiagent_rover_integration_v2.py",
        "tests/test_multiagent_codex_adapter_contract.py": "tests/test_multiagent_rover_adapter_contract.py",
    },
    "cli_options": {"--codex-snapshot": "--rover-snapshot", "--codex-reviewed": "--rover-reviewed"},
    "conversion_owners": {"CODEX_ADAPTER": "ROVER_ADAPTER", "CLAUDE_FRAMES2D": "MULTIAGENT_FRAMES2D"},
    "statuses_and_reasons": {
        "V2_READY_AWAITING_CODEX_ADAPTER": "V2_READY_AWAITING_ROVER_ADAPTER",
        "CONVERSION_DELEGATED_TO_CODEX_ADAPTER": "CONVERSION_DELEGATED_TO_ROVER_ADAPTER",
        "CODEX_ADAPTER_NOT_IN_SNAPSHOT": "ROVER_ADAPTER_NOT_IN_SNAPSHOT",
        "CODEX_ADAPTER_IN_SNAPSHOT_NOT_INTEGRATED": "ROVER_ADAPTER_IN_SNAPSHOT_NOT_INTEGRATED",
        "CLAUDE_FRAMES2D_IS_OFFLINE_TEST_ONLY": "MULTIAGENT_FRAMES2D_IS_OFFLINE_TEST_ONLY",
        "REFERENCED_BY_CODEX_CODE": "REFERENCED_BY_ROVER_CODE",
        "OPERATOR_RECEIPT_NOT_BOUND_TO_CODEX_PLAN": "OPERATOR_RECEIPT_NOT_BOUND_TO_ROVER_PLAN",
    },
    "trace_keys": {"codex_bridge": "rover_bridge", "codex_v2": "rover_v2", "codex_snapshot": "rover_snapshot",
                   "codex_commit": "rover_commit", "codex_contract_sha256": "rover_contract_sha256",
                   "codex_scope_sha256": "rover_scope_sha256", "codex_matrix": "rover_matrix"},
    "values": {"claude-rover-executor-bridge": "multiagent-rover-executor-bridge",
               "claude.multiagent.frames2d": "multiagent.frames2d", "claude-multiagent": "multiagent-planner",
               "codex-protected-ardurover-executor": "protected-ardurover-executor",
               "code_codex_uncommitted": "code_rover_uncommitted"},
}
