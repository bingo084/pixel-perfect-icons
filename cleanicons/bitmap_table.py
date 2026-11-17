"""Read explicitly selected legacy bitmap resources when AAPT2 cannot dump a table.

Only direct bitmap strings with density/version qualifiers are supported. Resource
names are read from the real type/key pools and checked for duplicate IDs.
Layout: AOSP libs/androidfw/include/androidfw/ResourceTypes.h.
"""

import re
import struct

from cleanicons.arsc import _chunks


class StringPool:
    def __init__(self, data, position, end):
        kind, self.header, size, self.count, styles, self.flags, start, style_start = struct.unpack_from('<HHIIIIII', data, position)
        if (kind != 1 or self.header < 28 or size < self.header or position + size > end or
                self.header + (self.count + styles) * 4 > start or start > size or
                (style_start and not start <= style_start <= size)):
            raise ValueError('Invalid resource string pool')
        self.data, self.position = data, position
        self.start, self.end = position + start, position + (style_start or size)
        self.cache = {}

    def __getitem__(self, index):
        if index in self.cache:
            return self.cache[index]
        if not 0 <= index < self.count:
            raise ValueError('String index out of bounds')
        offset = self.start + struct.unpack_from('<I', self.data, self.position + self.header + index * 4)[0]
        if not self.start <= offset < self.end:
            raise ValueError('String offset out of bounds')

        def length(width):
            nonlocal offset
            if offset + width > self.end:
                raise ValueError('Truncated string length')
            value = int.from_bytes(self.data[offset:offset + width], 'little')
            offset += width
            mask = 1 << (width * 8 - 1)
            if value & mask:
                if offset + width > self.end:
                    raise ValueError('Truncated extended string length')
                value = ((value & (mask - 1)) << (width * 8)) | int.from_bytes(self.data[offset:offset + width], 'little')
                offset += width
            return value

        width = 1 if self.flags & 0x100 else 2
        units = length(width)
        count = length(1) if width == 1 else units * 2
        if offset + count + width > self.end or any(self.data[offset + count:offset + count + width]):
            raise ValueError('Truncated or unterminated resource string')
        value = self.data[offset:offset + count].decode('utf8' if width == 1 else 'utf-16-le')
        self.cache[index] = value
        return value


def entries(data, pos, header, size):
    flags = data[pos + 9]
    count, start = struct.unpack_from('<II', data, pos + 12)
    width = 2 if flags == 2 else 4
    if flags not in (0, 1, 2) or start < header + count * width or start > size:
        raise ValueError('Invalid bitmap resource offsets')
    for i in range(count):
        if flags == 1:
            index, offset = struct.unpack_from('<HH', data, pos + header + i * 4)
            offset *= 4
        else:
            index = i
            offset = int.from_bytes(data[pos + header + i * width:pos + header + (i + 1) * width], 'little')
            if offset == (0xffff if width == 2 else 0xffffffff):
                continue
            if width == 2:
                offset *= 4
        entry = pos + start + offset
        if entry < pos + start or entry + 8 > pos + size:
            raise ValueError('Bitmap resource entry out of bounds')
        yield index, entry


def configuration(data, pos, header):
    size = struct.unpack_from('<I', data, pos + 20)[0]
    if size < 28 or size > header - 20:
        raise ValueError('Invalid bitmap configuration size')
    raw = bytearray(data[pos + 20:pos + 20 + size])
    density, sdk = struct.unpack_from('<H', raw, 14)[0], struct.unpack_from('<H', raw, 24)[0]
    raw[14:16] = raw[24:26] = b'\0\0'
    if any(raw[4:]):
        raise ValueError('Only density and version bitmap configurations are supported')
    densities = {0: '', 120: 'ldpi', 160: 'mdpi', 213: 'tvdpi', 240: 'hdpi', 320: 'xhdpi', 480: 'xxhdpi', 640: 'xxxhdpi', 0xfffe: 'anydpi', 0xffff: 'nodpi'}
    if density not in densities:
        raise ValueError('Unsupported bitmap density')
    return '-'.join(filter(None, [densities[density], f'v{sdk}' if sdk else '']))


