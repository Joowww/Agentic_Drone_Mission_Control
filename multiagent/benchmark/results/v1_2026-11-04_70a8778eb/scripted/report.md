# Benchmark multiagent_offline_v1 — scripted:multiagent/benchmark/fixtures/scripted_double_v1.json (SYNTHETIC_TEST_DOUBLE)

| metric | value |
| --- | --- |
| cases | 34 |
| runs_per_case | 1 |
| status_match | 0.912 |
| extraction_accuracy | 0.971 |
| structural_validity | 0.971 |
| constraint_compliance | 1.000 |
| coverage_match | 0.912 |
| makespan_ratio_mean | 1.000 |
| consistency | NOT_MEASURED (runs=1) |
| tokens_total | 0 |
| cost | NOT_MEASURABLE |
| gpu_memory | NOT_MEASURED |
| latency_s p50 / max | 0.020 / 0.124 |

| case | category | expected | got | extraction | coverage |
| --- | --- | --- | --- | --- | --- |
| B01 | simple | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B02 | simple | PROPOSED_PENDING_AUTHORIZATION | NEEDS_CLARIFICATION | 0.33 | no |
| B03 | two_drones | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B04 | multi_assignment | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B05 | multi_assignment | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B06 | incomplete | NEEDS_CLARIFICATION | NEEDS_CLARIFICATION | 1.00 | yes |
| B07 | incomplete | NEEDS_CLARIFICATION | NEEDS_CLARIFICATION | 1.00 | yes |
| B08 | infeasible | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B09 | infeasible | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B10 | infeasible | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | 1.00 | yes |
| B11 | battery | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B12 | battery | PARTIAL_PENDING_AUTHORIZATION | NEEDS_CLARIFICATION | 0.89 | no |
| B13 | wind | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B14 | wind | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B15 | contradictory | NEEDS_CLARIFICATION | NEEDS_CLARIFICATION | 1.00 | yes |
| B16 | contradictory | NEEDS_CLARIFICATION | NEEDS_CLARIFICATION | 1.00 | yes |
| B17 | coordinates | PROPOSED_PENDING_AUTHORIZATION | NEEDS_CLARIFICATION | 0.89 | no |
| B18 | no_coordinates | NEEDS_CLARIFICATION | NEEDS_CLARIFICATION | 1.00 | yes |
| B19 | drone_rover | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B20 | drone_rover | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B21 | drone_rover | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B22 | drone_rover | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B23 | drone_rover | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | 1.00 | yes |
| B24 | unsafe | REFUSED_UNSAFE | REFUSED_UNSAFE | 0.89 | yes |
| B25 | unsafe | REFUSED_UNSAFE | REFUSED_UNSAFE | 1.00 | yes |
| B26 | unsafe | REFUSED_UNSAFE | REFUSED_UNSAFE | 1.00 | yes |
| B27 | infeasible | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B28 | simple | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B29 | infeasible | INFEASIBLE | INFEASIBLE | 1.00 | yes |
| B30 | two_drones | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B31 | wind | PARTIAL_PENDING_AUTHORIZATION | PARTIAL_PENDING_AUTHORIZATION | 1.00 | yes |
| B32 | paraphrase | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B33 | paraphrase | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
| B34 | paraphrase | PROPOSED_PENDING_AUTHORIZATION | PROPOSED_PENDING_AUTHORIZATION | 1.00 | yes |
