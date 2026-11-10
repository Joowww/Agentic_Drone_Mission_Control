"""Check a `docker save` archive without a daemon: every blob's sha256 equals its name, and every manifest,
config and layer reachable from index.json is present. Prints JSON."""
import hashlib
import json
import sys
import tarfile


def check(path):
    out = {"archive": path.rsplit("/", 1)[-1], "blobs": 0, "blob_hash_mismatches": [], "missing": [],
           "index_manifests": [], "image_indexes": [], "images": []}
    blobs = {}
    with tarfile.open(path) as tar:
        for member in tar:
            if not member.isfile():
                continue
            data = tar.extractfile(member).read()
            if member.name.startswith("blobs/sha256/"):
                out["blobs"] += 1
                digest = member.name.rsplit("/", 1)[1]
                if hashlib.sha256(data).hexdigest() != digest:
                    out["blob_hash_mismatches"].append(digest)
                blobs[digest] = data
            elif member.name in ("index.json", "manifest.json", "oci-layout"):
                blobs[member.name] = data
    index = json.loads(blobs["index.json"])
    legacy = json.loads(blobs.get("manifest.json", b"[]"))

    def walk(descriptor, tags):
        digest = descriptor["digest"].split(":", 1)[1]
        if digest not in blobs:
            out["missing"].append(descriptor["digest"])
            return
        body = json.loads(blobs[digest])
        if "manifests" in body:
            out["image_indexes"].append(descriptor["digest"])
            for child in body["manifests"]:
                walk(child, tags)
            return
        layers = body.get("layers", [])
        for item in [body["config"], *layers]:
            if item["digest"].split(":", 1)[1] not in blobs:
                out["missing"].append(item["digest"])
        out["images"].append({"manifest": descriptor["digest"], "config": body["config"]["digest"],
                              "artifact_type": body.get("artifactType"),
                              "layers": len(layers), "layer_bytes": sum(l["size"] for l in layers), "tags": tags})

    for descriptor in index["manifests"]:
        tags = [descriptor.get("annotations", {}).get("io.containerd.image.name")]
        out["index_manifests"].append({"digest": descriptor["digest"], "name": tags[0]})
        walk(descriptor, tags)
    out["legacy_manifest_repotags"] = [t for m in legacy for t in m.get("RepoTags", [])]
    out["ok"] = not out["blob_hash_mismatches"] and not out["missing"] and bool(out["images"])
    return out


if __name__ == "__main__":
    results = [check(p) for p in sys.argv[1:]]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["ok"] for r in results) else 1)
