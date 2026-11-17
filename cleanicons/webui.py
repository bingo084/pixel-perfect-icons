"""Bundle the offline KSU interface and reviewed icon comparisons."""

import hashlib
import json
from pathlib import Path
import shutil

from preview import FONT, circle, run
from cleanicons.artwork import bitmap_background, bitmap_source

SDK_SHA256 = "35d1da95e89db19398a1e848a98ec20ad72b4d85964033341d57dc2b7d39da36"


def build_webui(root: Path, destination: Path, spec: dict, version: str):
    sdk = root / "webui/vendor/kernelsu.js"
    if hashlib.sha256(sdk.read_bytes()).hexdigest() != SDK_SHA256:
        raise ValueError("Vendored KernelSU SDK changed; review its pinned version and checksum")
    inventory = json.loads((root / ".cache/inventory.json").read_text())
    scanned = {a["package"]: a for a in inventory["apps"]}
    reasons = json.loads((root / "selection.json").read_text())
    shutil.copytree(root / "webui", destination)
    assets = destination / "assets"
    assets.mkdir()
    apps = []
    for target in spec["apps"]:
        package = target["package"]
        original = scanned.get(package)
        if not original or original["version_code"] != target["version_code"]:
            raise ValueError("Icon comparison needs a matching APK scan: " + package)
        selected_ids = {r["id"] for r in target["roots"] + target.get("seed_roots", [])}
        bitmaps = [(r, v) for r in original["roots"] if r["id"] in selected_ids
                   for v in r["variants"] if not v["file"].endswith(".xml")]
        before = None
        if bitmaps:
            primary = original.get("primary_icon_id")
            _, variant = max(bitmaps, key=lambda rv: (rv[0]["id"] == primary, len(rv[1]["config"])))
            name = package + ".before.png"
            circle(root / variant["file"], assets / name)
            before = "assets/" + name
        elif target.get("original_preview"):
            name = package + ".before.png"
            # The installer replaces this explicit placeholder with the exact APK PNG.
            run("magick", "-size", "160x160", "xc:transparent", "-fill", "#eef1f7",
                "-draw", "circle 80,80 80,0", "-font", FONT, "-pointsize", "16",
                "-fill", "#788397", "-gravity", "center", "-annotate", "+0+0", "待提取", assets / name)
            before = "assets/" + name
        after = package + ".after.png"
        if bitmap := bitmap_source(root, target):
            source = "应用原图"
            circle(bitmap, assets / after, background=bitmap_background(target))
        else:
            source = "补全计划"
            upstream = root / ".cache/upstream" / package
            merged = assets / (package + ".layers.png")
            run("magick", upstream / "0.png", "-resize", "432x432!", "(", upstream / "1.png",
                "-resize", "432x432!", ")", "-compose", "over", "-composite", merged)
            circle(merged, assets / after, adaptive=True)
            merged.unlink()
        apps.append({"package": package, "name": target["label"], "reason": reasons[package],
                     "before": before, "after": "assets/" + after, "source": source})
    catalog = {"version": version, "apps": apps}
    (destination / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    return catalog
