import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"original-apk-png-test"


class CaptureOriginalTests(unittest.TestCase):
    def capture(self, *, entry="r/cy.png", content=PNG, source_exists=True):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copyfile(ROOT / "module/capture-originals.sh", folder / "capture-originals.sh")
            (folder / "originals.tsv").write_text(f"example.app\tbase.apk\t{entry}\n")
            destination = folder / "webroot/assets/example.app.before.png"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"placeholder")
            inode = destination.stat().st_ino
            apk = folder / "base.apk"
            if source_exists:
                with zipfile.ZipFile(apk, "w") as archive:
                    archive.writestr("r/cy.png", content)
            pm = folder / "pm"
            pm.write_text("#!/bin/sh\nprintf 'package:%s/base.apk\\n' '" + tmp + "'\n")
            pm.chmod(0o755)
            env = dict(os.environ, PATH=tmp+os.pathsep+os.environ["PATH"])
            result = subprocess.run(["sh", str(folder / "capture-originals.sh")], capture_output=True, text=True, env=env)
            return result, destination.read_bytes(), inode == destination.stat().st_ino, list(folder.glob(".original-preview.*"))

    def test_png_is_read_from_the_apk_without_replacing_the_destination_inode(self):
        result, content, preserved, temporary = self.capture()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(content, PNG)
        self.assertTrue(preserved)
        self.assertEqual(temporary, [])

    def test_missing_apk_invalid_png_and_unsafe_paths_keep_the_placeholder(self):
        for arguments in [{"source_exists": False}, {"content": b"not-png"}, {"entry": "../outside.png"}, {"entry": "/absolute.png"}]:
            with self.subTest(arguments=arguments):
                result, content, preserved, temporary = self.capture(**arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(content, b"placeholder")
                self.assertTrue(preserved)
                self.assertEqual(temporary, [])


if __name__ == "__main__":
    unittest.main()
