"""Synthetic seq_file short reads: no Docker, ROS, live inventory or controls."""
import json
import os
from pathlib import Path
import pytest
from tools.rover_xrce_trace import socket_inventory as s
from tests.test_rover_socket_inventory import tree,HEADER,udp,put,writer,FixtureClock
from tools.rover_xrce_trace.budget import encode_row,journal_rows


def split_table_reads(monkeypatch,root,boundary=None):
    read=s.os.read
    # A legal line-complete first read, as /proc seq_file may return. It omits
    # the relevant socket placed in the following fragment. Not real topology.
    boundary=boundary or len((HEADER+udp(43,'00000000',2019)).encode())
    def fragmented(fd,n):
        if os.readlink('/proc/self/fd/'+str(fd))==str(root/'self/net/udp'):
            return read(fd,min(n,boundary))
        return read(fd,n)
    monkeypatch.setattr(s.os,'read',fragmented)


@pytest.mark.parametrize('background',['small','observed_endpoint_prefix'])
def test_capture_file_reader_association_requires_reading_beyond_first_page(tree,tmp_path,monkeypatch,background):
    root,expected=tree;prefix=HEADER+udp(43,'00000000',2019);count=2
    if background=='observed_endpoint_prefix':
        # The 30 retained endpoints are real. Inodes, row order and an extra
        # tail socket are SYNTHETIC: the real omitted tail cannot be recovered.
        history=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/container-capture/sockets.jsonl'
        row=s.unpack_inventory(json.loads(history.read_text().splitlines()[0]))
        endpoints=row['table_scope_before']['unmatched_local_endpoints']
        assert len(endpoints)==30
        prefix=HEADER+''.join(udp(1000+i,'00000000',v['port']) for i,v in enumerate(endpoints));count=31
    put(root,'self/net/udp',prefix+udp())
    split_table_reads(monkeypatch,root,len(prefix.encode()))
    # Demonstrate the old one-read parser accepts the incomplete first fragment.
    fd=os.open(root/'self/net/udp',os.O_RDONLY)
    try:first=s.os.read(fd,65537)
    finally:os.close(fd)
    assert len(s.table(first,'udp'))==count-1 and all(v['inode']!='42' for v in s.table(first,'udp'))
    row=s.collect(expected,reader=s.Reader(root,clock=FixtureClock()))
    assert row['snapshot_state']=='REPEATED_READS_AGREE'
    assert row['table_scope_before']['total_udp_rows']==count and row['table_scope_before']['read_completion']=='EOF_OBSERVED'
    assert row['size_diagnostics']['search_counts']['read_calls']<=s.MAX_READS
    path=tmp_path/'journal';path.write_bytes(encode_row(s.pack_inventory(row)))
    decoded=s.unpack_inventory(json.loads(next(journal_rows(path))))
    assert s.match_peer(decoded,writer(),expected['lifecycle_id'])['link_state']=='EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE'
    assert not decoded['source_association_verified']
    # A completion label without matching read provenance is rejected.
    for read in decoded['reads']:
        if read['source'].endswith('/net/udp'):read['operation']='bytes'
    with pytest.raises(ValueError):s.validate_inventory(decoded)


def test_budget_or_error_before_eof_is_incomplete_and_closes_file(tree,monkeypatch):
    root,expected=tree;put(root,'self/net/udp',HEADER+udp(43,'00000000',2019)+udp())
    split_table_reads(monkeypatch,root);reader=s.Reader(root,clock=FixtureClock())
    monkeypatch.setattr(s,'MAX_READS',1)
    before=len(list(Path('/proc/self/fd').iterdir()))
    with pytest.raises(s.Incomplete,match='BEFORE_EOF'):reader.get('self/net/udp')
    assert reader.reads[-1]['state']=='UNKNOWN' and reader.counts['read_calls']==1
    assert len(list(Path('/proc/self/fd').iterdir()))==before


def test_empty_udp_tables_are_complete_reads_but_not_absence_proof(tree):
    root,context=tree;put(root,'self/net/udp',HEADER)
    row=s.collect(context,reader=s.Reader(root,clock=FixtureClock()))
    assert row['snapshot_state']=='REPEATED_READS_AGREE' and row['tables_before']==[]
    assert row['table_scope_before']['read_completion']=='EOF_OBSERVED'
    assert s.match_peer(row,writer(),context['lifecycle_id'])['link_state']=='NOT_OBSERVED_NOT_ABSENCE_PROOF'


@pytest.mark.parametrize('bad',['truncated','read_error','file_budget'])
def test_read_failures_do_not_return_partial_usable_tables(tree,monkeypatch,bad):
    root,context=tree
    if bad=='truncated':put(root,'self/net/udp',(HEADER+udp()).rstrip('\n'))
    else:
        read=s.os.read
        def broken(fd,n):
            if os.readlink('/proc/self/fd/'+str(fd))==str(root/'self/net/udp'):
                if bad=='read_error':raise OSError(5,'synthetic IO failure')
                return b'x'*n  # no EOF; bounded at 65537, never retries forever
            return read(fd,n)
        monkeypatch.setattr(s.os,'read',broken)
    row=s.collect(context,reader=s.Reader(root,clock=FixtureClock()))
    assert row['snapshot_state']=='INCOMPLETE' and not row['associations']
