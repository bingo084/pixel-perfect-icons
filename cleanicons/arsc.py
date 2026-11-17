"""Read numeric aliases without losing their IDs to AAPT2's name formatting.

Layout: AOSP libs/androidfw/include/androidfw/ResourceTypes.h. Only scalar,
configuration-independent reference values are accepted; no name guessing.
"""

from pathlib import Path
import re
import struct
import zipfile


def _chunks(data, start, end):
    while start < end:
        if start + 8 > end:
            raise ValueError("Truncated Android resource chunk")
        kind, header, size = struct.unpack_from("<HHI", data, start)
        if header < 8 or size < header or start + size > end:
            raise ValueError("Invalid Android resource chunk")
        yield start, kind, header, size
        start += size


def reference_id(data, resource):
    """Return the exact referenced ID, or None for a non-reference/missing entry."""
    if isinstance(resource, str):
        if not re.fullmatch(r"@0x[0-9a-fA-F]{8}", resource):
            raise ValueError("Expected a numeric resource ID")
        resource = int(resource[1:], 16)
    try:
        kind, table_header, total = struct.unpack_from("<HHI", data)
        if kind != 0x0002 or table_header < 12 or total < table_header or total > len(data):
            raise ValueError("Not an Android resource table")
        values = []
        for package, kind, header, size in _chunks(data, table_header, total):
            if kind != 0x0200:
                continue
            if header < 284:
                raise ValueError("Invalid resource package header")
            if struct.unpack_from("<I", data, package + 8)[0] != resource >> 24:
                continue
            type_offset = struct.unpack_from("<I", data, package + 284)[0] if header >= 288 else 0
            for pos, kind, header, size in _chunks(data, package + header, package + size):
                if kind != 0x0201:
                    continue
                if header < 24:
                    raise ValueError("Invalid resource type header")
                if data[pos + 8] + type_offset != (resource >> 16) & 0xff:
                    continue
                flags = data[pos + 9]
                count, entries = struct.unpack_from("<II", data, pos + 12)
                if entries < header or entries > size:
                    raise ValueError("Invalid resource entry region")
                index = resource & 0xffff
                if flags == 1:  # ResTable_sparseTypeEntry: index and offset / 4.
                    if header + count * 4 > entries:
                        raise ValueError("Invalid sparse resource offsets")
                    offsets = [struct.unpack_from("<HH", data, pos + header + i * 4) for i in range(count)]
                    offset = next((off * 4 for idx, off in offsets if idx == index), None)
                elif flags in (0, 2):
                    width = 2 if flags == 2 else 4
                    if header + count * width > entries:
                        raise ValueError("Invalid resource offsets")
                    if index >= count:
                        continue
                    offset = struct.unpack_from("<H" if width == 2 else "<I", data, pos + header + index * width)[0]
                    if offset == (0xffff if width == 2 else 0xffffffff):
                        offset = None
                    elif width == 2:
                        offset *= 4
                else:
                    raise ValueError("Unsupported resource type flags")
                if offset is None:
                    continue
                entry = pos + entries + offset
                if entry + 8 > pos + size:
                    raise ValueError("Resource entry is out of bounds")
                entry_size, entry_flags = struct.unpack_from("<HH", data, entry)
                if entry_flags & 8:
                    raise ValueError("Compact resource entry requires separate parsing")
                if entry_flags & 1:
                    values.append(None)
                    continue
                if entry_size < 8 or entry + entry_size + 8 > pos + size:
                    raise ValueError("Invalid scalar resource entry")
                value_size, _, value_type, value = struct.unpack_from("<HBBI", data, entry + entry_size)
                if value_size != 8:
                    raise ValueError("Invalid resource value size")
                values.append(value if value_type == 1 else None)
        references = {v for v in values if v is not None}
        if len(references) > 1 or (references and None in values):
            raise ValueError("Resource reference varies by configuration")
        return f"@0x{next(iter(references)):08x}" if references else None
    except (struct.error, IndexError) as error:
        raise ValueError("Truncated Android resource table") from error


def alias_reader(apks):
    """Lazy lookup suitable for resolved_values(reference_lookup=...)."""
    paths = [Path(p) for p in apks]
    blobs = {}

    def lookup(resource):
        references = set()
        for path in paths:
            if path not in blobs:
                with zipfile.ZipFile(path) as archive:
                    blobs[path] = archive.read("resources.arsc")
            target = reference_id(blobs[path], resource)
            if target:
                references.add(target)
        if len(references) > 1:
            raise ValueError("Resource alias differs between APKs: " + resource)
        return next(iter(references)) if references else None

    return lookup
