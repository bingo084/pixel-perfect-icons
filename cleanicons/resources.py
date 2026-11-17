"""Read AAPT2's documented text dumps; never guess resource IDs from names."""

from dataclasses import dataclass, field
import re
import subprocess


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def xml_tree(text):
    root = Node("document")
    stack = [(-1, root)]
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("E: "):
            while stack[-1][0] >= indent:
                stack.pop()
            node = Node(stripped[3:].split()[0])
            stack[-1][1].children.append(node)
            stack.append((indent, node))
        elif stripped.startswith("A: "):
            key, value = stripped[3:].split("=", 1)
            key = key.split("(")[0].rsplit(":", 1)[-1]
            if value.startswith('"'):
                value = value[1:].split('"', 1)[0]
            stack[-1][1].attrs[key] = value
    return root


def launcher_icons(tree):
    app = next(n for n in tree.walk() if n.tag == "application")
    refs = {app.attrs[k] for k in ("icon", "roundIcon") if k in app.attrs}
    components = []
    for node in app.children:
        if node.tag not in ("activity", "activity-alias"):
            continue
        filters = [c for c in node.children if c.tag == "intent-filter"]
        launcher = any(
            any(c.tag == "action" and c.attrs.get("name") == "android.intent.action.MAIN"
                for c in f.children)
            and any(c.tag == "category" and c.attrs.get("name") == "android.intent.category.LAUNCHER"
                    for c in f.children)
            for f in filters
        )
        if launcher:
            components.append(node.attrs.get("name", ""))
            refs.update(node.attrs[k] for k in ("icon", "roundIcon") if k in node.attrs)
    return sorted(r.lower() for r in refs if re.fullmatch(r"@0x[0-9a-fA-F]+", r)), components


def resource_table(text):
    entries = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"\s*resource (0x[0-9a-f]+) ([\w.]+/[\w.$]+)", line)
        if match:
            current = entries.setdefault("@" + match[1], {"name": match[2], "values": []})
        elif current is not None:
            match = re.match(r"\s*\((.*?)\) (.*)", line)
            if match:
                current["values"].append({"config": match[1], "value": match[2]})
    return entries


def file_values(entry):
    for value in entry["values"]:
        match = re.match(r"\(file\) (\S+)", value["value"])
        if match:
            yield value["config"], match[1]
        else:
            # Some resource shrinkers relocate files outside res/; AAPT prints these as strings.
            match = re.fullmatch(r'"([^"\n]+\.(?:png|webp|jpe?g|xml))"', value["value"], re.I)
            if match and "/" in match[1]:
                yield value["config"], match[1]


def resolved_values(table, reference, seen=(), reference_lookup=None):
    """Follow both numeric and named aliases before locating bitmap/XML files."""
    if reference in seen:
        raise ValueError("Cyclic resource alias: " + reference)
    entry = table[reference]
    for value in entry["values"]:
        if list(file_values({"values": [value]})):
            yield value
            continue
        raw = value["value"]
        match = re.search(r"@0x[0-9a-fA-F]+", raw)
        child = match[0].lower() if match else None
        if child is None and raw.startswith("@"):
            name = raw[1:].split(":", 1)[-1]
            matches = [rid for rid, r in table.items() if r["name"] == name]
            if len(matches) == 1:
                child = matches[0]
            elif len(matches) > 1:
                child = reference_lookup(reference) if reference_lookup else None
                if child not in matches:
                    raise ValueError("Ambiguous resource alias needs its numeric ID: " + reference)
        if child in table:
            yield from resolved_values(table, child, (*seen, reference), reference_lookup)


def dump(aapt2, apk, kind, file=None):
    args = [str(aapt2), "dump", kind]
    if file:
        args += ["--file", file]
    result = subprocess.run([*args, str(apk)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result.stdout
