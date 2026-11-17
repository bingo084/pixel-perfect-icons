import copy
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from build import validate_target
from cleanicons.resources import dump, launcher_icons, resolved_values, resource_table, xml_tree

ROOT = Path(__file__).resolve().parents[1]


class LauncherResourceTests(unittest.TestCase):
    def test_disabled_marketing_alias_is_included_but_non_launcher_is_not(self):
        tree = xml_tree('''E: manifest
  E: application
    A: android:icon(0x01010002)=@0x7f010001
    E: activity-alias
      A: android:name="MarketingAlias"
      A: android:enabled=false
      A: android:icon=@0x7f010002
      E: intent-filter
        E: action
          A: android:name="android.intent.action.MAIN"
        E: category
          A: android:name="android.intent.category.LAUNCHER"
    E: activity
      A: android:name="PaymentScreen"
      A: android:icon=@0x7f010099
''')
        refs, components = launcher_icons(tree)
        self.assertEqual(refs, ["@0x7f010001", "@0x7f010002"])
        self.assertEqual(components, ["MarketingAlias"])

    def test_density_and_version_specific_configurations_are_retained(self):
        table = resource_table('''resource 0x7f010001 mipmap/icon
  (xxhdpi) (file) res/A.png type=PNG
  (anydpi-v33) (file) res/B.xml type=XML
resource 0x7f010002 drawable/other
  () #ff000000
''')
        self.assertEqual([v["config"] for v in table["@0x7f010001"]["values"]], ["xxhdpi", "anydpi-v33"])
        self.assertEqual(table["@0x7f010002"]["name"], "drawable/other")

    def test_ambiguous_obfuscated_names_fail_closed(self):
        app = copy.deepcopy(json.loads((ROOT / "targets.json").read_text())["apps"][0])
        app["roots"] = [{"name": "mipmap/_"}, {"name": "mipmap/_"}]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            validate_target(app)

    def test_named_alias_and_shrunk_resource_path_are_resolved(self):
        table = resource_table('''resource 0x7f010001 drawable/logo
  () @mipmap/pdd
resource 0x7f020001 mipmap/pdd
  (xxhdpi) "r/ab/icon.png"
''')
        values = list(resolved_values(table, "@0x7f010001"))
        self.assertEqual(values, [{"config": "xxhdpi", "value": '"r/ab/icon.png"'}])

    def test_resource_alias_cycle_is_rejected(self):
        table = resource_table('''resource 0x7f010001 drawable/a
  () @drawable/b
resource 0x7f010002 drawable/b
  () @drawable/a
''')
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            list(resolved_values(table, "@0x7f010001"))

    def test_overlayable_targets_require_explicit_review(self):
        app = copy.deepcopy(json.loads((ROOT / "targets.json").read_text())["apps"][0])
        app["has_overlayable"] = True
        with self.assertRaisesRegex(ValueError, "policy"):
            validate_target(app)


class InstallerTests(unittest.TestCase):
    def install_simulation(self, version="42", sdk="37", device="komodo"):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "targets.tsv").write_text("example.app\t42\tlocal.overlay\n")
            script = f'''
KSU=true
MODPATH={tmp}
abort() {{ printf 'ABORT %s\\n' "$*"; exit 1; }}
ui_print() {{ :; }}
getprop() {{ case "$1" in ro.product.device) printf '%s' '{device}';; *) printf '%s' '{sdk}';; esac; }}
dumpsys() {{ printf '%s\\n' 'versionCode={version} minSdk=26'; }}
set_perm_recursive() {{ printf 'PERMISSIONS_APPLIED\\n'; }}
set_perm() {{ :; }}
. {ROOT / 'module/customize.sh'}
[ ! -f "$MODPATH/.refresh-pending" ] || printf 'REFRESH_PENDING\\n'
'''
            return subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    def test_matching_versions_pass(self):
        result = self.install_simulation()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PERMISSIONS_APPLIED", result.stdout)
        self.assertIn("REFRESH_PENDING", result.stdout)

    def test_changed_app_aborts_before_installation_permissions(self):
        result = self.install_simulation(version="43")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed or is missing", result.stdout)
        self.assertNotIn("PERMISSIONS_APPLIED", result.stdout)

    def test_wrong_platform_aborts(self):
        for sdk, device in [("36", "komodo"), ("37", "other")]:
            with self.subTest(sdk=sdk, device=device):
                result = self.install_simulation(sdk=sdk, device=device)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("PERMISSIONS_APPLIED", result.stdout)

    def test_shell_syntax(self):
        for script in (ROOT / "module").glob("*.sh"):
            subprocess.run(["sh", "-n", str(script)], check=True)


class BuiltArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tools = ROOT / ".cache/toolchain/aapt2"
        self.apk = ROOT / "build/overlays/tv.danmaku.bili/overlay.apk"
        if not self.tools.exists() or not self.apk.exists():
            self.skipTest("Build the APKs first to run the binary resource regression checks")

    def test_compiled_adaptive_icon_keeps_version_specific_configuration(self):
        table = resource_table(dump(self.tools, self.apk, "resources"))
        icon = next(r for r in table.values() if r["name"] == "drawable/clean_icon")
        configs = {v["config"] for v in icon["values"]}
        self.assertIn("anydpi-v26", configs)
        self.assertIn("xxhdpi-v26", configs)

    def test_pre26_fallback_and_adaptive_variant_have_correct_drawable_types(self):
        legacy = xml_tree(dump(self.tools, self.apk, "xmltree", "res/drawable/clean_icon.xml"))
        adaptive = xml_tree(dump(self.tools, self.apk, "xmltree", "res/drawable-v26/clean_icon.xml"))
        self.assertIn("layer-list", {n.tag for n in legacy.walk()})
        self.assertIn("adaptive-icon", {n.tag for n in adaptive.walk()})


class NetdiskArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tools = ROOT / ".cache/toolchain/aapt2"
        self.apk = ROOT / "build/overlays/com.baidu.netdisk/overlay.apk"
        if not self.tools.exists() or not self.apk.exists():
            self.skipTest("Build the APKs first")
        self.expected = {"drawable/ic_element_appicon_netdisk", "drawable/ic_element_appicon_op", "drawable/ic_element_appicon_svip"}

    def test_default_and_both_alternate_entry_icons_are_mapped(self):
        mapping = xml_tree(dump(self.tools, self.apk, "xmltree", "res/xml/overlays.xml"))
        self.assertEqual({n.attrs["target"] for n in mapping.walk() if n.tag == "item"}, self.expected)
        table = resource_table(dump(self.tools, self.apk, "resources"))
        icon = next(r for r in table.values() if r["name"] == "drawable/clean_icon")
        self.assertTrue({"v26", "mdpi-v26", "hdpi-v26", "xhdpi-v26", "xxhdpi-v26"}.issubset({v["config"] for v in icon["values"]}))

    def test_all_targets_are_unique_resources_in_the_base_apk(self):
        base = ROOT / ".cache/device/com.baidu.netdisk/base.apk"
        table = resource_table(dump(self.tools, base, "resources"))
        names = Counter(r["name"] for r in table.values())
        manifest = xml_tree(dump(self.tools, base, "xmltree", "AndroidManifest.xml"))
        refs, _ = launcher_icons(manifest)
        self.assertEqual({table[r]["name"] for r in refs}, self.expected)
        for name in self.expected:
            self.assertEqual(names[name], 1, name)


class PddIdlefishArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tools = ROOT / ".cache/toolchain/aapt2"
        self.targets = {a["package"]: a for a in json.loads((ROOT / "targets.json").read_text())["apps"]}
        if not self.tools.exists():
            self.skipTest("Build the APKs first")

    def overlay(self, package):
        apk = ROOT / "build/overlays" / package / "overlay.apk"
        if not apk.exists():
            self.skipTest("Build the APKs first")
        return apk

    def test_pdd_maps_only_the_unique_base_launcher_alias(self):
        package = "com.xunmeng.pinduoduo"
        mapping = xml_tree(dump(self.tools, self.overlay(package), "xmltree", "res/xml/overlays.xml"))
        self.assertEqual([n.attrs["target"] for n in mapping.walk() if n.tag == "item"], ["drawable/logo"])
        table = resource_table(dump(self.tools, ROOT / ".cache/device" / package / "base.apk", "resources"))
        self.assertEqual(sum(e["name"] == "drawable/logo" for e in table.values()), 1)
        self.assertEqual(sum(e["name"] == "mipmap/pdd" for e in table.values()), 13)
        if plan := self.targets[package].get("original_preview"):
            self.assertEqual((plan["apk"], plan["entry"], plan["resolved_resource"]),
                             ("base.apk", "r/cy.png", "@0x7f0d0009"))
        else:
            self.assertTrue((ROOT / ".cache/device/com.xunmeng.pinduoduo/files/r/cy.png").exists())
        self.assertEqual(self.targets[package]["roots"][0]["id"], "@0x7f0d0009")
        self.assertEqual(self.targets[package]["seed_roots"][0]["id"], "@0x7f070570")
        compiled = resource_table(dump(self.tools, self.overlay(package), "resources"))
        icon = next(r for r in compiled.values() if r["name"] == "drawable/clean_icon")
        self.assertIn("anydpi-v26", {v["config"] for v in icon["values"]})

    def test_idlefish_bootstrap_uses_badge_but_runtime_mapping_targets_the_normal_icon(self):
        package = "com.taobao.idlefish"
        mapping = xml_tree(dump(self.tools, self.overlay(package), "xmltree", "res/xml/overlays.xml"))
        self.assertEqual([n.attrs["target"] for n in mapping.walk() if n.tag == "item"],
                         ["drawable/appicon_skin_default_badge"])
        base = resource_table(dump(self.tools, ROOT / ".cache/device" / package / "base.apk", "resources"))
        self.assertEqual(base["@0x7f08021e"]["name"], "drawable/appicon_skin_default_badge")
        self.assertNotIn("@0x7f0807a6", base)
        self.assertEqual(self.targets[package]["roots"][0]["id"], "@0x7f0807a6")
        self.assertEqual(self.targets[package]["seed_roots"][0]["id"], "@0x7f08021e")
        self.assertEqual(self.targets[package]["mapping_mode"], "numeric-idmap-v11")

    def test_idlefish_uses_verified_upstream_layers_for_the_adaptive_icon(self):
        package = "com.taobao.idlefish"
        apk = self.overlay(package)
        table = resource_table(dump(self.tools, apk, "resources"))
        icon = next(r for r in table.values() if r["name"] == "drawable/clean_icon")
        self.assertTrue({"", "v26", "xxhdpi-v26"}.issubset({v["config"] for v in icon["values"]}))
        for entry in ["res/drawable-v26/clean_icon.xml", "res/drawable-xxhdpi-v26/clean_icon.xml"]:
            adaptive = xml_tree(dump(self.tools, apk, "xmltree", entry))
            self.assertIn("adaptive-icon", {n.tag for n in adaptive.walk()})
            self.assertTrue({"background", "foreground"}.issubset({n.tag for n in adaptive.walk()}))
        self.assertNotIn("artwork", self.targets[package])
        self.assertEqual(set(self.targets[package]["assets"]), {"0", "1"})
        with zipfile.ZipFile(apk) as archive:
            self.assertFalse(any(p.endswith("/clean_original.png") for p in archive.namelist()))
            for number, layer in [(0, "background"), (1, "foreground")]:
                paths = [p for p in archive.namelist() if p.endswith(f"/clean_{layer}.png")]
                self.assertEqual(len(paths), 1)
                self.assertEqual(archive.read(paths[0]), (ROOT / ".cache/upstream" / package / f"{number}.png").read_bytes())


