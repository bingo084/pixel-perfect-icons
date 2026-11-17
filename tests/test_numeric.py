import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class NumericMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.classes = ROOT / "build/numeric-helper"
        if not (self.classes / "NumericIcons.class").exists():
            self.skipTest("Build the helper first")
        self.base = self.folder / "base.apk"
        self.overlay = self.folder / "overlay.apk"
        for path in [self.base, self.overlay]:
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("AndroidManifest.xml", path.name.encode())
                z.writestr("resources.arsc", b"metadata")
        self.seed = 0x7f070570
        self.target = 0x7f0d0009
        self.seed_overlay = 0x7f010004
        self.target_overlay = self.seed_overlay

    @staticmethod
    def string(text):
        raw = text.encode()
        return struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)

    @staticmethod
    def crc(path):
        with zipfile.ZipFile(path) as z:
            return z.getinfo("AndroidManifest.xml").CRC ^ z.getinfo("resources.arsc").CRC

    def mapping(self):
        data = struct.pack("<6I", 0x504d4449, 11, self.crc(self.base), self.crc(self.overlay), 3, 1)
        data += b"".join(self.string(t) for t in [str(self.base), str(self.overlay), "", ""])
        self.counts = len(data) + 4
        data += struct.pack("<7I", 0, 1, 0, 0, 0, 1, 7)
        self.entries = len(data)
        data += struct.pack("<5I", self.seed, self.seed_overlay, self.seed_overlay, self.seed, 4) + b"pool"
        return data

    def patch(self, data):
        source, dest = self.folder / "source.idmap", self.folder / "new.idmap"
        source.write_bytes(data)
        if dest.exists():
            dest.unlink()
        result = subprocess.run(["java", "-cp", str(self.classes), "NumericIcons", "patch", str(source), str(dest),
                                 hex(self.seed), hex(self.target), str(self.base), str(self.overlay), f'{self.crc(self.base):08x}',
                                 hex(self.seed_overlay), hex(self.target_overlay)], capture_output=True, text=True)
        self.assertEqual(source.read_bytes(), data)
        return result, dest

    def test_only_the_forward_and_reverse_ids_change_and_reapplication_is_idempotent(self):
        original = self.mapping()
        result, dest = self.patch(original)
        self.assertEqual(result.returncode, 0, result.stderr)
        patched = dest.read_bytes()
        expected = bytearray(original)
        struct.pack_into("<I", expected, self.entries, self.target)
        struct.pack_into("<I", expected, self.entries + 12, self.target)
        self.assertEqual(patched, expected)
        result, dest = self.patch(patched)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dest.read_bytes(), patched)

    def test_preserved_bootstrap_changes_both_resource_pairs_and_reapplication_is_idempotent(self):
        self.target_overlay = 0x7f010002
        original = self.mapping()
        result, dest = self.patch(original)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = bytearray(original)
        struct.pack_into('<4I', expected, self.entries, self.target, self.target_overlay, self.target_overlay, self.target)
        self.assertEqual(dest.read_bytes(), expected)
        result, dest = self.patch(bytes(expected))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dest.read_bytes(), expected)
        # A half-updated pair must not be accepted as a reviewed initial/final state.
        for target, overlay in [(self.seed, self.target_overlay), (self.target, self.seed_overlay)]:
            mixed = bytearray(original)
            struct.pack_into('<4I', mixed, self.entries, target, overlay, overlay, target)
            result, dest = self.patch(mixed)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(dest.exists())

    def test_changed_headers_paths_crcs_entries_and_bounds_fail_before_output(self):
        original = self.mapping()
        variants = [original[:12], original[:-1]]
        for offset, value in [(0, 0), (4, 12), (8, 0), (12, 0), (16, 1), (20, 0), (24, 0x7fffffff),
                              (self.counts, 2), (self.entries, 0x7f070999), (self.entries + 12, 0),
                              (self.entries + 8, 0x7f010099), (self.entries + 16, 0x7fffffff)]:
            changed = bytearray(original)
            struct.pack_into("<I", changed, offset, value)
            variants.append(bytes(changed))
        variants.append(original.replace(str(self.base).encode(), str(self.base).upper().encode()))
        for index, data in enumerate(variants):
            with self.subTest(index=index):
                result, dest = self.patch(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(dest.exists())

    def test_same_version_package_with_changed_resources_is_rejected(self):
        original = self.mapping()
        pinned = f'{self.crc(self.base):08x}'
        with zipfile.ZipFile(self.base, 'w') as z:
            z.writestr('AndroidManifest.xml', b'same-version-other-channel')
            z.writestr('resources.arsc', b'different-resources')
        changed = bytearray(original)
        struct.pack_into('<I', changed, 8, self.crc(self.base))
        source, dest = self.folder / 'different.idmap', self.folder / 'new.idmap'
        source.write_bytes(changed)
        result = subprocess.run(['java', '-cp', str(self.classes), 'NumericIcons', 'patch', str(source), str(dest),
                                 hex(self.seed), hex(self.target), str(self.base), str(self.overlay), pinned,
                                 hex(self.seed_overlay), hex(self.target_overlay)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reviewed scan', result.stderr)
        self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
