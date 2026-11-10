# Opik import: joowww / tfg-multiagent-benchmarks

Status: DRY RUN ONLY, nothing sent. `ledger.json` appears here only after an authorized send.

- `dry_run_E07.json`: the exact request bodies (traces/batch, spans/batch) of the first proposed trace, with
  its manifest; the authorization names their sha256.
- `manifest_pilot_all.json`: what would leave for the 11 qwen3:4b traces and the 11 rules traces of
  pilot_qwen3_4b_v1_2026-11-04_c00b737d3 (ids, span counts, request sizes and sha256, egress findings).
- `datasets_experiments.dry_run.json`: Opik dataset items (eval_v2, dev_v3, eval_v3, adversarial_v3) and the
  two experiments that real runs support; REST shapes unverified; never uploaded by this repository yet.
Regenerate with `python -m multiagent.opik_bridge dry-run <results_dir> --cases E07 --out <file>`; the bodies are
deterministic, so the sha256 must match.
