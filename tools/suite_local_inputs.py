"""Inventory of the local inputs the offline suite reads that Git does not carry (ignored evidence and state).

    python -m tools.suite_local_inputs --write docs/suite-local-inputs-<date>.json   # record the current inputs
    python -m tools.suite_local_inputs --check docs/suite-local-inputs-<date>.json   # compare with a record

Read only: lists the ignored paths with ``git status --ignored``, skips caches and environments, and records for each
path its file count and a SHA-256 over the sorted ``<relative path>  <file sha256>`` lines. ``--check`` exits 1 if
any path is missing, extra or different. It never copies, moves or changes the inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "tfg.suite-local-inputs/1"
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIXES = (".egg-info", ".pyc")
SKIP_NAMES = {".coverage"}


def ignored_paths(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--ignored"], capture_output=True,
                         text=True, check=True).stdout
    paths = []
    for line in out.splitlines():
        if not line.startswith("!! "):
            continue
        rel = line[3:].rstrip("/")
        parts = Path(rel).parts
        if any(p in SKIP_PARTS or p.endswith(SKIP_SUFFIXES) for p in parts) or Path(rel).name in SKIP_NAMES:
            continue
        paths.append(rel)
    return sorted(paths)


def digest(path: Path) -> dict:
    """{files, sha256} of a file or of every file under a directory (symlinks recorded by target, not followed)."""
    files = [path] if path.is_file() or path.is_symlink() else sorted(
        p for p in path.rglob("*") if p.is_file() or p.is_symlink())
    lines = []
    for f in files:
        rel = f.relative_to(path).as_posix() if f != path else f.name
        if f.is_symlink():
            value = "symlink:" + str(f.readlink())
        else:
            value = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{rel}  {value}\n")
    return {"files": len(files), "sha256": hashlib.sha256("".join(lines).encode()).hexdigest()}


def inventory(root: Path = ROOT) -> dict:
    return {"schema": SCHEMA, "method": "sha256 over sorted '<relative path>  <sha256 | symlink:target>' lines",
            "paths": {rel: digest(root / rel) for rel in ignored_paths(root)}}


def compare(recorded: dict, current: dict) -> list[str]:
    old, new = recorded.get("paths", {}), current.get("paths", {})
    return ([f"MISSING {p}" for p in sorted(set(old) - set(new))] + [f"EXTRA {p}" for p in sorted(set(new) - set(old))]
            + [f"DIFFERENT {p}" for p in sorted(set(old) & set(new)) if old[p] != new[p]])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path, help="write the current inventory here (refuses to overwrite)")
    mode.add_argument("--check", type=Path, help="compare the current inputs with this inventory")
    args = parser.parse_args(argv)
    current = inventory()
    if args.write:
        if args.write.exists():
            parser.error(f"{args.write} exists; an inventory is a dated record, write a new one")
        args.write.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{len(current['paths'])} paths recorded in {args.write}")
        return 0
    problems = compare(json.loads(args.check.read_text(encoding="utf-8")), current)
    print("\n".join(problems) if problems else f"{len(current['paths'])} paths match {args.check}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
