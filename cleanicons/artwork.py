"""Validate the optional original-APK bitmap used for a scoped icon cleanup."""

import hashlib
from pathlib import Path
import re


def bitmap_background(app):
    background = app.get("artwork", {}).get("adaptive_background")
    if background is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        raise ValueError("Invalid adaptive bitmap background")
    return background


def bitmap_source(root, app):
    artwork = app.get("artwork")
    if not artwork:
        return None
    if artwork.get("kind") != "apk-bitmap":
        raise ValueError("Unknown artwork kind")
    path = Path(artwork["file"])
    allowed = (root / ".cache/device" / app["package"] / "files").resolve()
    if path.is_absolute() or not (root / path).resolve().is_relative_to(allowed):
        raise ValueError("APK artwork must be inside its scanned resource directory")
    content = (root / path).read_bytes()
    if not content.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(content).hexdigest() != artwork["sha256"]:
        raise ValueError("Scanned APK artwork changed: " + app["package"])
    return root / path


def bootstrap_source(root, app):
    """The initial non-launcher mapping must preserve its reviewed bitmap bytes."""
    artwork = app.get("bootstrap_artwork")
    if not artwork:
        return None
    if app.get("mapping_mode") != "numeric-idmap-v11" or len(app.get("seed_roots", [])) != 1:
        raise ValueError("Preserved bootstrap requires a single numeric seed")
    seed = app["seed_roots"][0]
    if (seed["id"] != artwork["source_resource"] or seed["name"] != artwork["source_name"] or
            seed["configs"] != [artwork["config"]] or artwork["apk"] != "base.apk"):
        raise ValueError("Bootstrap configuration differs from the reviewed seed")
    path = Path(artwork["file"])
    allowed = (root / ".cache/device" / app["package"] / "files").resolve()
    if path.is_absolute() or not (root / path).resolve().is_relative_to(allowed):
        raise ValueError("Bootstrap image must be inside its scanned resource directory")
    content = (root / path).read_bytes()
    valid = (path.suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n") or
             path.suffix == ".webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    if not valid or hashlib.sha256(content).hexdigest() != artwork["sha256"]:
        raise ValueError("Scanned bootstrap bitmap changed: " + app["package"])
    return root / path
