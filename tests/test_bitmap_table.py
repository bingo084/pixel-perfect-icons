from pathlib import Path
import struct
import unittest
import zipfile

from cleanicons.bitmap_table import bitmap_resource_table

ROOT = Path(__file__).resolve().parents[1]


def pool(strings, utf8=True):
    offsets, body = [], b''
    for text in strings:
        offsets.append(len(body))
        if utf8:
            raw = text.encode()
            def length(n):
                return bytes([(n >> 8) | 0x80, n & 255]) if n >= 128 else bytes([n])
            body += length(len(text)) + length(len(raw)) + raw + b'\0'
        else:
            body += struct.pack('<H', len(text)) + text.encode('utf-16-le') + b'\0\0'
    body += b'\0' * (-len(body) % 4)
    start = 28 + len(offsets) * 4
    return struct.pack('<HH6I', 1, 28, start + len(body), len(strings), 0, 0x100 if utf8 else 0, start, 0) + b''.join(struct.pack('<I', n) for n in offsets) + body


def table(*, flags=0, utf8=True, path='r/b/icon.png', density=480, sdk=0, locale=False, duplicate=False, value_type=3):
    types = pool(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'drawable'], utf8)
    keys = pool(['icon'], utf8)
    values = pool([path], utf8)
    config = bytearray(64)
    struct.pack_into('<I', config, 0, 64)
    struct.pack_into('<H', config, 14, density)
    struct.pack_into('<H', config, 24, sdk)
    if locale:
        config[8:10] = b'en'
    entry = struct.pack('<HHI', 8, 0, 0) + struct.pack('<HBBI', 8, 0, value_type, 0)
    entries = entry * (2 if duplicate else 1)
    if flags == 1:
        count, offsets = 1, struct.pack('<HH', 0, 0)
    elif flags == 2:
        count, offsets = 1, struct.pack('<HH', 0, 0xffff)
    else:
        count = 2 if duplicate else 1
        offsets = struct.pack('<II', 0, 16) if duplicate else struct.pack('<I', 0)
    start = 84 + len(offsets)
    chunk = struct.pack('<HHIBBHII', 0x201, 84, start + len(entries), 8, flags, 0, count, start) + config + offsets + entries
    package = bytearray(288)
    struct.pack_into('<HHII', package, 0, 0x200, 288, 288 + len(types) + len(keys) + len(chunk), 0x7f)
    struct.pack_into('<I', package, 268, 288)
    struct.pack_into('<I', package, 276, 288 + len(types))
    body = values + package + types + keys + chunk
    return struct.pack('<HHII', 2, 12, 12 + len(body), 1) + body


class BitmapTableTests(unittest.TestCase):
    def test_exact_ids_names_bitmap_paths_and_configurations_are_read(self):
        for flags in [0, 1, 2]:
            for utf8 in [True, False]:
                with self.subTest(flags=flags, utf8=utf8):
                    result = bitmap_resource_table(table(flags=flags, utf8=utf8, sdk=26), ['@0x7f080000'])
                    self.assertEqual(result, {'@0x7f080000': {'name': 'drawable/icon', 'values': [{'config': 'xxhdpi-v26', 'value': '(file) r/b/icon.png'}]}})

    def test_long_utf8_strings_and_missing_ids_are_handled(self):
        path = 'r/' + 'a' * 150 + '.png'
        self.assertEqual(bitmap_resource_table(table(path=path), ['@0x7f080000'])['@0x7f080000']['values'][0]['value'], '(file) ' + path)
        self.assertEqual(bitmap_resource_table(table(), ['@0x7f080001']), {})

    def test_ambiguous_names_aliases_unsafe_paths_and_unsupported_qualifiers_fail(self):
        for options in [dict(duplicate=True), dict(value_type=1), dict(path='r/../private.png'), dict(path='r/icon.xml'), dict(locale=True), dict(density=999)]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                bitmap_resource_table(table(**options), ['@0x7f080000'])

    def test_bad_tables_offsets_and_string_bounds_fail(self):
        original = table()
        damaged = [original[:8], original[:-1], b'not a table']
        for offset, value in [(12 + 8, 0x7fffffff), (12 + 28, 0xffffffff)]:
            raw = bytearray(original)
            struct.pack_into('<I', raw, offset, value)
            damaged.append(bytes(raw))
        for raw in damaged:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                bitmap_resource_table(raw, ['@0x7f080000'])

    def test_recorded_qq_ordinary_icon_is_one_unique_legacy_bitmap(self):
        apk = ROOT / '.cache/device/com.tencent.mobileqq/base.apk'
        if not apk.exists():
            self.skipTest('Requires the recorded QQ resource table')
        with zipfile.ZipFile(apk) as archive:
            result = bitmap_resource_table(archive.read('resources.arsc'), ['@0x7f081e92'])
        self.assertEqual(result, {'@0x7f081e92': {'name': 'drawable/icon', 'values': [{'config': 'xxhdpi', 'value': '(file) r/b/icon.png'}]}})


if __name__ == '__main__':
    unittest.main()
