#!/usr/bin/env python3
"""Export reviewed targets with exact installed resource names and pinned artwork hashes."""

import json
from pathlib import Path
from collections import Counter
import re
import hashlib
import zipfile

from cleanicons.arsc import alias_reader
from cleanicons.bitmap_table import bitmap_resource_table
from cleanicons.artwork import foreground_scale
from cleanicons.resources import dump, file_values, resolved_values, resource_table

ROOT = Path(__file__).resolve().parent


def main():
    inventory = json.loads((ROOT / ".cache/inventory.json").read_text())
    tree = json.loads((ROOT / ".cache/upstream-tree.json").read_text())
    index = {n["path"]: n["sha"] for n in tree["tree"]}
    selection = json.loads((ROOT / "selection.json").read_text())
    overrides = json.loads((ROOT / "icon-overrides.json").read_text())
    apps = {a["package"]: a for a in inventory["apps"]}
    result = {"upstream": inventory["upstream"], "device": inventory["device"], "apps": []}
    for package, reason in selection.items():
        app = apps[package]
        folder = ROOT / ".cache/device" / package
        table = {}
        apks = [p for p in sorted(folder.glob("*.apk")) if p.name != "metadata.apk"]
        base_ids = set()
        override = overrides.get(package, {})
        for apk in apks:
            if override.get("resource_reader") == "binary-bitmaps":
                with zipfile.ZipFile(apk) as archive:
                    apk_table = bitmap_resource_table(archive.read("resources.arsc"), [r["id"] for r in app["roots"]])
            else:
                apk_table = resource_table(dump(ROOT / ".cache/toolchain/aapt2", apk, "resources"))
            if apk.name == "base.apk":
                base_ids = set(apk_table)
            for rid, entry in apk_table.items():
                for value in entry["values"]:
                    value["apk"] = apk.name
                if rid in table:
                    table[rid]["values"].extend(entry["values"])
                else:
                    table[rid] = entry
        names = Counter(r["name"] for r in table.values())
        selected_roots = app["roots"]
        if requested := override.get("roots"):
            selected_roots = [r for r in app["roots"] if r["name"] in requested]
            if {r["name"] for r in selected_roots} != set(requested):
                raise ValueError("Requested icon roots not found: " + package)
        original_preview = None
        if any(not root["variants"] for root in selected_roots):
            if len(selected_roots) != 1 or app.get("primary_icon_id") != selected_roots[0]["id"]:
                raise ValueError("Original launcher artwork needs review: " + package)
            rid = app["primary_icon_id"]
            values = list(resolved_values(table, rid, reference_lookup=alias_reader(apks)))
            candidates = [(v, config, path) for v in values for config, path in file_values({"values": [v]}) if path.lower().endswith(".png")]
            if not candidates:
                raise ValueError("No verified PNG original for install-time extraction: " + package)
            density = {"ldpi": 120, "mdpi": 160, "tvdpi": 213, "hdpi": 240, "xhdpi": 320, "xxhdpi": 480, "xxxhdpi": 640}
            def rank(candidate):
                config = candidate[1]
                qualifiers = config.split("-")
                return "night" not in qualifiers, max((density.get(q, 0) for q in qualifiers), default=0)
            value, config, path = max(candidates, key=rank)
            if not re.fullmatch(r"[A-Za-z0-9_./-]+\.png", path) or ".." in path.split("/"):
                raise ValueError("Unsafe original preview entry: " + path)
            original_preview = {"apk": value["apk"], "entry": path, "config": config, "source_resource": rid,
                                "resolved_resource": alias_reader(apks)(rid)}
        roots = []
        bootstrap_artwork = None
        if bootstrap := override.get("bootstrap_resource"):
            if not override.get("numeric_target") or override.get("roots"):
                raise ValueError("Preserved bootstrap requires a numeric target without launcher seeds: " + package)
            resource = table[bootstrap["id"]]
            values = resource["values"]
            files = list(file_values(resource))
            if (resource["name"] != bootstrap["name"] or len(values) != 1 or
                    values[0]["apk"] != "base.apk" or len(files) != 1):
                raise ValueError("Bootstrap must be one direct base bitmap: " + package)
            config, path = files[0]
            if not re.fullmatch(r"res/[A-Za-z0-9_/-]+\.(png|webp)", path):
                raise ValueError("Unsupported bootstrap image: " + path)
            file = folder / "files" / path
            content = file.read_bytes()
            bootstrap_artwork = {"file": str(file.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest(),
                                 "entry": path, "config": config, "source_resource": bootstrap["id"],
                                 "source_name": bootstrap["name"], "apk": "base.apk"}
            selected_roots = [{"id": bootstrap["id"], "name": bootstrap["name"]}]
        for r in selected_roots:
            if r["id"] not in base_ids:
                raise ValueError("RRO target is absent from base.apk: " + package + ':' + r["name"])
            if names[r["name"]] != 1:
                raise ValueError("Resource name is ambiguous: " + package + ':' + r["name"])
            roots.append({"id": r["id"], "name": r["name"], "configs": sorted({v["config"] for v in table[r["id"]]["values"]})})
        reviewed = {k: app[k] for k in ["package", "label", "version_code", "version_name", "has_overlayable"]} | {
            "roots": roots, "reason": reason, "assets": {str(i): index[f"icons/{package}/{i}.png"] for i in (0, 1)}}
        if numeric := override.get("numeric_target"):
            if len(roots) != 1 or not re.fullmatch(r"@0x7f[0-9a-f]{6}", numeric["id"]):
                raise ValueError("Numeric mapping requires one reviewed seed resource: " + package)
            resource = table[numeric["id"]]
            if resource["name"] != numeric["name"] or {v["apk"] for v in resource["values"]} != {numeric["apk"]}:
                raise ValueError("Numeric target differs from the installed resource table: " + package)
            reviewed["seed_roots"] = roots
            reviewed["roots"] = [{"id": numeric["id"], "name": numeric["name"],
                                  "configs": sorted({v["config"] for v in resource["values"]})}]
            reviewed["mapping_mode"] = "numeric-idmap-v11"
            reviewed["numeric_target_apk"] = numeric["apk"]
            with zipfile.ZipFile(folder / "base.apk") as base:
                reviewed["numeric_target_crc"] = f'{base.getinfo("AndroidManifest.xml").CRC ^ base.getinfo("resources.arsc").CRC:08x}'
        if original_preview:
            reviewed["original_preview"] = original_preview
        if bootstrap_artwork:
            reviewed["bootstrap_artwork"] = bootstrap_artwork
        if source_name := override.get("artwork_resource"):
            source_ids = [rid for rid, resource in table.items() if resource["name"] == source_name]
            if len(source_ids) != 1:
                raise ValueError("APK bitmap source is ambiguous: " + package)
            source_id = source_ids[0]
            candidates = [(v, config, path) for v in resolved_values(table, source_id, reference_lookup=alias_reader(apks))
                          for config, path in file_values({"values": [v]}) if path.lower().endswith(".png")]
            if len(candidates) != 1:
                raise ValueError("APK bitmap source needs explicit configuration review: " + package)
            value, config, path = candidates[0]
            file = folder / "files" / path
            content = file.read_bytes()
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("APK source is not a PNG: " + package)
            reviewed["artwork"] = {"kind": "apk-bitmap", "file": str(file.relative_to(ROOT)),
                                   "sha256": hashlib.sha256(content).hexdigest(), "source_resource": source_id,
                                   "source_name": source_name, "apk": value["apk"], "entry": path, "config": config}
            reviewed["assets"] = {}
            if background := override.get("adaptive_background"):
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
                    raise ValueError("Invalid adaptive background: " + package)
                reviewed["artwork"]["adaptive_background"] = background
        if scope := override.get("scope"):
            reviewed["scope"] = scope
        if "foreground_scale" in override:
            scale = foreground_scale(dict(reviewed, foreground_scale=override["foreground_scale"]))
            if scale != 1:
                reviewed["foreground_scale"] = scale
        result["apps"].append(reviewed)
    (ROOT / "targets.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Selected {len(result['apps'])} apps, {sum(len(a['roots']) for a in result['apps'])} launcher icon resources")


if __name__ == "__main__":
    main()
