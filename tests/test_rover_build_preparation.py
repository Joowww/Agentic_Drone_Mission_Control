"""Exact local rebuild selection, with synthetic source and dependency files only."""
import json

import pytest

from tests.test_rover_transport_driver import selection
from tools.rover_xrce_trace import selection as s, passive_trial as d


def test_reviewed_rebuild_pair_accepts_large_installed_dependency_closure(selection):
    root,ap,rp,agent,reader=selection
    agent.update(dict(zip((k+'_sha256' for k in ('wrapper','library','bridge','bridge_library')),s.RPC_PREPARED_ARTIFACTS)))
    reader['agent_selection_sha256']=s.digest(agent)
    reader['native_dependencies']={f'/usr/lib/x86_64-linux-gnu/synthetic-{i}.so':'a'*64 for i in range(66)}
    ap.write_text(json.dumps(agent));rp.write_text(json.dumps(reader))
    assert s.check_manifest(agent)==agent
    assert d.selection_dry_run(root,ap,rp)['selection_files_valid'] is True


@pytest.mark.parametrize('key',['wrapper','library'])
def test_rebuild_and_historical_pair_cannot_be_mixed(selection,key):
    _,_,_,agent,_=selection
    agent[key+'_sha256']=s.RPC_PREPARED_ARTIFACTS[0 if key=='wrapper' else 1]
    with pytest.raises(ValueError,match='incompatible'):s.check_manifest(agent)


def test_dependency_closure_remains_bounded(selection):
    root,ap,rp,_,reader=selection
    reader['native_dependencies']={f'/usr/lib/x86_64-linux-gnu/synthetic-{i}.so':'a'*64 for i in range(257)}
    rp.write_text(json.dumps(reader))
    with pytest.raises(ValueError,match='dependency'):d.LocalPorts(root,root,ap,rp)
