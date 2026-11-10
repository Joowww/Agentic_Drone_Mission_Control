"""Frozen, verifiable Hermes source for the planning image: exactly NousResearch/hermes-agent at COMMIT.

The archive holds the RAW blobs of the commit's tree (no working tree, no .git, no checkout filters such as the
repository's eol=crlf rules, no config, credentials or virtual environment), as a deterministic tar: sorted paths,
mtime = commit time, uid/gid 0, modes 0644/0755. ``verify`` recomputes the git tree hash from the archive itself and
requires TREE (the tree GitHub reports for COMMIT), so it proves byte equality with the commit without git.

    hermes_source.py export --repo PATH --out TAR     from any local clone that holds COMMIT (objects only)
    hermes_source.py fetch --out TAR [--timeout S]    the same, from a fresh shallow fetch of the official repo
    hermes_source.py verify TAR                       exit 0 only if TAR's tree hash is TREE
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

URL = "https://github.com/NousResearch/hermes-agent.git"
COMMIT = "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
TREE = "5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0"
MODES = {"100644": 0o644, "100755": 0o755}


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True).stdout


def export(repo: Path, out: Path) -> str:
    if out.exists():
        raise SystemExit(f"{out} exists; archives are never overwritten")
    if _git(repo, "cat-file", "-t", COMMIT).strip() != b"commit":
        raise SystemExit(f"{COMMIT} is not a commit in {repo}")
    if _git(repo, "rev-parse", f"{COMMIT}^{{tree}}").decode().strip() != TREE:
        raise SystemExit("the commit's tree is not the expected tree")
    when = int(_git(repo, "show", "-s", "--format=%ct", COMMIT))
    entries = []
    for record in _git(repo, "ls-tree", "-r", "-z", "--full-tree", COMMIT).split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        if kind != "blob" or mode not in MODES:
            raise SystemExit(f"unsupported entry {mode} {kind} {path!r} (submodule, symlink or other)")
        entries.append((path.decode(), mode, blob))
    entries.sort()
    batch = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "x", format=tarfile.PAX_FORMAT) as archive:
        for path, mode, blob in entries:
            batch.stdin.write(blob.encode() + b"\n")
            batch.stdin.flush()
            header = batch.stdout.readline().split()
            data = batch.stdout.read(int(header[2]))
            batch.stdout.read(1)
            if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != blob:
                raise SystemExit(f"object {blob} does not hash to its id")
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime = len(data), MODES[mode], when
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    batch.stdin.close()
    batch.wait()
    return verify(out)


def _tree_hash(files: dict[str, tuple[str, bytes]]) -> str:
    """Git tree hash of {path: (mode, blob_sha1_hex)}."""
    children: dict[str, dict] = {}
    for path, (mode, sha) in files.items():
        node = children
        *dirs, name = path.split("/")
        for directory in dirs:
            node = node.setdefault(directory + "/", {})
        node[name] = (mode, sha)

    def write(node: dict) -> str:
        rows = []
        for key, value in node.items():
            if key.endswith("/"):
                rows.append((key, b"40000 " + key[:-1].encode() + b"\0" + bytes.fromhex(write(value))))
            else:
                rows.append((key, value[0].encode() + b" " + key.encode() + b"\0" + bytes.fromhex(value[1])))
        body = b"".join(row for _, row in sorted(rows))  # git orders a directory as "name/"
        return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()

    return write(children)


def verify(tar: Path) -> str:
    files = {}
    with tarfile.open(tar) as archive:
        for member in archive:
            if not member.isfile() or member.name.startswith("/") or ".." in member.name.split("/"):
                raise SystemExit(f"unexpected member {member.name!r}")
            data = archive.extractfile(member).read()
            mode = "100755" if member.mode & 0o111 else "100644"
            files[member.name] = (mode, hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest())
    tree = _tree_hash(files)
    if tree != TREE:
        raise SystemExit(f"tree {tree} != expected {TREE}: not hermes-agent {COMMIT}")
    digest = hashlib.sha256(tar.read_bytes()).hexdigest()
    print(f"VERIFIED hermes-agent {COMMIT} tree {TREE}: {len(files)} files; sha256 {digest}")
    return digest


def fetch(out: Path, timeout: float) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git(repo, "init", "-q")
        subprocess.run(["timeout", str(int(timeout)), "git", "-C", str(repo), "fetch", "-q", "--depth", "1", URL,
                        COMMIT], check=True)
        return export(repo, out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--repo", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--timeout", type=float, default=1800)
    v = sub.add_parser("verify")
    v.add_argument("tar", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export":
        export(args.repo, args.out)
    elif args.command == "fetch":
        fetch(args.out, args.timeout)
    else:
        verify(args.tar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
