"""Exact offline consumption of the reviewed clock-path preparation; no SDK."""
from pathlib import Path
import copy,json
import pytest
from tools.rover_xrce_trace.selection import check_manifest
from tools.rover_xrce_trace.passive_trial import selection_dry_run

ROOT=Path(__file__).resolve().parents[1]
PREP=ROOT/'evaluation/operations/rover_clock_path_preparation_2026_10_31/54b7adc8-690b-4da1-98fa-eacdc78e9e0e/preparation'
OLD=ROOT/'evaluation/operations/rover_status_diagnostic_build_2026_10_31/c29d228d-3170-49ca-a0cb-b93b5874b9f8/preparation'


def test_exact_pairs_remain_distinct_and_prior_manifest_is_accepted():
    old=json.loads((OLD/'agent.prepared.json').read_text())
    new=json.loads((PREP/'agent.prepared.json').read_text())
    assert check_manifest(old)==old and check_manifest(new)==new
    for field in ['rover_sha256','model_library_sha256']:
        mixed=copy.deepcopy(new);mixed[field]=old[field]
        with pytest.raises(ValueError,match='Unreviewed'):check_manifest(mixed)


def test_prior_file_selection_requires_explicit_closure_reader_derivation():
    result=selection_dry_run(ROOT,PREP/'agent.prepared.json',PREP/'reader.prepared.json',socket_helper_review=PREP/'socket-helper-review.json')
    assert not result['selection_files_valid'] and result['status']=='BLOCKED' and not result['executed']
    assert 'source differs' in result['reason']


def test_stale_closure_reader_review_cannot_select_changed_receiver_sources(tmp_path):
    import hashlib
    reader=json.loads((PREP/'reader.prepared.json').read_text())
    before=copy.deepcopy(reader)
    for name in ('tools/rover_xrce_trace/session_precheck.py','tools/rover_xrce_trace/historical_disposition.py'):
        reader['source_hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    path=tmp_path/'reader.json';path.write_text(json.dumps(reader))
    result=selection_dry_run(ROOT,PREP/'agent.prepared.json',path,socket_helper_review=PREP/'socket-helper-review.json')
    assert not result['selection_files_valid'] and result['status']=='BLOCKED' and not result['executed']
    assert result['reason']=='Receiver/helper source differs from reviewed preparation'
    assert reader['binary']==before['binary'] and reader['native_dependencies']==before['native_dependencies']
    reader['source_hashes']['tools/rover_xrce_trace/session_precheck.py']='0'*64
    path.write_text(json.dumps(reader))
    assert not selection_dry_run(ROOT,PREP/'agent.prepared.json',path,socket_helper_review=PREP/'socket-helper-review.json')['selection_files_valid']


@pytest.mark.parametrize('change',['timing-review','source','socket-review','binary'])
def test_missing_or_changed_review_cannot_select(tmp_path,change):
    reader=json.loads((PREP/'reader.prepared.json').read_text())
    if change=='timing-review':reader['helper_review']['status_source_review']['source_hashes'].pop('tools/rover_xrce_trace/prepare_timing.py')
    if change=='source':reader['source_hashes']['tools/rover_identity_probe/session_context.hpp']='0'*64
    if change=='binary':reader['binary']['sha256']='0'*64
    path=tmp_path/'reader.json';path.write_text(json.dumps(reader))
    result=selection_dry_run(ROOT,PREP/'agent.prepared.json',path,socket_helper_review=None if change=='socket-review' else PREP/'socket-helper-review.json')
    assert not result['selection_files_valid'] and not result['executed']
