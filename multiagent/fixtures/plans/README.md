# Example `.plan` for the demo (TEST_FIXTURE)

`red_target_aerial.plan` is the aerial part of the `red_target` scenario, written by Hermes' exporter
(`inputs.qgroundcontrol_exporter`, unchanged). The mission is: POI_1 `inspect` with `rgb`, and POI_3 `take_photo`
with `multispectral`.

`red_target_aerial.plan.semantics.json` is the semantics manifest from `multiagent.plan_semantics.export_with_manifest`.
It is bound to the `.plan` by its sha256 and keeps what a `.plan` cannot carry:
- the actions `inspect` and `take_photo`;
- the sensors;
- the waypoint ids.

A `.plan` also cannot carry the conditional rover task ("if a card is seen, send rover_01"). That task comes from the
operator, through the natural-language path.

Use them with:

```bash
python -m multiagent.demo --input-plan multiagent/fixtures/plans/red_target_aerial.plan \
    [--plan-manifest multiagent/fixtures/plans/red_target_aerial.plan.semantics.json]
```

They were generated on 07/11/2026 with `planned_home_amsl_m=584.0` and the site's declared georeference. They are
fixtures: do not edit them by hand. Any change to the `.plan` breaks the manifest binding, by design.
