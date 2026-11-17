import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NumericLauncherCheckTests(unittest.TestCase):
    def run_check(self, activity_icon, application_icon):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            module = folder / 'module'
            commands = folder / 'bin'
            cache = folder / 'cache'
            overlay = folder / 'overlay'
            apps = folder / 'apps/example'
            for path in (module, commands, cache, overlay, apps):
                path.mkdir(parents=True)
            script = (ROOT / 'module/numeric.sh').read_text()
            script = script.replace('/data/resource-cache', str(cache)).replace('/system_ext/overlay', str(overlay))
            script = script.replace('/data/app/', str(folder / 'apps') + '/')
            (module / 'numeric.sh').write_text(script)
            (module / 'numeric-icons.jar').touch()
            (module / 'numeric-targets.tsv').write_text(
                'example.app\t42\tlocal.pixelcleanicons.example_app\t0x7f080001\t0x7f080002\t12345678\t0x7f010005\t0x7f010004\n')
            (cache / 'system_ext@overlay@local.pixelcleanicons.example_app.apk@idmap').touch()
            (overlay / 'local.pixelcleanicons.example_app.apk').touch()
            (apps / 'base.apk').touch()
            bodies = {
                'id': 'echo 0',
                'getprop': 'case "$1" in ro.product.device) echo komodo;; *) echo 37;; esac',
                'dumpsys': 'echo versionCode=42',
                'pm': f'echo package:{apps}/base.apk',
                'cmd': f'''cat <<'OUT'
ActivityInfo:
  labelRes=0x0 icon={activity_icon} banner=0x0
  ApplicationInfo:
    labelRes=0x0 icon={application_icon} banner=0x0
OUT''',
                'app_process': 'shift 3; printf "%s\\n" "$@" > "$NUMERIC_ARGS"',
            }
            for name, body in bodies.items():
                path = commands / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            output = folder / 'helper-args'
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'], NUMERIC_ARGS=str(output))
            result = subprocess.run(['sh', str(module / 'numeric.sh'), 'check'], capture_output=True, text=True, env=env)
            return result, output.read_text().splitlines() if output.exists() else []

    def test_inherited_application_icon_and_explicit_activity_icon_are_checked(self):
        for activity, application in [('0x0', '0x7f080002'), ('0x00000000', '0x7F080002'), ('0x7f080002', '0x7f080099')]:
            with self.subTest(activity=activity, application=application):
                result, args = self.run_check(activity, application)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(args[0], 'check')
                self.assertEqual(args[2:4], ['0x7f080001', '0x7f080002'])
                self.assertEqual(args[-3:], ['12345678', '0x7f010005', '0x7f010004'])

    def test_an_uncovered_activity_icon_or_missing_icons_never_reaches_the_helper(self):
        for activity, application in [('0x7f080099', '0x7f080002'), ('0x0', '0x0')]:
            with self.subTest(activity=activity, application=application):
                result, args = self.run_check(activity, application)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Launcher entry is not covered', result.stdout)
                self.assertEqual(args, [])


if __name__ == '__main__':
    unittest.main()
