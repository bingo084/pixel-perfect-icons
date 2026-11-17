#!/usr/bin/env python3
"""Build and verify a local KernelSU module. Never installs anything on a phone."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from cleanicons.resources import dump, resource_table, xml_tree
from cleanicons.webui import build_webui
from cleanicons.artwork import bitmap_background, bitmap_source

ROOT = Path(__file__).resolve().parent
ANDROID = "http://schemas.android.com/apk/res/android"
VERSION = "0.3.8"
VERSION_CODE = 308
# Keep the installed identity so renamed releases update the existing module.
MODULE_ID = "pixel-clean-icons"
ARCHIVE_NAME = "pixel-perfect-icons"
DISPLAY_NAME = "Pixel Perfect Icons"
ET.register_namespace("android", ANDROID)


def run(*args, env=None):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed:\n{result.stderr[-3000:]}")
    return result.stdout


def write_xml(path, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def signing_environment():
    folder = ROOT / "keys"
    folder.mkdir(mode=0o700, exist_ok=True)
    password_file = folder / "password"
    if not password_file.exists():
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(40))
    env = dict(os.environ, CLEAN_ICONS_STORE_PASS=password_file.read_text())
    key = folder / "overlay.p12"
    if not key.exists():
        run("keytool", "-genkeypair", "-keystore", key, "-storetype", "PKCS12", "-storepass:env",
            "CLEAN_ICONS_STORE_PASS", "-alias", "overlay", "-keyalg", "RSA", "-keysize", "3072",
            "-validity", "10000", "-dname", "CN=Pixel Clean Icons Local Build", env=env)
        key.chmod(0o600)
    return key, env


def validate_target(app):
    package = app["package"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package):
        raise ValueError("Invalid package: " + package)
    if not app["roots"]:
        raise ValueError("No launcher icon resources: " + package)
    names = [r["name"] for r in app["roots"]]
    if len(set(names)) != len(names):
        raise ValueError("Ambiguous obfuscated resource names: " + package)
    for name in names:
        if not re.fullmatch(r"(?:drawable|mipmap)/[A-Za-z0-9_.$]+", name) or name.endswith("/_"):
            raise ValueError("Unsafe target resource: " + name)
    if app.get("has_overlayable"):
        raise ValueError("Explicit overlayable policy requires separate review: " + package)
    if not str(app["version_code"]).isdigit():
        raise ValueError("Expected a numeric version code: " + package)


def build_overlay(app, target, tools, framework, key, env):
    validate_target(app)
    mapping_roots = app.get("seed_roots", app["roots"])
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    overlay_id = "local.pixelcleanicons." + app["package"].lower().replace(".", "_")
    manifest = ET.Element("manifest", {"package": overlay_id, f"{{{ANDROID}}}versionCode": str(VERSION_CODE),
                                           f"{{{ANDROID}}}versionName": VERSION})
    # A high APK minSdk collapses v26 configurations to their unversioned forms.
    # Those would lose against the target's original anydpi-v26 icon at runtime.
    # Installation remains restricted to Android 17 by customize.sh.
    ET.SubElement(manifest, "uses-sdk", {f"{{{ANDROID}}}minSdkVersion": "24", f"{{{ANDROID}}}targetSdkVersion": "37"})
    ET.SubElement(manifest, "application", {f"{{{ANDROID}}}hasCode": "false", f"{{{ANDROID}}}label": DISPLAY_NAME})
    ET.SubElement(manifest, "overlay", {f"{{{ANDROID}}}targetPackage": app["package"],
                                      f"{{{ANDROID}}}isStatic": "true", f"{{{ANDROID}}}priority": "9999",
                                      f"{{{ANDROID}}}resourcesMap": "@xml/overlays"})
    write_xml(target / "AndroidManifest.xml", manifest)
    assets = ROOT / ".cache/upstream" / app["package"]
    configs = {""}
    for entry in app["roots"]:
        configs.update(entry.get("configs", []))
    for config in configs:
        if config and not re.fullmatch(r"[A-Za-z0-9+_-]+", config):
            raise ValueError("Unexpected resource configuration: " + config)
    bitmap = bitmap_source(ROOT, app)
    adaptive = None
    if bitmap:
        dest = target / "res/drawable-nodpi/clean_original.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bitmap, dest)
        icon = ET.Element("bitmap", {f"{{{ANDROID}}}src": "@drawable/clean_original",
                                     f"{{{ANDROID}}}gravity": "fill", f"{{{ANDROID}}}filter": "true"})
        for config in sorted(configs):
            folder = "res/drawable" + ("-" + config if config else "")
            write_xml(target / folder / "clean_icon.xml", icon)
        expected_images = {"clean_original.png": bitmap.read_bytes()}
        if background := bitmap_background(app):
            colors = ET.Element("resources")
            ET.SubElement(colors, "color", {"name": "clean_background"}).text = background
            write_xml(target / "res/values/colors.xml", colors)
            write_xml(target / "res/drawable/clean_bitmap_layer.xml", icon)
            # Keep the original artwork in the central 72 of the adaptive 108 units.
            # A matching opaque background fills the mask without a launcher white plate.
            foreground = ET.Element("inset", {f"{{{ANDROID}}}drawable": "@drawable/clean_bitmap_layer",
                                               f"{{{ANDROID}}}inset": "16.666667%"})
            write_xml(target / "res/drawable/clean_foreground_layer.xml", foreground)
            adaptive = ET.Element("adaptive-icon")
            ET.SubElement(adaptive, "background", {f"{{{ANDROID}}}drawable": "@color/clean_background"})
            ET.SubElement(adaptive, "foreground", {f"{{{ANDROID}}}drawable": "@drawable/clean_foreground_layer"})
    else:
        expected_images = {}
        for number, name in [(0, "background"), (1, "foreground")]:
            path = assets / f"{number}.png"
            expected = app["assets"][str(number)]
            content = path.read_bytes()
            if hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest() != expected:
                raise ValueError("Artwork changed since review: " + str(path))
            dest = target / "res/drawable-nodpi" / f"clean_{name}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            expected_images[f"clean_{name}.png"] = content
            wrapper = ET.Element("bitmap", {f"{{{ANDROID}}}src": f"@drawable/clean_{name}",
                                             f"{{{ANDROID}}}gravity": "fill", f"{{{ANDROID}}}filter": "true"})
            write_xml(target / f"res/drawable/clean_{name}_layer.xml", wrapper)
        adaptive = ET.Element("adaptive-icon")
        for name in ("background", "foreground"):
            ET.SubElement(adaptive, name, {f"{{{ANDROID}}}drawable": f"@drawable/clean_{name}_layer"})
        fallback = ET.Element("layer-list")
        for name in ("background", "foreground"):
            ET.SubElement(fallback, "item", {f"{{{ANDROID}}}drawable": f"@drawable/clean_{name}_layer"})
        write_xml(target / "res/drawable/clean_icon.xml", fallback)
    if adaptive is not None:
        adaptive_configs = set()
        for config in sorted(configs):
            version = re.search(r"-v(\d+)$", config)
            if version:
                config = config[:version.start()] + "-v" + str(max(26, int(version[1])))
            else:
                config = config + "-v26" if config else "v26"
            adaptive_configs.add(config)
        for config in sorted(adaptive_configs):
            write_xml(target / ("res/drawable-" + config) / "clean_icon.xml", adaptive)
    mapping = ET.Element("overlay")
    for entry in mapping_roots:
        ET.SubElement(mapping, "item", {"target": entry["name"], "value": "@drawable/clean_icon"})
    write_xml(target / "res/xml/overlays.xml", mapping)
    compiled = target / "compiled.zip"
    run(tools / "aapt2", "compile", "--no-crunch", "--dir", target / "res", "-o", compiled)
    unsigned, aligned, signed = [target / name for name in ["unsigned.apk", "aligned.apk", "overlay.apk"]]
    run(tools / "aapt2", "link", "--manifest", target / "AndroidManifest.xml", "-I", framework,
        "--no-auto-version", "--no-resource-deduping", "--no-resource-removal", "-o", unsigned, compiled)
    run(tools / "zipalign", "-p", "-f", "4", unsigned, aligned)
    run(tools / "apksigner", "sign", "--ks", key, "--ks-key-alias", "overlay", "--ks-pass",
        "env:CLEAN_ICONS_STORE_PASS", "--v1-signing-enabled", "false", "--v2-signing-enabled", "true",
        "--v3-signing-enabled", "true", "--out", signed, aligned, env=env)
    run(tools / "apksigner", "verify", "--verbose", signed)
    run(tools / "zipalign", "-c", "4", signed)
    actual = xml_tree(dump(tools / "aapt2", signed, "xmltree", "res/xml/overlays.xml"))
    actual_targets = sorted(n.attrs["target"] for n in actual.walk() if n.tag == "item")
    if actual_targets != sorted(r["name"] for r in mapping_roots):
        raise ValueError("Compiled overlay map differs from the reviewed resource map")
    compiled_table = resource_table(dump(tools / "aapt2", signed, "resources"))
    compiled_icon = next(v for v in compiled_table.values() if v["name"] == "drawable/clean_icon")
    compiled_configs = {v["config"] for v in compiled_icon["values"]}
    missing_versioned = {c for c in configs if re.search(r"-v\d+$", c)} - compiled_configs
    if missing_versioned:
        raise ValueError("AAPT collapsed target version qualifiers: " + str(missing_versioned))
    with zipfile.ZipFile(signed) as archive:
        if any(re.fullmatch(r"classes\d*\.dex", n) for n in archive.namelist()):
            raise ValueError("Resource-only overlay unexpectedly contains executable code")
        for name, expected in expected_images.items():
            paths = [n for n in archive.namelist() if n.endswith("/" + name)]
            if len(paths) != 1:
                raise ValueError("Compiled artwork missing")
            if archive.read(paths[0]) != expected:
                raise ValueError("Compiled artwork differs from its verified PNG source")
    return overlay_id, signed


def build_numeric_helper(tools, destination):
    folder = ROOT / "build/numeric-helper"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    run("javac", "--release", "8", "-Xlint:-options", "-d", folder, ROOT / "helper/NumericIcons.java")
    run("java", "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--min-api", "26", "--output", folder,
        *sorted(folder.glob("*.class")))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("classes.dex", (folder / "classes.dex").read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=ROOT / "targets.json")
    parser.add_argument("--tools", type=Path, default=ROOT / ".cache/toolchain")
    parser.add_argument("--framework", type=Path, default=ROOT / ".cache/framework-res.apk")
    args = parser.parse_args()
    spec = json.loads(args.targets.read_text())
    reasons = json.loads((ROOT / "selection.json").read_text())
    build = ROOT / "build/module"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    key, env = signing_environment()
    details, lines, maps, originals, numeric = [], [], [], [], []
    for app in spec["apps"]:
        app = dict(app, reason=reasons[app["package"]])
        overlay_id, apk = build_overlay(app, ROOT / "build/overlays" / app["package"], args.tools, args.framework, key, env)
        relative = Path("system/system_ext/overlay") / (overlay_id + ".apk")
        dest = build / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(apk, dest)
        lines.append("\t".join([app["package"], app["version_code"], overlay_id]))
        maps.extend("\t".join([overlay_id, entry["name"]]) for entry in app["roots"])
        if app.get("mapping_mode") == "numeric-idmap-v11":
            if len(app["roots"]) != 1 or len(app["seed_roots"]) != 1:
                raise ValueError("Numeric mappings require one seed and one target")
            numeric.append("\t".join([app["package"], app["version_code"], overlay_id,
                                      app["seed_roots"][0]["id"][1:], app["roots"][0]["id"][1:], app["numeric_target_crc"]]))
        if plan := app.get("original_preview"):
            if not re.fullmatch(r"(?:base|split_config\.[A-Za-z0-9_.-]+)\.apk", plan["apk"]):
                raise ValueError("Unsafe original preview APK")
            if not re.fullmatch(r"[A-Za-z0-9_./-]+\.png", plan["entry"]) or plan["entry"].startswith("/") or ".." in plan["entry"]:
                raise ValueError("Unsafe original preview path")
            originals.append("\t".join([app["package"], plan["apk"], plan["entry"]]))
        details.append(dict(app, overlay_package=overlay_id, path=str(relative), sha256=hashlib.sha256(apk.read_bytes()).hexdigest()))
        print(f"Verified {app['package']}: {len(app['roots'])} resource mappings", flush=True)
    for name in ["customize.sh", "check.sh", "refresh.sh", "boot-completed.sh", "ui.sh", "capture-originals.sh", "numeric.sh"]:
        shutil.copy2(ROOT / "module" / name, build / name)
    build_webui(ROOT, build / "webroot", spec, VERSION)
    (build / "targets.tsv").write_text("\n".join(lines) + "\n")
    (build / "maps.tsv").write_text("\n".join(maps) + "\n")
    (build / "originals.tsv").write_text("\n".join(originals) + ("\n" if originals else ""))
    (build / "numeric-targets.tsv").write_text("\n".join(numeric) + ("\n" if numeric else ""))
    if numeric:
        build_numeric_helper(args.tools, build / "numeric-icons.jar")
    manifest = {"version": VERSION, "upstream": spec["upstream"], "device": spec["device"], "apps": details}
    (build / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (build / "module.prop").write_text(f"id={MODULE_ID}\nname={DISPLAY_NAME}\nversion={VERSION}\nversionCode={VERSION_CODE}\n"
        f"author=Bingo\ndescription=Original color icons without marketing badges; {len(details)} apps, Pixel 9 Pro XL Android 17.\n")
    shutil.copy2(ROOT / "THIRD_PARTY.md", build / "THIRD_PARTY.md")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / f"{ARCHIVE_NAME}-{VERSION}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(build.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(build).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.external_attr = (0o100755 if path.suffix == ".sh" else 0o100644) << 16
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(f"{digest}  {output.name}\n")
    (dist / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {output} ({output.stat().st_size} bytes)\nSHA256 {digest}")


if __name__ == "__main__":
    main()
