#!/usr/bin/env python3
"""Fetch only the reviewed foreground/background pairs at the pinned commit."""

import hashlib
import json
from pathlib import Path

from scan import fetch
from cleanicons.artwork import bitmap_source

ROOT = Path(__file__).resolve().parent


def main():
    spec = json.loads((ROOT / "targets.json").read_text())
    upstream = spec["upstream"]
    for app in spec["apps"]:
        if bitmap_source(ROOT, app):
            print("Verified original APK bitmap: " + app["package"])
            continue
        for number in (0, 1):
            dest = ROOT / ".cache/upstream" / app["package"] / f"{number}.png"
            expected = app["assets"][str(number)]
            content = dest.read_bytes() if dest.exists() else b""
            digest = lambda data: hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if digest(content) != expected:
                content = fetch(f"https://raw.githubusercontent.com/{upstream['repository']}/{upstream['commit']}/icons/{app['package']}/{number}.png")
                if digest(content) != expected:
                    raise SystemExit("Upstream hash mismatch: " + str(dest))
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
        print("Verified " + app["package"])


if __name__ == "__main__":
    main()
