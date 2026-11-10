import ast
import hashlib
from pathlib import Path

from tools.rover_xrce_trace import historical_disposition as disposition
from tools.rover_xrce_trace import present_resources

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'tools/rover_xrce_trace/reader_compat/present_resources_v1.py'
CURRENT = ROOT / 'tools/rover_xrce_trace/present_resources.py'


def assignments(path):
    tree = ast.parse(path.read_text())
    return {node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {'SCHEMA', 'WIRE_SCHEMA'}}


def test_historical_source_copy_matches_the_original_audit_reader_pin():
    assert hashlib.sha256(LEGACY.read_bytes()).hexdigest() == disposition.RESOURCE_READER_LEGACY_SHA256
    assert assignments(LEGACY) == {'SCHEMA': 'tfg.present-resources/1',
                                   'WIRE_SCHEMA': 'tfg.present-resources/2'}


def test_current_source_hash_and_schemas_are_explicitly_pinned():
    assert hashlib.sha256(CURRENT.read_bytes()).hexdigest() == disposition.RESOURCE_READER_CURRENT_SHA256
    assert assignments(CURRENT) == {'SCHEMA': present_resources.SCHEMA,
                                    'WIRE_SCHEMA': present_resources.WIRE_SCHEMA}
    assert present_resources.SCHEMA == 'tfg.present-resources/1'
    assert present_resources.WIRE_SCHEMA == 'tfg.present-resources/2'


def test_new_transition_names_both_exact_readers_and_introducing_commit():
    transition = disposition._verified_resource_reader_transition()
    assert transition['protocol'] == 'PRESENT_RESOURCE_READER_SUCCESSOR_V1'
    assert transition['pin'] == disposition.RESOURCE_READER_PIN
    assert transition['from_sha256'] == disposition.RESOURCE_READER_LEGACY_SHA256
    assert transition['to_sha256'] == disposition.RESOURCE_READER_CURRENT_SHA256
    assert transition['introduced_by_commit'] == 'd53f508ea312c4cd63d916a31890299ae35a4090'
    assert transition['reason'].endswith('retain TIME_WAIT as unavailable cooldown')


def test_unknown_code_bytes_fail_closed(monkeypatch):
    monkeypatch.setattr(disposition, 'RESOURCE_READER_CURRENT_SHA256', '0' * 64)
    try:
        disposition._verified_resource_reader_transition()
    except ValueError as exc:
        assert 'source bytes' in str(exc)
    else:
        raise AssertionError('Unknown current reader bytes must be rejected')


def test_missing_historical_source_fails_closed(monkeypatch):
    original = Path.read_bytes

    def missing_legacy(path):
        if path == LEGACY:
            raise OSError('synthetic missing source')
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', missing_legacy)
    try:
        disposition._verified_resource_reader_transition()
    except ValueError as exc:
        assert 'unavailable' in str(exc)
    else:
        raise AssertionError('Missing exact historical source must be rejected')