class RuntimeCheckerTests(unittest.TestCase):
    def run_checker(self, value, mode=None, state="STATE_ENABLED", dump_exit=0, lookup_exit=0, mapping=True):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "check.sh").write_bytes((ROOT / "module/check.sh").read_bytes())
            (folder / "targets.tsv").write_text("example.app\t42\tlocal.overlay\n")
            (folder / "maps.tsv").write_text("local.overlay\tmipmap/icon\n")
            command = folder / "cmd"
            command.write_text('''#!/bin/sh
if [ "$2" = dump ]; then
 printf 'mState: %s\\n' "$ICON_OVERLAY_STATE"
 if [ "$ICON_MAPPING" = 1 ]; then printf '%s\\n' '0x7f010001 -> 0x7f010002 (mipmap/icon -> drawable/clean_icon)'; fi
 exit "$ICON_DUMP_EXIT"
else
 printf '%s\\n' "$ICON_LOOKUP_VALUE"
 exit "$ICON_LOOKUP_EXIT"
fi
''')
            command.chmod(0o755)
            env = dict(os.environ, PATH=tmp+os.pathsep+os.environ["PATH"], ICON_LOOKUP_VALUE=value,
                       ICON_OVERLAY_STATE=state, ICON_DUMP_EXIT=str(dump_exit), ICON_LOOKUP_EXIT=str(lookup_exit),
                       ICON_MAPPING="1" if mapping else "0")
            return subprocess.run(["sh", str(folder / "check.sh"), *([mode] if mode else [])], capture_output=True, text=True, env=env)

    def test_enabled_mapping_with_original_resource_is_not_success(self):
        result = self.run_checker("res/mipmap-anydpi-v26/ic_launcher.xml")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT SELECTED", result.stdout)

    def test_enabled_mapping_selecting_clean_icon_succeeds(self):
        result = self.run_checker("res/drawable-anydpi-v26/clean_icon.xml")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Failed overlay/resource checks: 0", result.stdout)

    def test_webui_state_is_active_only_when_replacement_is_selected(self):
        for value, status, code in [("res/drawable-anydpi-v26/clean_icon.xml", "active", 0),
                                    ("res/mipmap-anydpi-v26/ic_launcher.xml", "inactive", 1)]:
            with self.subTest(value=value):
                result = self.run_checker(value, "--tsv")
                self.assertEqual(result.returncode, code)
                issue = "-" if status == "active" else "resource-not-selected"
                self.assertEqual(result.stdout, "example.app\t" + status + "\t" + issue + "\n")

    def test_failure_explanations_distinguish_inactive_from_unavailable_checks(self):
        cases = [({"state": "STATE_DISABLED"}, "inactive", "disabled"),
                 ({"state": "STATE_NO_IDMAP"}, "inactive", "mapping-missing"),
                 ({"mapping": False}, "inactive", "mapping-missing"),
                 ({"lookup_exit": 1}, "unknown", "check-unavailable"),
                 ({"dump_exit": 1}, "unknown", "check-unavailable")]
        for options, status, issue in cases:
            with self.subTest(options=options):
                result = self.run_checker("res/drawable-anydpi-v26/clean_icon.xml", "--tsv", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "example.app\t"+status+"\t"+issue+"\n")


if __name__ == "__main__":
    unittest.main()
