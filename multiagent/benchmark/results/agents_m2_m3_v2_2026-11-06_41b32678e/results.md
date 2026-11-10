# agents_m2_m3_v2: results

Model ollama:qwen3:4b (359d7dd4bcda), generation {'temperature': 0.0, 'seed': 7, 'num_predict': 1024, 'think': False, 'num_ctx': 8192, 'timeout_s': 120.0}; dataset dev_v3; commit 41b32678ef15a5182804f2a58824284d169b0389.
Real model calls: 6 of 6. Data kind: MODEL_OUTPUT_OVER_SYNTHETIC_CASES. Three cases per role: preliminary evidence, no statistics.

## M2-drone-qwen-pilot-v2 (drone_swarm_agent)

which eligible drone takes which aerial objective and in which order, and which verification tools to run; gate = evaluate_proposal + deconfliction; a rejected proposal falls back to the deterministic reference (recorded, never counted as an agent success)

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | True | True | - | PROPOSED_PENDING_AUTHORIZATION | True | 7.82 | 1153/112 | 1/2 |
| D05 | INFEASIBLE | INFEASIBLE | True | True | - | INFEASIBLE | True | 1.2 | 1090/105 | 1/1 |
| D13 | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | True | False | MODEL | PARTIAL_PENDING_AUTHORIZATION | True | 2.56 | 1426/234 | 1/3 |

- D01: final_allocation_from=MODEL; coordination_attempts=['CHOSEN:NOT_APPLICABLE']
- D05: final_allocation_from=MODEL; coordination_attempts=['CHOSEN:NOT_APPLICABLE']
- D13: final_allocation_from=DETERMINISTIC_ALTERNATIVE; coordination_attempts=['CHOSEN:UNRESOLVED', 'ALTERNATIVE_1:UNRESOLVED', 'ALTERNATIVE_2:NOT_APPLICABLE']

## M3-rover-qwen-pilot-v2 (rover_agent)

the ground tasks (declared target, wait point) or what is missing, and which verification tools to run; the deterministic rover agent keeps the last word (advisory gate)

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D11 | PROPOSED_PENDING_AUTHORIZATION | NEEDS_CLARIFICATION | False | False | MODEL | PROPOSED_PENDING_AUTHORIZATION | True | 2.0 | 1017/143 | 1/1 |
| D12 | INFEASIBLE | NEEDS_CLARIFICATION | False | False | MODEL | INFEASIBLE | True | 1.43 | 1007/129 | 1/1 |
| D14 | INFEASIBLE | NEEDS_CLARIFICATION | False | False | MODEL | INFEASIBLE | True | 1.52 | 1007/140 | 1/1 |

- D11: agreement=DISAGREES_DETERMINISTIC_KEPT; rover_gate_findings=['EXECUTION_PRECONDITION_REPORTED_AS_MISSING: rover_01 is not authorized to execute tasks', 'WAIT_POINT_MISSING: G1: after_aerial is true, the wait point is POI_3']
- D12: agreement=DISAGREES_DETERMINISTIC_KEPT; rover_gate_findings=['WAIT_POINT_MISSING: G1: after_aerial is true, the wait point is POI_1']
- D14: agreement=DISAGREES_DETERMINISTIC_KEPT; rover_gate_findings=['ROVER_UNAVAILABLE_TASK_PROPOSED: G1: the declared rover is unavailable']

