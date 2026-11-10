"""Builds ONE pin revision of the 31/10 clock-path preparation; host files only, nothing executed.

Run from the repository root:  .venv/bin/python evaluation/operations/rover_xrce_pin_revision_2026_11_04/prepare_revision.py <out_dir>
Reads the sealed preparation, never writes to it. The new reader manifest differs from the
historical one ONLY in source_hashes of files whose current content differs; binary, native
dependencies, reviews and provenance are copied unchanged. selection_dry_run is run for both.
"""
import copy, difflib, hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path.cwd()
PREP_ID = '54b7adc8-690b-4da1-98fa-eacdc78e9e0e'
BASE = ROOT / 'evaluation/operations/rover_clock_path_preparation_2026_10_31' / PREP_ID
PREP, FROZEN = BASE / 'preparation', BASE / 'frozen-host-sources'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(out):
    from tools.rover_xrce_trace.passive_trial import selection_dry_run
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('refusing: output directory not empty')
    (out / 'preparation').mkdir(parents=True)
    (out / 'diffs').mkdir()
    reader = json.loads((PREP / 'reader.prepared.json').read_text())
    revised = copy.deepcopy(reader)
    changed = []
    for name, old in sorted(reader['source_hashes'].items()):
        current = sha(ROOT / name)
        if current == old:
            continue
        frozen = FROZEN / name
        if sha(frozen) != old:
            raise SystemExit(f'frozen copy of {name} does not match its historical pin')
        patch = ''.join(difflib.unified_diff(frozen.read_text().splitlines(True), (ROOT / name).read_text().splitlines(True),
                                             f'historical/{name}', f'current/{name}'))
        patch_path = out / 'diffs' / (name.replace('/', '__') + '.patch')
        patch_path.write_text(patch)
        commits = git('log', '--format=%h %ad %s', '--date=short', '--since=2026-10-31', '--', name).splitlines()
        changed.append({'path': name, 'historical_sha256': old, 'current_sha256': current,
                        'historical_copy': str(frozen.relative_to(ROOT)), 'diff': str(patch_path.relative_to(out)),
                        'changed_lines': sum(1 for l in patch.splitlines() if l[:1] in '+-' and l[:3] not in ('+++', '---')),
                        'commits_since_preparation': commits, 'review': 'PENDING_HUMAN_REVIEW'})
        revised['source_hashes'][name] = current
    for key in reader:
        if key != 'source_hashes' and reader[key] != revised[key]:
            raise SystemExit('only source_hashes may change')
    (out / 'preparation' / 'reader.prepared.json').write_text(json.dumps(revised, indent=1, sort_keys=True) + '\n')
    args = dict(socket_helper_review=PREP / 'socket-helper-review.json')
    historical = selection_dry_run(ROOT, PREP / 'agent.prepared.json', PREP / 'reader.prepared.json', **args)
    new = selection_dry_run(ROOT, PREP / 'agent.prepared.json', out / 'preparation' / 'reader.prepared.json', **args)
    # The embedded host-helper review must name the new simulation_lifecycle.py hash. Writing it would
    # ASSERT a review nobody has done: it is left as a PENDING template, and the effect of accepting it
    # is only computed in a temporary directory (never persisted as a manifest).
    host_change = {k: {'before': reader['helper_review']['host_source_review']['source_changes'][k]['after'],
                       'after': revised['source_hashes'][k]}
                   for k in sorted(reader['helper_review']['host_source_review']['source_changes'])}
    template = {'schema': 'tfg.passive-host-helper-review/1', 'status': 'PENDING_HUMAN_REVIEW_NOT_A_REVIEW',
                'source_changes': host_change, 'reviewer': '<<REVIEWER_REQUIRED>>', 'scope': '<<REVIEW_SCOPE_REQUIRED>>',
                'native_binary_unchanged': revised['binary'] == reader['binary'],
                'native_dependencies_unchanged': revised['native_dependencies'] == reader['native_dependencies'],
                'diffs': [c['diff'] for c in changed if c['path'] in host_change], 'runtime_checked': False}
    (out / 'host-source-review.pending.json').write_text(json.dumps(template, indent=1, sort_keys=True) + '\n')
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        what_if = copy.deepcopy(revised)
        for k, v in host_change.items():
            what_if['helper_review']['host_source_review']['source_changes'][k]['after'] = v['after']
        path = Path(tmp) / 'reader.json'
        path.write_text(json.dumps(what_if))
        hypothetical = selection_dry_run(ROOT, PREP / 'agent.prepared.json', path, **args)
    descriptor = {
        'schema': 'tfg.rover.xrce-pin-revision/1', 'status': 'PREPARED_FOR_REVIEW_NOT_AUTHORIZED_NOT_APPLIED',
        'prepared_at_head': git('rev-parse', 'HEAD'), 'supersedes_draft': 'Codex xrce-pin-review-proposal.json (base 8067f8b03)',
        'predecessor': {'preparation': str(PREP.relative_to(ROOT)),
                        'files_sha256': {p.name: sha(p) for p in sorted(PREP.iterdir())},
                        'seal_sha256': sha(BASE / 'SHA256SUMS')},
        'changed_pins': changed, 'unchanged_pins': len(reader['source_hashes']) - len(changed),
        'unchanged_fields': sorted(k for k in reader if k != 'source_hashes'),
        'binary_sha256': reader['binary'].get('sha256'),
        'selection_dry_run': {'historical_reader': historical, 'revised_reader': new,
                              'hypothetical_after_host_review_accepted': {
                                  **hypothetical, 'basis': 'COMPUTED_IN_TEMPORARY_DIRECTORY_NOT_PERSISTED'}},
        'host_source_review': 'host-source-review.pending.json (PENDING, not a review)',
        'authorization': 'NOT_PROVIDED', 'operational_actions_performed': False,
        'valid_only_while_current_sources_match': True,
        'pending': ['Human review of each diff (Joel; Codex owns these files)',
                    'Exact authorization by Joel naming this descriptor digest before any use',
                    'Current host/container/lifecycle facts in a separately authorized procedure',
                    'Precheck at the time of use; any later change of a pinned file blocks selection again']}
    (out / 'revision.json').write_text(json.dumps(descriptor, indent=1, sort_keys=True) + '\n')
    return descriptor


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    d = main(sys.argv[1])
    print(json.dumps({'revised_valid': d['selection_dry_run']['revised_reader']['selection_files_valid'],
                      'hypothetical_valid': d['selection_dry_run']['hypothetical_after_host_review_accepted']['selection_files_valid'],
                      'historical_valid': d['selection_dry_run']['historical_reader']['selection_files_valid'],
                      'changed': [c['path'] for c in d['changed_pins']]}, indent=1))
