#!/usr/bin/env python3
"""Download a private, checksum-verified subset of official Linux Build Tools 37."""

import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
URL = "https://dl.google.com/android/repository/build-tools_r37_linux.zip"
SHA1 = "70954e99f4c3d9d46ee70fa32624672fe7cd6ebe"
FILES = {"aapt2", "apksigner", "zipalign", "lib/apksigner.jar", "lib/d8.jar", "lib64/libc++.so"}


def main():
    archive = ROOT / ".cache/build-tools_r37_linux.zip"
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix(".download")
        with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.replace(archive)
    if hashlib.sha1(archive.read_bytes()).hexdigest() != SHA1:
        raise SystemExit("Build Tools archive differs from Google's repository checksum")
    extracted = set()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            relative = Path(*Path(entry.filename).parts[1:])
            if relative.as_posix() in FILES:
                target = ROOT / ".cache/toolchain" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(entry))
                target.chmod(0o755 if relative.parent == Path(".") else 0o644)
                extracted.add(relative.as_posix())
    if extracted != FILES:
        raise SystemExit("Official Build Tools archive layout changed")
    print("Verified and extracted Google Build Tools 37 to .cache/toolchain")


if __name__ == "__main__":
    main()
