#!/usr/bin/env python3
"""Create a clearly labeled local WebUI preview with a fake KSU bridge. No ADB."""

import base64
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent


def main():
    source = ROOT / "build/module/webroot"
    destination = ROOT / "build/ui-preview"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    inventory = json.loads((ROOT / ".cache/inventory.json").read_text())
    catalog = json.loads((destination / "catalog.json").read_text())
    managed = {app["package"] for app in catalog["apps"]}
    labels = {"com.tencent.wemeet.app": "腾讯会议", "com.xiaomi.smarthome": "米家", "com.xiaomi.router": "小米 WiFi"}
    infos, icons = [], {}
    for index, app in enumerate(inventory["apps"]):
        package = app["package"]
        infos.append({"packageName": package, "appLabel": labels.get(package, app["label"]), "userId": 0, "uid": 10000 + index})
        candidates = [ROOT / "build/preview-selected" / (package + ".original.png"), ROOT / "build/preview" / (package + ".original.png")]
        original = next((p for p in candidates if p.exists()), None)
        if original:
            target = "assets/preview-" + package + ".png"
            shutil.copyfile(original, destination / target)
            icons[package] = target
    packages = [info["packageName"] for info in infos]
    snapshot = "PIXEL_CLEAN_ICONS_V1\n" + "\n".join(packages) + "\n__OVERLAY_STATES__\n"
    snapshot += "\n".join(package + "\tactive" for package in packages if package in managed) + "\n"
    fixture = {"infos": infos, "snapshot": snapshot, "icons": icons}
    fixture_json = json.dumps(fixture, ensure_ascii=False).replace("<", "\\u003c")
    script = "const fixture = " + fixture_json + ";\n" + r'''
window.PIXEL_CLEAN_ICONS_PREVIEW = true;
window.PCI_CALLS = [];
window.PCI_TRANSPORTS = [];
window.ksu = {
  exec(command, options, callback) {
    window.PCI_CALLS.push(command);
    window.PCI_TRANSPORTS.push('exec');
    setTimeout(() => {
      if (command.endsWith(' snapshot')) window[callback](0, fixture.snapshot, '');
      else if (command.endsWith(' clear-cache')) {
        if (window.PCI_CLEAR_FAIL) window[callback](1, 'Overlays are not ready.', '');
        else window[callback](0, 'SUCCESS (preview; no operation performed)', '');
      } else window[callback](1, '', 'Unexpected command');
    }, 180);
  },
  spawn(command, args, options, callback) {
    const text = [command, ...JSON.parse(args)].join(' ');
    window.PCI_CALLS.push(text);
    window.PCI_TRANSPORTS.push('spawn');
    if (text.endsWith(' clear-cache') && window.PCI_CLEAR_HOLD) {
      window.PCI_PENDING_CLEAR = callback;
      return;
    }
    setTimeout(() => {
      const child = window[callback];
      if (!child) return;
      if (text.endsWith(' snapshot')) {
        child.stdout.emit('data', fixture.snapshot);
        child.emit('exit', 0);
      } else if (text.endsWith(' clear-cache')) {
        if (window.PCI_CLEAR_FAIL) child.stdout.emit('data', 'Overlays are not ready.');
        else child.stdout.emit('data', 'SUCCESS (preview; no operation performed)');
        child.emit('exit', window.PCI_CLEAR_FAIL ? 1 : 0);
      } else child.emit('exit', 1);
    }, text.endsWith(' clear-cache') ? 600 : 180);
  },
  pm() { return {
    version: () => 1,
    getPackagesInfo: () => JSON.stringify(fixture.infos),
    listPackages: () => JSON.stringify(fixture.infos.map(info => info.packageName)),
  }; },
  getPackagesInfo: () => JSON.stringify(fixture.infos),
};
const iconDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
Object.defineProperty(HTMLImageElement.prototype, 'src', {
  get: iconDescriptor.get,
  set(value) { iconDescriptor.set.call(this, value.startsWith('ksu://icon/') ?
    (fixture.icons[value.slice('ksu://icon/'.length)] || 'assets/missing-preview.png') : value); },
});
'''
    (destination / "fixture.js").write_text(script)
    page = (destination / "index.html").read_text().replace('<script type="module" src="app.js"></script>',
                                                            '<script src="fixture.js"></script>\n  <script type="module" src="app.js"></script>')
    (destination / "index.html").write_text(page)
    images = {"assets/" + p.name: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
              for p in (destination / "assets").glob("*.png")}
    offline_fixture = dict(fixture, icons={pkg: images[src] for pkg, src in icons.items()})
    inline = script.replace(fixture_json, json.dumps(offline_fixture).replace("<", "\\u003c"), 1)
    inline += "\nconst previewImages = " + json.dumps(images) + ";\n"
    inline += "const previewCatalog = " + json.dumps(catalog).replace("<", "\\u003c") + ";\n"
    inline += r'''
window.fetch = async () => ({ ok: true, json: async () => previewCatalog });
const previewDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
Object.defineProperty(HTMLImageElement.prototype, 'src', {
  get: previewDescriptor.get,
  set(value) { previewDescriptor.set.call(this, previewImages[value] || value); },
});
'''
    strip_exports = lambda s: re.sub(r"^\s*export (?=(function|const)\b)", "", s, flags=re.M)
    inline += "\nconst sdk = (() => {\n" + strip_exports((source / "vendor/kernelsu.js").read_text()) + "\nreturn { exec, pm, getPackagesInfo };\n})();\n"
    inline += "const model = (() => {\n" + strip_exports((source / "model.mjs").read_text()) + "\nreturn { parseSnapshot, makeApps, filterApps, cacheError };\n})();\n"
    inline += "const commands = (() => {\n" + strip_exports((source / "commands.mjs").read_text()) + "\nreturn { runModuleCommand };\n})();\n"
    app = re.sub(r"^import[^\n]+\n", "", (source / "app.js").read_text(), flags=re.M)
    inline += "(() => {\nconst { exec, pm, getPackagesInfo } = sdk;\nconst { parseSnapshot, makeApps, filterApps, cacheError } = model;\nconst { runModuleCommand } = commands;\n" + app + "\n})();\n"
    standalone = (source / "index.html").read_text()
    standalone = standalone.replace("script-src 'self'; style-src 'self';", "script-src 'nonce-pixel-preview'; style-src 'nonce-pixel-preview';")
    standalone = standalone.replace('<link rel="stylesheet" href="style.css">', '<style nonce="pixel-preview">' + (source / "style.css").read_text() + '</style>')
    standalone = standalone.replace('<script type="module" src="app.js"></script>', '')
    standalone = standalone.replace('</body>', '<script nonce="pixel-preview">' + inline + '</script>\n</body>')
    output = ROOT / "dist/webui-preview.html"
    output.write_text(standalone)
    print("Offline preview (fake KSU bridge, no phone operations): " + str(output))


if __name__ == "__main__":
    main()
