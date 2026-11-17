import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import zipfile

from cleanicons.artwork import foreground_scale
from cleanicons.resources import dump, xml_tree
from preview import compose_layers, run

ROOT = Path(__file__).resolve().parents[1]


class ForegroundScaleTests(unittest.TestCase):
    def test_default_and_invalid_scales(self):
        self.assertEqual(foreground_scale({}), 1)
        for value in [0, -1, 1.1, True, None, '0.9', float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                foreground_scale({'foreground_scale': value})
        with self.assertRaises(ValueError):
            foreground_scale({'foreground_scale': .9, 'artwork': {'kind': 'apk-bitmap'}})

    def test_preview_shrinks_only_the_foreground_and_keeps_it_centered(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            background, foreground = folder / 'background.png', folder / 'foreground.png'
            run('magick', '-size', '432x432', 'xc:blue', background)
            run('magick', '-size', '432x432', 'xc:none', '-fill', 'red', '-draw', 'rectangle 108,108 323,323', foreground)
            widths = []
            for scale in [1, .5]:
                output = folder / f'{scale}.png'
                compose_layers(background, foreground, output, scale)
                corner = subprocess.check_output(['magick', str(output), '-format', '%[pixel:p{0,0}]', 'info:'], text=True)
                self.assertIn('0,0,255', corner)
                geometry = subprocess.check_output(['magick', str(output), str(background), '-compose', 'difference', '-composite',
                                                    '-alpha', 'off', '-threshold', '1%', '-format', '%@', 'info:'], text=True)
                width, height, x, y = map(int, re.fullmatch(r'(\d+)x(\d+)\+(\d+)\+(\d+)', geometry).groups())
                self.assertEqual(width, height)
                self.assertAlmostEqual(x + width / 2, 216, delta=1)
                self.assertAlmostEqual(y + height / 2, 216, delta=1)
                widths.append(width)
            self.assertAlmostEqual(widths[1] / widths[0], .5, delta=.02)

    def test_scaled_overlays_keep_raw_layers_and_background_unchanged(self):
        apps = {a['package']: a for a in json.loads((ROOT / 'targets.json').read_text())['apps']}
        for package in ['com.hpbr.bosszhipin', 'com.taobao.idlefish']:
            with self.subTest(package=package):
                apk = ROOT / 'build/overlays' / package / 'overlay.apk'
                if not apk.exists():
                    self.skipTest('Build the overlays first')
                self.assertLess(foreground_scale(apps[package]), 1)
                xml = xml_tree(dump(ROOT / '.cache/toolchain/aapt2', apk, 'xmltree', 'res/drawable/clean_foreground_layer.xml'))
                self.assertIn('inset', {n.tag for n in xml.walk()})
                background = xml_tree(dump(ROOT / '.cache/toolchain/aapt2', apk, 'xmltree', 'res/drawable/clean_background_layer.xml'))
                self.assertNotIn('inset', {n.tag for n in background.walk()})
                with zipfile.ZipFile(apk) as archive:
                    for number, layer in [(0, 'background'), (1, 'foreground')]:
                        name = next(p for p in archive.namelist() if p.endswith('/clean_' + layer + '.png'))
                        self.assertEqual(archive.read(name), (ROOT / '.cache/upstream' / package / f'{number}.png').read_bytes())


if __name__ == '__main__':
    unittest.main()
