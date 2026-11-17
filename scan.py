#!/usr/bin/env python3
"""Read-only ADB inventory and icon-resource extraction. Does not use su."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

from cleanicons.resources import dump, file_values, launcher_icons, resolved_values, resource_table, xml_tree
from cleanicons.arsc import alias_reader

ROOT = Path(__file__).resolve().parent
REPO = "pzcn/Perfect-Icons-Completion-Project"


def shell(command, binary=False):
    result = subprocess.run(["adb", "exec-out", command], capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1200:])
    return result.stdout if binary else result.stdout.decode().strip()


def read_entry(apk, entry):
    return shell("unzip -p " + shlex.quote(apk) + " " + shlex.quote(entry), binary=True)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "pixel-clean-icons/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


def inspect(package, aapt2, cache):
    folder = cache / "device" / package
    folder.mkdir(parents=True, exist_ok=True)
    paths = [s.removeprefix("package:") for s in shell("pm path " + shlex.quote(package)).splitlines()]
    selected = [s for s in paths if s.endswith("/base.apk") or re.search(r"/split_config\.[a-z]*dpi\.apk$", s)]
    table = {}
    base_tree = None
    for remote in selected:
        local = folder / Path(remote).name
        stamp = local.with_suffix(".source")
        if not local.exists() or not stamp.exists() or stamp.read_text() != remote:
            with zipfile.ZipFile(local, "w") as archive:
                for name in ("AndroidManifest.xml", "resources.arsc"):
                    try:
                        archive.writestr(name, read_entry(remote, name))
                    except RuntimeError:
                        if name == "AndroidManifest.xml":
                            raise
            stamp.write_text(remote)
        parsed = resource_table(dump(aapt2, local, "resources"))
        for rid, entry in parsed.items():
            for value in entry["values"]:
                value["apk"] = remote
            if rid in table:
                table[rid]["values"].extend(entry["values"])
            else:
                table[rid] = entry
        if remote.endswith("/base.apk"):
            base_tree = xml_tree(dump(aapt2, local, "xmltree", "AndroidManifest.xml"))
            badging = dump(aapt2, local, "badging")
            overlayable = dump(aapt2, local, "overlayable")
    if base_tree is None:
        raise RuntimeError("base.apk missing")
    refs, components = launcher_icons(base_tree)
    reference_lookup = alias_reader([folder / Path(p).name for p in selected])
    manifest = next(n for n in base_tree.walk() if n.tag == "manifest")
    label = re.search(r"^application-label:'(.*)'$", badging, re.M)
    roots = []
    for rid in refs:
        if rid not in table:
            raise RuntimeError("Launcher icon resource missing from installed APKs: " + rid)
        entry = table[rid]
        variants = []
        for value in resolved_values(table, rid, reference_lookup=reference_lookup):
            files = list(file_values({"values": [value]}))
            if not files:
                continue
            config, filename = files[0]
            dest = folder / "files" / filename
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(read_entry(value["apk"], filename))
            variant = {"config": config, "file": str(dest.relative_to(ROOT)), "path": filename}
            if filename.endswith(".xml"):
                # Read the actual binary XML, including adaptive foreground/background/monochrome refs.
                with zipfile.ZipFile(folder / Path(value["apk"]).name, "a") as apk:
                    if filename not in apk.namelist():
                        apk.writestr(filename, dest.read_bytes())
                xml = dump(aapt2, folder / Path(value["apk"]).name, "xmltree", filename)
                variant["xml"] = xml
                for dep in sorted(set(re.findall(r"@0x[0-9a-fA-F]+", xml))):
                    if dep.lower() not in table:
                        continue
                    dependency = table[dep.lower()]
                    for dv in dependency["values"]:
                        for dc, dp in file_values({"values": [dv]}):
                            target = folder / "files" / dp
                            if not target.exists():
                                target.parent.mkdir(parents=True, exist_ok=True)
                                target.write_bytes(read_entry(dv["apk"], dp))
                variant["dependencies"] = {d: table[d.lower()] for d in sorted(set(re.findall(r"@0x[0-9a-fA-F]+", xml))) if d.lower() in table}
            variants.append(variant)
        roots.append({"id": rid, "name": entry["name"], "configs": sorted({v['config'] for v in entry['values']}), "variants": variants})
    return {"package": package, "label": label[1] if label else package,
            "version_code": manifest.attrs.get("versionCode"), "version_name": manifest.attrs.get("versionName"),
            "components": components, "roots": roots, "has_overlayable": bool(overlayable.strip()),
            "primary_icon_id": next(n for n in base_tree.walk() if n.tag == "application").attrs.get("icon", "").lower(),
            "metadata_sha256": hashlib.sha256((folder / "base.apk").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aapt2", type=Path, required=True)
    parser.add_argument("--upstream-commit", required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--serial", help="ADB transport serial (or use ANDROID_SERIAL)")
    parser.add_argument("--package", help="Recheck one matched package, preserving the other scan records")
    args = parser.parse_args()
    if args.serial:
        os.environ["ANDROID_SERIAL"] = args.serial
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    packages = sorted(s.removeprefix("package:") for s in shell("pm list packages -3").splitlines())
    index = cache / "upstream-tree.json"
    tree = json.loads(index.read_text()) if index.exists() else {}
    if tree.get("commit") != args.upstream_commit:
        tree = json.loads(fetch(f"https://api.github.com/repos/{REPO}/git/trees/{args.upstream_commit}?recursive=1"))
        tree["commit"] = args.upstream_commit
    if tree.get("truncated"):
        raise SystemExit("Upstream tree incomplete")
    (cache / "upstream-tree.json").write_text(json.dumps(tree))
    by_path = {n["path"]: n for n in tree["tree"]}
    matched = [p for p in packages if all(f"icons/{p}/{i}.png" in by_path for i in (0, 1))]
    inventory = {"device": {key: shell("getprop " + key) for key in ["ro.product.device", "ro.build.version.sdk", "ro.build.fingerprint"]},
                 "upstream": {"repository": REPO, "commit": args.upstream_commit},
                 "installed_count": len(packages), "unmatched": sorted(set(packages) - set(matched)), "apps": [], "errors": []}
    if args.package:
        if args.package not in matched:
            raise SystemExit("Requested package has no installed/upstream match")
        previous = json.loads((cache / "inventory.json").read_text())
        if previous["device"] != inventory["device"] or previous["upstream"] != inventory["upstream"]:
            raise SystemExit("Device or upstream changed; do a full scan")
        inventory["apps"] = [a for a in previous["apps"] if a["package"] != args.package]
        inventory["errors"] = [a for a in previous["errors"] if a["package"] != args.package]
        matched = [args.package]
    print(f"Installed: {len(packages)}; upstream layer pairs: {len(matched)}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(inspect, p, args.aapt2, cache): p for p in matched}
        for future in as_completed(jobs):
            package = jobs[future]
            try:
                app = future.result()
                folder = cache / "upstream" / package
                folder.mkdir(parents=True, exist_ok=True)
                for i in (0, 1):
                    path = f"icons/{package}/{i}.png"
                    dest = folder / f"{i}.png"
                    data = dest.read_bytes() if dest.exists() else fetch(f"https://raw.githubusercontent.com/{REPO}/{args.upstream_commit}/{path}")
                    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                    if digest != by_path[path]["sha"]:
                        raise RuntimeError("Upstream asset hash mismatch: " + path)
                    dest.write_bytes(data)
                inventory["apps"].append(app)
                print(f"OK {package}: {len(app['roots'])} launcher icon resources", flush=True)
            except Exception as exc:
                inventory["errors"].append({"package": package, "error": str(exc)})
                print(f"ERROR {package}: {exc}", flush=True)
            inventory["apps"].sort(key=lambda x: x["package"])
            (cache / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2))
    print(f"Saved {len(inventory['apps'])} apps, {len(inventory['errors'])} errors to .cache/inventory.json")


if __name__ == "__main__":
    main()
