# agents_m1_m3_v1: results

Model ollama:qwen3:4b (359d7dd4bcda), generation {'temperature': 0.0, 'seed': 7, 'num_predict': 1024, 'think': False, 'num_ctx': 8192, 'timeout_s': 120.0}; dataset dev_v3; commit 776c7edd48f8e906e8305aea2f5c9cb8e13ba5b3.
Real model calls: 9 of 9. Data kind: MODEL_OUTPUT_OVER_SYNTHETIC_CASES. Three cases per role: preliminary evidence, no statistics.

## M1-supervisor-qwen-pilot (mission_orchestrator)

interpretation and decomposition of the operator text into the brief /2 (aerial and ground objectives, vehicles, availability, missing information, unsafe signals); delegation, consolidation, coordination checks and revision requests are the supervisor's deterministic graph

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | PROPOSED_PENDING_AUTHORIZATION | REFUSED_UNSAFE | False | False | MODEL | NEEDS_CLARIFICATION | False | 9.96 | 888/225 | 0/0 |
| D04 | NEEDS_CLARIFICATION | REFUSED_UNSAFE | False | False | MODEL | NEEDS_CLARIFICATION | True | 2.5 | 882/241 | 0/0 |
| D06 | REFUSED_UNSAFE | REFUSED_UNSAFE | True | True | - | PROPOSED_PENDING_AUTHORIZATION | False | 1.9 | 889/179 | 0/0 |

- D01: parse_error=['MODEL_REPLY_NOT_A_BRIEF: 1 errors']

## M2-drone-qwen-pilot (drone_swarm_agent)

which eligible drone takes which aerial objective and in which order, and which verification tools to run; gate = evaluate_proposal + deconfliction; a rejected proposal falls back to the deterministic reference (recorded, never counted as an agent success)

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | True | True | - | PROPOSED_PENDING_AUTHORIZATION | True | 1.83 | 1098/135 | 1/2 |
| D05 | INFEASIBLE | INFEASIBLE | True | False | MODEL | INFEASIBLE | True | 1.24 | 1035/106 | 1/2 |
| D13 | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | True | False | MODEL | PARTIAL_PENDING_AUTHORIZATION | True | 2.64 | 1371/233 | 1/3 |

- D01: final_allocation_from=MODEL; coordination_attempts=['CHOSEN:NOT_APPLICABLE']
- D05: final_allocation_from=DETERMINISTIC_REFERENCE; coordination_attempts=['CHOSEN:NOT_APPLICABLE']; agent_violations=['INELIGIBLE: A1 -> SENSOR_MISSING: drone_01 has no multispectral sensor']
- D13: final_allocation_from=DETERMINISTIC_ALTERNATIVE; coordination_attempts=['CHOSEN:UNRESOLVED', 'ALTERNATIVE_1:UNRESOLVED', 'ALTERNATIVE_2:NOT_APPLICABLE']

## M3-rover-qwen-pilot (rover_agent)

the ground tasks (declared target, wait point) or what is missing, and which verification tools to run; the deterministic rover agent keeps the last word (advisory gate)

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D11 | PROPOSED_PENDING_AUTHORIZATION | NEEDS_CLARIFICATION | False | False | MODEL | PROPOSED_PENDING_AUTHORIZATION | True | 1.88 | 831/131 | 1/1 |
| D12 | INFEASIBLE | NEEDS_CLARIFICATION | False | False | MODEL | INFEASIBLE | True | 1.49 | 821/133 | 1/1 |
| D14 | INFEASIBLE | NEEDS_CLARIFICATION | False | False | MODEL | INFEASIBLE | True | 1.64 | 821/148 | 1/1 |

- D11: agreement=DISAGREES_DETERMINISTIC_KEPT
- D12: agreement=DISAGREES_DETERMINISTIC_KEPT
- D14: agreement=DISAGREES_DETERMINISTIC_KEPT

