"""Inventory of the drafts store (path, size, sha256, mtime_ns) and its comparison. Read-only on the store."""
import hashlib
import json
import sys
from pathlib import Path

STORE = Path("/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/drafts")


def inventory():
    files = {}
    for path in sorted(STORE.rglob("*")):
        if path.is_file():
            stat = path.stat()
            files[path.relative_to(STORE).as_posix()] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"store": "missions/generated/drafts", "files": files,
            "directories": sorted(p.relative_to(STORE).as_posix() for p in STORE.iterdir() if p.is_dir())}


def compare(before, after):
    b, a = before["files"], after["files"]
    created = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    modified = sorted(p for p in set(a) & set(b) if a[p]["sha256"] != b[p]["sha256"])
    touched = sorted(p for p in set(a) & set(b) if a[p]["sha256"] == b[p]["sha256"] and a[p]["mtime_ns"] != b[p]["mtime_ns"])
    return {"created": created, "removed": removed, "modified": modified, "mtime_changed_same_content": touched,
            "new_directories": sorted(set(after["directories"]) - set(before["directories"])),
            "previous_files_unchanged": not removed and not modified,
            "incident": bool(removed or modified)}


if __name__ == "__main__":
    if sys.argv[1] == "snapshot":
        Path(sys.argv[2]).write_text(json.dumps(inventory(), indent=2) + "\n")
    else:
        before, after = (json.loads(Path(p).read_text()) for p in sys.argv[2:4])
        result = compare(before, after)
        Path(sys.argv[4]).write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
