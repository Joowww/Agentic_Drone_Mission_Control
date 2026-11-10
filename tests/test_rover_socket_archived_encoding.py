"""Pure serialization of original saved rows; no proc, SDK or ROS reads."""
import copy
import json
from pathlib import Path

import pytest
from tools.rover_xrce_trace import socket_inventory as s

ARCHIVE=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_050_authorized_capture_2026_10_30/e7fc9f9b-76d9-42a5-8276-e852a17451ad'
OWNER='5be209d5-7856-4e9e-bc6f-70d19f0c2c4e'


@pytest.mark.parametrize('index',[0,1])
def test_real_archived_wire_and_accounting_are_byte_identical(index):
    records=json.loads((ARCHIVE/'sdk-file-index.json').read_bytes())
    matches=[v for v in records if v['path']=='/tmp/tfg_diagnostic_agents/'+OWNER+'/capture/sockets.jsonl']
    assert len(matches)==1
    raw=(ARCHIVE/matches[0]['archive_path']).read_bytes().splitlines(keepends=True)[index]
    original=json.loads(raw);row=s.unpack_inventory(original)
    assert s.pack_inventory(row)==original
    expected=copy.deepcopy(row);counts=row.pop('size_diagnostics')['search_counts']
    actual=s._account_inventory(row,counts)
    assert actual==expected
    assert (json.dumps(s.pack_inventory(actual),separators=(',',':')).encode()+b'\n')==raw
    assert actual['snapshot_state']=='REPEATED_READS_AGREE'
    assert actual['table_scope_before']['read_completion']=='EOF_OBSERVED'
    assert actual['table_scope_after']['read_completion']=='EOF_OBSERVED'
