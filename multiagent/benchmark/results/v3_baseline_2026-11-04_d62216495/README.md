# v3 baselines: sealed record (04/11/2026, commit d62216495)

Deterministic candidates only; no model was run. Pipeline v2 (brief /2 availability, safety/2).
- oracle = hand-written gold /2 briefs (checks the specification);
- rules = the frozen rules interpreter of eval_v2 (brief /1, so it never reports availability), 2 runs.
eval_v3 and adversarial_v3 were frozen in commit bc04a2557 (frozen_check MATCH in each report) before these runs; the code is the committed tree of the commit named above, unmodified during the run.
Do not edit or regenerate; a later run goes into a new directory. Integrity: sha256sum -c SHA256SUMS.
