import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from build import ARCHIVE_NAME, VERSION

ROOT = Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    def snapshot(self, *, query_exit=0, user="0", action="snapshot"):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shutil.copyfile(ROOT / "module/ui.sh", folder / "ui.sh")
            (folder / "check.sh").write_text("printf 'example.app\\tinactive\\n'; exit 1\n")
            commands = {
                "id": "echo 0",
                "am": f"echo {user}",
                "cmd": f"""cat <<'OUT'
3 activities found:
example.app/.MainActivity
example.app/.OtherActivity
com.system.launcher/.Main
example.app/.DisabledActivity with-extra-output
not-a-package/.Bad
OUT
exit {query_exit}""",
            }
            for name, body in commands.items():
                file = folder / name
                file.write_text("#!/bin/sh\n" + body + "\n")
                file.chmod(0o755)
            env = dict(os.environ, PATH=tmp+os.pathsep+os.environ["PATH"])
            return subprocess.run(["sh", str(folder / "ui.sh"), action], capture_output=True, text=True, env=env)

    def test_only_launcher_packages_are_returned_deduplicated(self):
        result = self.snapshot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PIXEL_CLEAN_ICONS_V1\ncom.system.launcher\nexample.app\n__OVERLAY_STATES__\nexample.app\tinactive\n")

    def test_query_failure_is_not_an_empty_success(self):
        result = self.snapshot(query_exit=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PIXEL_CLEAN_ICONS_V1", result.stdout)

    def test_other_android_users_are_rejected(self):
        result = self.snapshot(user="10")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_webui_dispatch_does_not_execute_arbitrary_arguments(self):
        result = self.snapshot(action="snapshot; echo injected")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("injected", result.stdout)


class WebPackageTests(unittest.TestCase):
    def test_packaged_interface_has_all_comparisons_and_no_action_entry(self):
        path = ROOT / "dist" / f"{ARCHIVE_NAME}-{VERSION}.zip"
        if not path.exists():
            self.skipTest("Build the module first")
        with zipfile.ZipFile(path) as archive:
            self.assertNotIn("action.sh", archive.namelist())
            catalog = json.loads(archive.read("webroot/catalog.json"))
            targets = json.loads((ROOT / "targets.json").read_text())["apps"]
            self.assertEqual({a["package"] for a in catalog["apps"]}, {a["package"] for a in targets})
            for app in catalog["apps"]:
                for key in ["before", "after"]:
                    self.assertTrue(app[key], app["package"])
                    self.assertTrue(archive.read("webroot/"+app[key]).startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertIn(app["reason"], ["移除营销装饰", "适配自适应图标"])
                self.assertEqual(app["source"], "补全计划")
                self.assertNotIn("scope", app)
            self.assertNotIn("notes", catalog)
            for package in ["cmb.pb", "com.autonavi.minimap"]:
                self.assertIn(package, {a["package"] for a in catalog["apps"]})
            for name in ["webroot/vendor/kernelsu.js", "webroot/vendor/LICENSE-Apache-2.0.txt", "ui.sh"]:
                self.assertIn(name, archive.namelist())
            pdd = next(a for a in catalog["apps"] if a["package"] == "com.xunmeng.pinduoduo")
            self.assertTrue(pdd["before"])
            plan = next(a for a in targets if a["package"] == "com.xunmeng.pinduoduo").get("original_preview")
            if plan:
                self.assertIn("com.xunmeng.pinduoduo\tbase.apk\tr/cy.png\n", archive.read("originals.tsv").decode())
            else:
                self.assertNotIn("com.xunmeng.pinduoduo", archive.read("originals.tsv").decode())
            idlefish = next(a for a in catalog["apps"] if a["package"] == "com.taobao.idlefish")
            self.assertEqual(idlefish["reason"], "适配自适应图标")
            self.assertIn("webroot/commands.mjs", archive.namelist())
            self.assertIn("numeric-icons.jar", archive.namelist())
            self.assertIn("numeric.sh", archive.namelist())
            self.assertIn("com.taobao.idlefish\t529\tlocal.pixelcleanicons.com_taobao_idlefish\t0x7f08021e\t0x7f0807a6", archive.read("numeric-targets.tsv").decode())
            self.assertIn("capture-originals.sh", archive.namelist())

    def test_unadapted_reasons_are_documented_instead_of_shipped_as_ui_notes(self):
        self.assertFalse((ROOT / "webui/notes.json").exists())
        notes = (ROOT / "docs/unsupported-apps.md").read_text()
        self.assertIn("招商银行、高德地图", notes)
        self.assertIn("QQ", notes)


if __name__ == "__main__":
    unittest.main()
