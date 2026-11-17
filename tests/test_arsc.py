from pathlib import Path
import struct
import unittest
import zipfile

from cleanicons.arsc import reference_id
from cleanicons.resources import resolved_values, resource_table

ROOT = Path(__file__).resolve().parents[1]


def table_for(references, flags=0, index=0):
    chunks = []
    for reference in references:
        if flags == 1:
            offsets = struct.pack("<HH", index, 0)
            count = 1
        else:
            width, empty = (2, 0xffff) if flags == 2 else (4, 0xffffffff)
            count = index + 1
            offsets = b"".join(struct.pack("<H" if width == 2 else "<I", empty if i != index else 0) for i in range(count))
            offsets += b"\0" * (-len(offsets) % 4)
        entry = struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 1, reference)
        size = 24 + len(offsets) + len(entry)
        chunks.append(struct.pack("<HHIBBHIII", 0x0201, 24, size, 7, flags, 0, count, 24 + len(offsets), 4) + offsets + entry)
    package = bytearray(288)
    struct.pack_into("<HHII", package, 0, 0x0200, 288, 288 + sum(map(len, chunks)), 0x7f)
    body = bytes(package) + b"".join(chunks)
    return struct.pack("<HHII", 2, 12, 12 + len(body), 1) + body


class BinaryReferenceTests(unittest.TestCase):
    def test_standard_sparse_and_16_bit_offsets_preserve_numeric_ids(self):
        for flags, index in [(0, 0), (1, 5), (2, 2)]:
            with self.subTest(flags=flags):
                resource = f"@0x{0x7f070000 + index:08x}"
                self.assertEqual(reference_id(table_for([0x7f0d0009], flags, index), resource), "@0x7f0d0009")

    def test_configuration_dependent_references_fail_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, "configuration"):
            reference_id(table_for([0x7f0d0009, 0x7f0d000a]), "@0x7f070000")

    def test_truncated_tables_and_invalid_offsets_fail(self):
        original = table_for([0x7f0d0009])
        for invalid in [original[:8], original[:-1], b"not a table"]:
            with self.subTest(length=len(invalid)):
                with self.assertRaises(ValueError):
                    reference_id(invalid, "@0x7f070000")

    def test_duplicate_names_require_an_exact_binary_reference(self):
        table = resource_table('''resource 0x7f070000 drawable/logo
  () @mipmap/pdd
resource 0x7f0d0008 mipmap/pdd
  (xxhdpi) "r/wrong.png"
resource 0x7f0d0009 mipmap/pdd
  (xxhdpi) "r/correct.png"
''')
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            list(resolved_values(table, "@0x7f070000"))
        values = list(resolved_values(table, "@0x7f070000", reference_lookup=lambda rid: reference_id(table_for([0x7f0d0009]), rid)))
        self.assertEqual(values[0]["value"], '"r/correct.png"')

    def test_recorded_pinduoduo_alias_resolves_to_the_actual_id(self):
        path = ROOT / ".cache/device/com.xunmeng.pinduoduo/base.apk"
        if not path.exists():
            self.skipTest("Requires the recorded device APK metadata")
        with zipfile.ZipFile(path) as archive:
            data = archive.read("resources.arsc")
        self.assertEqual(reference_id(data, "@0x7f070570"), "@0x7f0d0009")


if __name__ == "__main__":
    unittest.main()
