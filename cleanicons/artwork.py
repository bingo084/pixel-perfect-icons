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