def bitmap_resource_table(data, resources):
    """Return resource_table-compatible records for exact manifest resource IDs."""
    try:
        wanted = {int(r.removeprefix('@'), 16) for r in resources if re.fullmatch(r'@0x[0-9a-fA-F]{8}', r)}
        if len(wanted) != len(resources):
            raise ValueError('Expected unique numeric bitmap resource IDs')
        kind, header, total = struct.unpack_from('<HHI', data)
        if kind != 2 or header < 12 or total != len(data):
            raise ValueError('Invalid bitmap resource table')
        chunks = list(_chunks(data, header, total))
        pools = [p for p, kind, _, _ in chunks if kind == 1]
        if len(pools) != 1:
            raise ValueError('Expected one value string pool')
        strings = StringPool(data, pools[0], total)
        result, owners = {}, {}
        for package, kind, package_header, size in chunks:
            if kind != 0x200:
                continue
            if package_header < 284:
                raise ValueError('Invalid bitmap package header')
            pid = struct.unpack_from('<I', data, package + 8)[0]
            package_wanted = {r for r in wanted if r >> 24 == pid}
            if not package_wanted:
                continue
            type_offset = struct.unpack_from('<I', data, package + 284)[0] if package_header >= 288 else 0
            type_pool, key_pool = struct.unpack_from('<I', data, package + 268)[0], struct.unpack_from('<I', data, package + 276)[0]
            if not package_header <= type_pool < size or not package_header <= key_pool < size:
                raise ValueError('Invalid package string pool offset')
            types = StringPool(data, package + type_pool, package + size)
            keys = StringPool(data, package + key_pool, package + size)
            for pos, kind, type_header, type_size in _chunks(data, package + package_header, package + size):
                if kind != 0x201:
                    continue
                if type_header < 48:
                    raise ValueError('Invalid bitmap type header')
                tid = data[pos + 8] + type_offset
                if not any((rid >> 16) & 0xff == tid for rid in package_wanted):
                    continue
                type_name = types[data[pos + 8] - 1]
                if type_name not in ('drawable', 'mipmap'):
                    raise ValueError('Requested resource is not a drawable')
                for index, entry in entries(data, pos, type_header, type_size):
                    entry_size, flags, key = struct.unpack_from('<HHI', data, entry)
                    if flags & 8:
                        raise ValueError('Compact bitmap entries require separate review')
                    name = type_name + '/' + keys[key]
                    rid = (pid << 24) | (tid << 16) | index
                    owners.setdefault(name, set()).add(rid)
                    if rid not in wanted:
                        continue
                    if flags & 1 or entry_size < 8 or entry + entry_size + 8 > pos + type_size:
                        raise ValueError('Requested bitmap is not a valid scalar')
                    value_size, _, value_type, value = struct.unpack_from('<HBBI', data, entry + entry_size)
                    if value_size != 8 or value_type != 3:
                        raise ValueError('Requested bitmap must be a direct file string')
                    path = strings[value]
                    if not re.fullmatch(r'(?:res|r)/[A-Za-z0-9_./-]+\.(?:png|webp|jpe?g)', path) or '..' in path.split('/'):
                        raise ValueError('Unsafe or unsupported bitmap path')
                    record = result.setdefault(f'@0x{rid:08x}', {'name': name, 'values': []})
                    if record['name'] != name:
                        raise ValueError('Bitmap resource name differs by configuration')
                    record['values'].append({'config': configuration(data, pos, type_header), 'value': f'(file) {path}'})
        if any(len(owners[r['name']]) != 1 for r in result.values()):
            raise ValueError('Bitmap resource name is ambiguous')
        return result
    except (struct.error, IndexError, UnicodeError) as error:
        raise ValueError('Malformed bitmap resource table') from error
