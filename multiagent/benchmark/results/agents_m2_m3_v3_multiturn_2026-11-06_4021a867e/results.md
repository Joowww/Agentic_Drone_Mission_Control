# agents_m2_m3_v3_multiturn: results

Model ollama:qwen3:4b (359d7dd4bcda), generation {'temperature': 0.0, 'seed': 7, 'num_predict': 1024, 'think': False, 'num_ctx': 8192, 'timeout_s': 120.0}; dataset dev_v3; commit 4021a867efc24cc3f4108213d24213460bb554d1.
Real model calls: 8 of 12. Data kind: MODEL_OUTPUT_OVER_SYNTHETIC_CASES. Three cases per role: preliminary evidence, no statistics.

## M2-drone-qwen-pilot-v3-multiturn (drone_swarm_agent)

which eligible drone takes which aerial objective and in which order, and which verification tools to run; gate = evaluate_proposal + deconfliction; a rejected proposal falls back to the deterministic reference (recorded, never counted as an agent success)

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | True | True | - | PROPOSED_PENDING_AUTHORIZATION | True | 9.24 | 1153/112 | 1/2 |
| D05 | INFEASIBLE | INFEASIBLE | True | True | - | INFEASIBLE | True | 1.2 | 1090/105 | 1/1 |
| D13 | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | True | False | MODEL | PARTIAL_PENDING_AUTHORIZATION | True | 5.07 | 1426/234 | 1/6 |

- D01: final_allocation_from=MODEL; coordination_attempts=['CHOSEN:NOT_APPLICABLE']
- D05: final_allocation_from=MODEL; coordination_attempts=['CHOSEN:NOT_APPLICABLE']
- D13: final_allocation_from=DETERMINISTIC_ALTERNATIVE; coordination_attempts=['CHOSEN:UNRESOLVED', 'ALTERNATIVE_1:UNRESOLVED', 'ALTERNATIVE_2:NOT_APPLICABLE']

## M3-rover-qwen-pilot-v3-multiturn (rover_agent)

one typed decision per ground objective (plan to its declared POI, wait for an observation, or cannot plan with a closed reason) and the verification tools; rover_gate.check_v3 validates it against the facts and names the exact field for the one revision; the deterministic rover agent keeps the last word

| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D11 | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | True | True | - | PROPOSED_PENDING_AUTHORIZATION | True | 2.92 | 1067/123 | 1/1 |
| D12 | INFEASIBLE | INFEASIBLE | True | False | MODEL | INFEASIBLE | True | 2.68 | 1057/123 | 1/2 |
| D14 | INFEASIBLE | INFEASIBLE | True | True | - | INFEASIBLE | True | 1.31 | 1053/115 | 1/1 |

- D11: agreement=AGREES
- D12: agreement=DISAGREES_DETERMINISTIC_KEPT; rover_gate_findings=['DEPENDENCY_UNSATISFIED_TASK_PROPOSED at decisions[0].decision: no proposed drone task reaches POI_1']
- D14: agreement=AGREES

