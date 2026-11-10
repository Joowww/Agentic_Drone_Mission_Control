"""Inventory of the suite's ignored local inputs: digest stability and comparison (temporary directories only)."""
from __future__ import annotations

from tools import suite_local_inputs as inv


def test_digest_depends_on_names_and_contents_not_on_order(tmp_path):
    a = tmp_path / "a"
    (a / "x").mkdir(parents=True)
    (a / "x" / "1.json").write_text("{}")
    (a / "2.txt").write_text("two")
    first = inv.digest(a)
    assert first["files"] == 2 and inv.digest(a) == first
    (a / "2.txt").write_text("changed")
    assert inv.digest(a)["sha256"] != first["sha256"]
    (a / "2.txt").write_text("two")
    (a / "2.txt").rename(a / "3.txt")
    assert inv.digest(a)["sha256"] != first["sha256"]


def test_compare_reports_missing_extra_and_different():
    recorded = {"paths": {"a": {"files": 1, "sha256": "x"}, "b": {"files": 1, "sha256": "y"}}}
    current = {"paths": {"a": {"files": 1, "sha256": "x"}, "b": {"files": 2, "sha256": "z"}, "c": {}}}
    assert inv.compare(recorded, current) == ["EXTRA c", "DIFFERENT b"]
    assert inv.compare(current, recorded) == ["MISSING c", "DIFFERENT b"]
    assert inv.compare(recorded, recorded) == []


def test_ignored_paths_skip_caches_and_environments():
    paths = inv.ignored_paths()
    assert not any(part in inv.SKIP_PARTS for p in paths for part in p.split("/"))
