import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CACHE_FILES = ["app_icons.db", "app_icons.db-journal", "app_icons.db-wal", "app_icons.db-shm"]


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.module = self.root / "module"
        self.db = self.root / "databases"
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        for folder in [self.module, self.db, self.bin]:
            folder.mkdir()
        for name in ["ui.sh", "boot-completed.sh"]:
            shutil.copyfile(ROOT / "module" / name, self.module / name)
        script = (ROOT / "module/refresh.sh").read_text()
        script = script.replace("DBDIR=/data/user/0/com.google.android.apps.nexuslauncher/databases", f"DBDIR={self.db}")
        script = script.replace("STATEDIR=/data/adb/pixel-clean-icons", f"STATEDIR={self.state}")
        (self.module / "refresh.sh").write_text(script)
        (self.module / "check.sh").write_text('printf "RESOURCE_CHECK\\n"; exit "${CHECK_EXIT:-0}"\n')
        self.pending = self.module / ".refresh-pending"
        self.pending.touch()
        for name in CACHE_FILES + ["launcher.db", "launcher_5_by_6.db", "widgetpreviews.db", "app_icons.db-extra"]:
            (self.db / name).write_text("original:" + name)
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ["PATH"], TEST_ROOT=str(self.root))
        self.mock("id", 'printf "0\\n"')
        self.mock("getprop", 'case "$1" in ro.product.device) echo komodo;; *) echo 37;; esac')
        self.mock("cmd", 'echo "${DEFAULT_HOME:-com.google.android.apps.nexuslauncher/.NexusLauncherActivity}"')
        self.mock("dumpsys", 'echo "topResumedActivity=ActivityRecord{ ${FOREGROUND:-com.google.android.apps.nexuslauncher/.NexusLauncherActivity} }"')
        self.mock("pidof", '[ "${STILL_RUNNING:-0}" = 1 ] && { echo 123; exit 0; }; exit 1')
        self.mock("sleep", 'echo WAIT >> "$TEST_ROOT/events"; touch "$TEST_ROOT/unlocked"')
        self.mock("am", '''case "$1" in
get-started-user-state)
 if [ "${LOCKED:-0}" = 1 ] && [ ! -f "$TEST_ROOT/unlocked" ]; then echo RUNNING_LOCKED; else echo RUNNING_UNLOCKED; fi;;
get-current-user) echo "${CURRENT_USER:-0}";;
force-stop) echo STOP >> "$TEST_ROOT/events"; exit "${STOP_EXIT:-0}";;
start) echo HOME >> "$TEST_ROOT/events";;
esac''')

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, name="refresh.sh", mode="manual", **env):
        return subprocess.run(["sh", str(self.module / name), mode], env=dict(self.env, **env), capture_output=True, text=True, timeout=10)

    def events(self):
        file = self.root / "events"
        return file.read_text().splitlines() if file.exists() else []

    def assert_cache_unchanged(self):
        for name in CACHE_FILES:
            self.assertEqual((self.db / name).read_text(), "original:" + name)
        self.assertTrue(self.pending.exists())

    def test_webui_clears_only_icon_cache_and_reopens_foreground_home(self):
        result = self.run_script("ui.sh", "clear-cache")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.events(), ["STOP", "HOME"])
        for name in CACHE_FILES:
            self.assertFalse((self.db / name).exists())
        for name in ["launcher.db", "launcher_5_by_6.db", "widgetpreviews.db", "app_icons.db-extra"]:
            self.assertEqual((self.db / name).read_text(), "original:" + name)
        self.assertFalse(self.pending.exists())
        self.assertEqual({p.name for p in self.state.iterdir()}, {"refresh.lock", "last-refresh.log", "last-check.log"})

    def test_auto_waits_for_unlock_and_runs_only_once(self):
        first = self.run_script("boot-completed.sh", LOCKED="1")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(self.events(), ["WAIT", "STOP", "HOME"])
        old_log = (self.state / "last-refresh.log").read_bytes()
        second = self.run_script("boot-completed.sh")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(self.events(), ["WAIT", "STOP", "HOME"])
        self.assertEqual((self.state / "last-refresh.log").read_bytes(), old_log)

    def test_manual_refresh_works_without_an_install_pending_flag(self):
        self.pending.unlink()
        result = self.run_script("ui.sh", "clear-cache")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.events(), ["STOP", "HOME"])

    def test_numeric_mapping_failure_keeps_cache_and_pending_flag(self):
        (self.module / "numeric-targets.tsv").write_text("example.app\n")
        (self.module / "numeric.sh").write_text("echo 'Unsupported idmap format'; exit 1\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assert_cache_unchanged()
        self.assertEqual(self.events(), [])

    def test_ordinary_boot_maintains_numeric_mapping_without_clearing_cache(self):
        self.pending.unlink()
        (self.module / "numeric-targets.tsv").write_text("example.app\n")
        (self.module / "numeric.sh").write_text('echo MAPPING >> "$TEST_ROOT/events"; exit 0\n')
        result = self.run_script("boot-completed.sh")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.events(), ["MAPPING"])
        for name in CACHE_FILES:
            self.assertTrue((self.db / name).exists())

    def test_disabled_auto_job_does_not_refresh(self):
        (self.module / "disable").touch()
        result = self.run_script("boot-completed.sh")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_cache_unchanged()
        self.assertEqual(self.events(), [])

    def test_other_foreground_app_keeps_focus(self):
        result = self.run_script(FOREGROUND="example.app/.MainActivity")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.events(), ["STOP"])

    def test_locked_manual_request_does_not_touch_cache(self):
        result = self.run_script(LOCKED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assert_cache_unchanged()
        self.assertEqual(self.events(), [])

    def test_failed_resource_check_leaves_pending_and_cache_untouched(self):
        result = self.run_script(CHECK_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assert_cache_unchanged()
        self.assertEqual(self.events(), [])

    def test_wrong_user_or_default_launcher_does_not_stop_launcher(self):
        for env in [{"CURRENT_USER": "10"}, {"DEFAULT_HOME": "example.launcher/.Home"}]:
            with self.subTest(env=env):
                result = self.run_script(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assert_cache_unchanged()
                self.assertEqual(self.events(), [])

    def test_failed_stop_or_living_process_prevents_deletion(self):
        for env in [{"STOP_EXIT": "1"}, {"STILL_RUNNING": "1"}]:
            with self.subTest(env=env):
                result = self.run_script(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assert_cache_unchanged()

    def test_cache_symlink_is_rejected(self):
        (self.db / "app_icons.db").unlink()
        (self.db / "app_icons.db").symlink_to(self.db / "launcher.db")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.db / "launcher.db").read_text(), "original:launcher.db")
        self.assertEqual(self.events(), [])
        self.assertTrue(self.pending.exists())

    def test_another_refresh_lock_prevents_deletion(self):
        self.state.mkdir()
        with (self.state / "refresh.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assert_cache_unchanged()
        self.assertEqual(self.events(), [])

    def test_empty_cache_completes_without_stopping_launcher(self):
        for name in CACHE_FILES:
            (self.db / name).unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.events(), [])
        self.assertFalse(self.pending.exists())

    def test_diagnostic_log_is_bounded(self):
        (self.module / "check.sh").write_text("head -c 70000 /dev/zero; exit 1\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual((self.state / "last-check.log").stat().st_size, 32768)
        self.assert_cache_unchanged()


if __name__ == "__main__":
    unittest.main()
