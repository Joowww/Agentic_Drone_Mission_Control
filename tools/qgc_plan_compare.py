"""Offline semantic comparison of a .plan we exported with the copy QGroundControl saved after importing it.

It only compares two files: it never opens QGroundControl, connects to a vehicle or rewrites either file. Every
difference falls into one category:

- PRESENTATION: same parsed value, different text (whitespace, key order, ``5`` vs ``5.0``);
- QGC_METADATA: fields QGC writes for itself whose change does not alter a MAVLink item (listed below);
- SEMANTIC_CHANGE: command, frame, parameter, coordinate, altitude, header or home changed;
- ADDED / REMOVED: mission items or plan elements present on one side only;
- UNDETERMINED: equivalence cannot be decided here (unknown fields, non-standard JSON constants, type changes,
  QGC altitude fields that disagree with the item, float drift that maps to the same degE7 integer, ...).

null, NaN and 0 are never equivalent by default. The rules come from the sources consulted on 27/10/2026:
QGroundControl master 98ee79c1 (``MissionItem::load`` accepts only double or null in params 1-4 and reads null
as NaN through ``JsonParsing::possibleNaNJsonValue``; ``SimpleMissionItem::save`` writes Altitude/AltitudeMode/
AMSLAltAboveTerrain only for items that specify an altitude and writes doJumpId from the sequence number;
``AltitudeFrame`` 1 = MAV_FRAME_GLOBAL_RELATIVE_ALT) and ArduPilot 755258db (``AP_Mission::sanity_check_params``:
NaN allowed only in param4 of NAV_WAYPOINT, NAV_LAND and NAV_TAKEOFF). A JSON ``NaN``/``Infinity`` token is not
standard JSON, so its meaning for QGC is UNDETERMINED rather than "the same as null".

The result is a comparison, never a compatibility verdict.

    python -m tools.qgc_plan_compare ORIGINAL.plan SAVED.plan --out NEW_DIR
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

SCHEMA = "tfg.qgc-plan-comparison/1"
CATEGORIES = ("PRESENTATION", "QGC_METADATA", "SEMANTIC_CHANGE", "ADDED", "REMOVED", "UNDETERMINED")
COMMAND_NAMES = {16: "NAV_WAYPOINT", 20: "NAV_RETURN_TO_LAUNCH", 21: "NAV_LAND", 22: "NAV_TAKEOFF",
                 177: "DO_JUMP", 178: "DO_CHANGE_SPEED"}
DO_JUMP = 177
# Param index (0-based) -> meaning, for the commands our exporter writes; others get generic names.
PARAM_NAMES = {
    16: ("hold_s", "acceptance_radius", "pass_radius", "yaw", "latitude", "longitude", "altitude"),
    21: ("abort_altitude", "precision_land", "empty", "yaw", "latitude", "longitude", "altitude"),
    22: ("pitch", "empty", "empty", "yaw", "latitude", "longitude", "altitude"),
    178: ("speed_type", "speed_mps", "throttle", "empty", "empty", "empty", "empty"),
}
NAN_CAPABLE = {16: {3}, 21: {3}, 22: {3}}  # ArduPilot 755258db sanity_check_params
KNOWN_KEYS = {
    "plan": {"fileType", "version", "groundStation", "mission", "geoFence", "rallyPoints"},
    "mission": {"cruiseSpeed", "firmwareType", "globalPlanAltitudeMode", "hoverSpeed", "items",
                "plannedHomePosition", "vehicleType", "version"},
    "item": {"AMSLAltAboveTerrain", "Altitude", "AltitudeMode", "autoContinue", "command", "doJumpId", "frame",
             "params", "type"},
}
# Written by QGC for its own planning/display; a change here does not alter the uploaded MAVLink item.
QGC_METADATA_KEYS = {"plan": {"groundStation", "version"}, "mission": {"cruiseSpeed", "hoverSpeed", "version"},
                     "item": {"AMSLAltAboveTerrain"}}


class _Constant:
    """A non-standard JSON constant (NaN, Infinity, -Infinity) kept distinct from null and from numbers."""

    def __init__(self, token: str):
        self.token = token

    def __eq__(self, other):
        return isinstance(other, _Constant) and other.token == self.token

    def __repr__(self):
        return self.token


class _Duplicate(ValueError):
    pass


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    duplicated = sorted({k for k in keys if keys.count(k) > 1})
    if duplicated:
        raise _Duplicate(f"duplicate keys {duplicated}")
    return dict(pairs)


def parse(data: bytes) -> tuple[dict | None, list[str], str | None]:
    """(plan, constants found, error). Never repairs: an error means the file is not interpreted."""
    constants: list[str] = []

    def constant(token):
        constants.append(token)
        return _Constant(token)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, constants, f"not UTF-8: {exc}"
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=constant)
    except _Duplicate as exc:
        return None, constants, f"ambiguous JSON: {exc}"
    except ValueError as exc:
        return None, constants, f"invalid JSON: {exc}"
    if not isinstance(value, dict) or not isinstance(value.get("mission"), dict) \
            or not isinstance(value["mission"].get("items"), list):
        return None, constants, "not a plan: missing object 'mission' with list 'items'"
    return value, constants, None


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _same(a, b) -> bool:
    """Equal value with the same JSON kind (5 == 5.0 counts; true != 1; null != 0)."""
    if _number(a) and _number(b):
        return a == b
    return type(a) is type(b) and a == b


def _kind(v) -> str:
    return ("null" if v is None else "NaN/Infinity token" if isinstance(v, _Constant) else "boolean"
            if isinstance(v, bool) else "number" if _number(v) else type(v).__name__)


def _orders(a, b, path="") -> int:
    """Objects whose key order differs (presentation only)."""
    count = 0
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b) and set(a) == set(b):
            count += 1
        for key in set(a) & set(b):
            count += _orders(a[key], b[key], f"{path}/{key}")
    elif isinstance(a, list) and isinstance(b, list):
        count += sum(_orders(x, y) for x, y in zip(a, b))
    return count


class _Diff:
    def __init__(self):
        self.rows = []

    def add(self, category, path, original, saved, detail):
        self.rows.append({"category": category, "path": path, "original": _plain(original), "saved": _plain(saved),
                          "detail": detail})


def _plain(v):
    if isinstance(v, _Constant):
        return f"<{v.token}>"
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _value(diff, path, a, b, *, field, category_if_changed="SEMANTIC_CHANGE", degE7=False):
    if _same(a, b):
        if not (type(a) is type(b)):
            diff.add("PRESENTATION", path, a, b, f"{field}: same number, different literal")
        return
    if isinstance(a, _Constant) or isinstance(b, _Constant):
        diff.add("UNDETERMINED", path, a, b, f"{field}: non-standard JSON constant; QGC's reading is not established")
        return
    if (a is None) != (b is None):
        diff.add(category_if_changed, path, a, b, f"{field}: null (read as NaN by QGC) vs "
                 f"{_kind(b if a is None else a)}; not equivalent")
        return
    if _number(a) and _number(b):
        if degE7 and round(a * 1e7) == round(b * 1e7):
            diff.add("UNDETERMINED", path, a, b, f"{field}: float differs but maps to the same degE7 integer")
        else:
            diff.add(category_if_changed, path, a, b, f"{field}: value changed (Δ={b - a:.10g})")
        return
    if _kind(a) != _kind(b):
        diff.add("UNDETERMINED", path, a, b, f"{field}: type changed {_kind(a)} -> {_kind(b)}")
        return
    diff.add(category_if_changed, path, a, b, f"{field}: changed")


def _unknown_keys(diff, path, a, b, scope):
    for key in sorted(set(b) - KNOWN_KEYS[scope]):
        if key in a and _same(a[key], b[key]):
            continue  # present unchanged on both sides (our exporter never writes unknown keys)
        diff.add("UNDETERMINED", f"{path}/{key}", a.get(key), b[key],
                 "field unknown to this comparator: not assumed harmless")
    for key in sorted(set(a) - KNOWN_KEYS[scope] - set(b)):
        diff.add("UNDETERMINED", f"{path}/{key}", a[key], None, "unknown field removed")


def _keys(diff, path, a, b, scope, handled):
    for key in sorted((set(a) | set(b)) & KNOWN_KEYS[scope] - handled):
        if key not in b:
            category = "QGC_METADATA" if key in QGC_METADATA_KEYS.get(scope, ()) else "REMOVED"
            diff.add(category, f"{path}/{key}", a[key], None, "field removed")
        elif key not in a:
            category = "QGC_METADATA" if key in QGC_METADATA_KEYS.get(scope, ()) else "ADDED"
            diff.add(category, f"{path}/{key}", None, b[key], "field added")
        else:
            category = "QGC_METADATA" if key in QGC_METADATA_KEYS.get(scope, ()) else "SEMANTIC_CHANGE"
            _value(diff, f"{path}/{key}", a[key], b[key], field=key, category_if_changed=category)


def _item(diff, path, a, b, renumbering_ok):
    if a.get("type") != "SimpleItem" or b.get("type") != "SimpleItem":
        if not _same(a.get("type"), b.get("type")):
            diff.add("SEMANTIC_CHANGE", f"{path}/type", a.get("type"), b.get("type"), "item type changed")
        if b.get("type") != "SimpleItem":
            diff.add("UNDETERMINED", path, None, b.get("type"), "non-SimpleItem not interpreted by this comparator")
        return
    _unknown_keys(diff, path, a, b, "item")
    command = a.get("command")
    _value(diff, f"{path}/command", command, b.get("command"),
           field=f"command {COMMAND_NAMES.get(command, command)} -> {COMMAND_NAMES.get(b.get('command'), b.get('command'))}")
    _value(diff, f"{path}/frame", a.get("frame"), b.get("frame"), field="frame")
    _value(diff, f"{path}/autoContinue", a.get("autoContinue"), b.get("autoContinue"), field="autoContinue")
    if not _same(a.get("doJumpId"), b.get("doJumpId")):
        diff.add("QGC_METADATA" if renumbering_ok else "UNDETERMINED", f"{path}/doJumpId", a.get("doJumpId"),
                 b.get("doJumpId"), "QGC writes doJumpId from the sequence number" + (
                     "; no DO_JUMP references in either file" if renumbering_ok else "; a DO_JUMP may refer to it"))
    pa, pb = a.get("params"), b.get("params")
    if not (isinstance(pa, list) and isinstance(pb, list) and len(pa) == 7 and len(pb) == 7):
        diff.add("UNDETERMINED", f"{path}/params", pa, pb, "params is not a list of 7 values")
    else:
        names = PARAM_NAMES.get(command, tuple(f"param{i + 1}" for i in range(7)))
        for i, (x, y) in enumerate(zip(pa, pb)):
            field = f"{COMMAND_NAMES.get(command, command)} param{i + 1} ({names[i]})"
            if (x is None) != (y is None) and i not in NAN_CAPABLE.get(command, set()):
                field += "; NaN is not accepted here by ArduPilot"
            _value(diff, f"{path}/params/{i}", x, y, field=field, degE7=i in (4, 5))
    # QGC altitude fields: present only for items that specify an altitude; they must agree with the item.
    for key in ("Altitude", "AltitudeMode"):
        if key in a and key not in b:
            diff.add("QGC_METADATA", f"{path}/{key}", a[key], None, f"{key} not written by QGC for this item")
        elif key in b and key not in a:
            diff.add("QGC_METADATA", f"{path}/{key}", None, b[key], f"{key} added by QGC")
        elif key in a and not _same(a[key], b[key]):
            diff.add("UNDETERMINED", f"{path}/{key}", a[key], b[key],
                     f"{key} changed: QGC uses it to plan the item's altitude frame/value")
    if "Altitude" in b and isinstance(pb, list) and len(pb) == 7 and _number(b["Altitude"]) \
            and b.get("frame") == 3 and _number(pb[6]) and b["Altitude"] != pb[6] and b.get("command") != 21:
        diff.add("UNDETERMINED", f"{path}/Altitude", None, b["Altitude"], "QGC Altitude disagrees with param7")
    _keys(diff, path, a, b, "item", {"type", "command", "frame", "autoContinue", "doJumpId", "params", "Altitude",
                                     "AltitudeMode"})


def compare_plans(original: bytes, saved: bytes) -> dict:
    result = {"schema": SCHEMA, "original_sha256": hashlib.sha256(original).hexdigest(),
              "saved_sha256": hashlib.sha256(saved).hexdigest(),
              "verdict_scope": "comparison of two files only; not a QGroundControl or vehicle compatibility verdict"}
    if original == saved:
        return {**result, "status": "IDENTICAL_BYTES", "differences": [], "counts": {c: 0 for c in CATEGORIES}}
    a, a_constants, a_error = parse(original)
    b, b_constants, b_error = parse(saved)
    if a_error or b_error:
        return {**result, "status": "UNREADABLE_ORIGINAL" if a_error else "UNREADABLE_SAVED",
                "error": a_error or b_error, "differences": [], "counts": {c: 0 for c in CATEGORIES},
                "note": "not normalized or repaired; see text.diff and the copies"}
    diff = _Diff()
    orders = _orders(a, b)
    if orders:
        diff.add("PRESENTATION", "/", None, None, f"key order differs in {orders} object(s)")
    if [x for x in b_constants if x not in a_constants]:
        diff.add("UNDETERMINED", "/", None, sorted(set(b_constants)), "saved file uses non-standard JSON constants")
    _unknown_keys(diff, "", a, b, "plan")
    _keys(diff, "", a, b, "plan", {"mission", "geoFence", "rallyPoints"})
    ma, mb = a["mission"], b["mission"]
    _unknown_keys(diff, "/mission", ma, mb, "mission")
    _keys(diff, "/mission", ma, mb, "mission", {"items", "plannedHomePosition"})
    ha, hb = ma.get("plannedHomePosition"), mb.get("plannedHomePosition")
    if isinstance(ha, list) and isinstance(hb, list) and len(ha) == len(hb) == 3:
        for i, field in enumerate(("latitude", "longitude", "AMSL altitude")):
            _value(diff, f"/mission/plannedHomePosition/{i}", ha[i], hb[i], field=f"planned home {field}",
                   degE7=i < 2)
    elif not _same(ha, hb):
        diff.add("UNDETERMINED", "/mission/plannedHomePosition", ha, hb, "planned home not a 3-value list")
    for section, content in (("geoFence", ("circles", "polygons")), ("rallyPoints", ("points",))):
        sa, sb = a.get(section), b.get(section)
        if not (isinstance(sa, dict) and isinstance(sb, dict)):
            if not _same(sa, sb):
                diff.add("UNDETERMINED", f"/{section}", sa, sb, f"{section} missing or not an object")
            continue
        if not _same(sa.get("version"), sb.get("version")):
            diff.add("QGC_METADATA", f"/{section}/version", sa.get("version"), sb.get("version"), "format version")
        for key in content:
            if _plain(sa.get(key)) != _plain(sb.get(key)):
                category = "ADDED" if not sa.get(key) else "REMOVED" if not sb.get(key) else "SEMANTIC_CHANGE"
                diff.add(category, f"/{section}/{key}", sa.get(key), sb.get(key), f"{section} {key} changed")
        for key in sorted((set(sa) | set(sb)) - {"version", *content}):
            if not _same(sa.get(key), sb.get(key)):
                diff.add("UNDETERMINED", f"/{section}/{key}", sa.get(key), sb.get(key), "unknown field")
    ia, ib = ma["items"], mb["items"]
    renumbering_ok = not any(isinstance(i, dict) and i.get("command") == DO_JUMP for i in [*ia, *ib])
    key = lambda item: item.get("command") if isinstance(item, dict) else repr(item)  # noqa: E731
    matcher = difflib.SequenceMatcher(a=[key(i) for i in ia], b=[key(i) for i in ib], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if isinstance(ia[i], dict) and isinstance(ib[j], dict):
                    _item(diff, f"/mission/items/{i}", ia[i], ib[j], renumbering_ok)
                else:
                    diff.add("UNDETERMINED", f"/mission/items/{i}", ia[i], ib[j], "item is not an object")
            continue
        for i in range(i1, i2):
            diff.add("REMOVED", f"/mission/items/{i}", ia[i], None,
                     f"item {COMMAND_NAMES.get(key(ia[i]), key(ia[i]))} absent from the saved file")
        for j in range(j1, j2):
            diff.add("ADDED", f"/mission/items/(saved {j})", None, ib[j],
                     f"item {COMMAND_NAMES.get(key(ib[j]), key(ib[j]))} only in the saved file")
    counts = {c: sum(1 for r in diff.rows if r["category"] == c) for c in CATEGORIES}
    status = ("SEMANTIC_DIFFERENCES" if counts["SEMANTIC_CHANGE"] or counts["ADDED"] or counts["REMOVED"] else
              "UNDETERMINED" if counts["UNDETERMINED"] else "NO_SEMANTIC_DIFFERENCES")
    return {**result, "status": status, "differences": diff.rows, "counts": counts}


def text_diff(original: bytes, saved: bytes) -> str:
    decode = lambda data: data.decode("utf-8", errors="replace").splitlines(keepends=True)  # noqa: E731
    return "".join(difflib.unified_diff(decode(original), decode(saved), "original.plan", "saved.plan"))


def render(result: dict) -> str:
    lines = [f"# Comparación `.plan`: {result['status']}", "",
             f"- Original sha256 `{result['original_sha256']}`; guardado sha256 `{result['saved_sha256']}`.",
             f"- Alcance: {result['verdict_scope']}.", ""]
    if result.get("error"):
        lines += [f"**No interpretado:** {result['error']} (sin normalizar ni reparar).", ""]
    lines += ["| Categoría | Número |", "| --- | --- |"] + [f"| {c} | {n} |" for c, n in result["counts"].items()]
    if result["differences"]:
        lines += ["", "| Categoría | Ruta | Original | Guardado | Detalle |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {r['category']} | `{r['path']}` | `{json.dumps(r['original'])}` | `{json.dumps(r['saved'])}` | "
                  f"{r['detail']} |" for r in result["differences"]]
    return "\n".join(lines) + "\n"


def write_comparison(original_path: Path, saved_path: Path, out: Path) -> dict:
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} exists; comparisons are never overwritten")
    original, saved = Path(original_path).read_bytes(), Path(saved_path).read_bytes()
    result = compare_plans(original, saved)
    out.mkdir(parents=True)
    shutil.copyfile(original_path, out / "original.plan")
    shutil.copyfile(saved_path, out / "saved.plan")
    (out / "text.diff").write_text(text_diff(original, saved), encoding="utf-8")
    (out / "comparison.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "comparison.md").write_text(render(result), encoding="utf-8")
    names = sorted(p.name for p in out.iterdir())
    (out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n"
                                            for n in names), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("original", type=Path)
    parser.add_argument("saved", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="NEW directory for copies, diff and comparison")
    args = parser.parse_args(argv)
    try:
        result = write_comparison(args.original, args.saved, args.out)
    except (FileExistsError, FileNotFoundError) as exc:
        print(f"[REFUSED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, indent=2))
    return {"IDENTICAL_BYTES": 0, "NO_SEMANTIC_DIFFERENCES": 0, "UNDETERMINED": 1,
            "SEMANTIC_DIFFERENCES": 1}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
