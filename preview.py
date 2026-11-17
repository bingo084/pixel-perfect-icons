#!/usr/bin/env python3
"""Render APK bitmap fallbacks beside the upstream two-layer artwork."""

import argparse
import html
import json
from pathlib import Path
import re
import subprocess
from cleanicons.artwork import bitmap_background, bitmap_source, foreground_scale

ROOT = Path(__file__).resolve().parent
FONT = subprocess.check_output(["fc-match", "-f", "%{file}", "sans-serif"], text=True).strip()


def run(*args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])


def compose_layers(background, foreground, output, scale=1):
    scale = foreground_scale({"foreground_scale": scale})
    side = max(1, round(432 * scale))
    run("magick", background, "-resize", "432x432!", "(", foreground,
        "-resize", f"{side}x{side}!", "-gravity", "center", "-background", "none", "-extent", "432x432",
        ")", "-compose", "over", "-composite", output)


def circle(source, output, adaptive=False, background=None):
    args = ["magick", str(source)]
    if background:
        args += ["-background", background, "-alpha", "remove", "-alpha", "off"]
    if adaptive:
        args += ["-resize", "432x432!", "-gravity", "center", "-crop", "288x288+0+0", "+repage"]
    args += ["-resize", "160x160!", "-alpha", "on", "(", "-size", "160x160", "xc:black",
             "-fill", "white", "-draw", "circle 80,80 80,0", "-alpha", "off", ")", "-compose", "CopyOpacity",
             "-composite", str(output)]
    run(*args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected", action="store_true")
    args = parser.parse_args()
    data = json.loads((ROOT / ".cache/inventory.json").read_text())
    apps = data["apps"]
    targets = {}
    if args.selected:
        selection = json.loads((ROOT / "selection.json").read_text())
        by_package = {a["package"]: a for a in apps}
        apps = [by_package[p] for p in selection]
        targets = {a["package"]: a for a in json.loads((ROOT / "targets.json").read_text())["apps"]}
    out = ROOT / ("build/preview-selected" if args.selected else "build/preview")
    out.mkdir(parents=True, exist_ok=True)
    tiles, cards = [], []
    for app in apps:
        package = app["package"]
        target = targets.get(package, app)
        upstream = ROOT / ".cache/upstream" / package
        merged, clean = out / (package + ".merged.png"), out / (package + ".clean.png")
        if bitmap := bitmap_source(ROOT, target):
            circle(bitmap, clean, background=bitmap_background(target))
        else:
            compose_layers(upstream / "0.png", upstream / "1.png", merged, foreground_scale(target))
            circle(merged, clean, adaptive=True)
        selected_ids = {r["id"] for r in target["roots"] + target.get("seed_roots", [])}
        bitmaps = [(r, v) for r in app["roots"] if r["id"] in selected_ids
                   for v in r["variants"] if not v["file"].endswith(".xml")]
        original = out / (package + ".original.png")
        if bitmaps:
            primary = app.get("primary_icon_id", app["roots"][0]["id"])
            root, variant = max(bitmaps, key=lambda rv: (rv[0]["id"] == primary, len(rv[1]["config"])))
            circle(ROOT / variant["file"], original)
        else:
            run("magick", "-size", "160x160", "xc:#e6e8ef", "-font", FONT, "-pointsize", "16",
                "-fill", "#444444", "-gravity", "center", "-annotate", "+0+0",
                "待提取\n安装时读取" if target.get("original_preview") else "XML / adaptive\nsee inventory", original)
        tile = out / (package + ".tile.png")
        run("magick", "(", original, "-background", "#f4f5f7", "-gravity", "center", "-extent", "190x188", ")",
            "(", clean, "-background", "#f4f5f7", "-gravity", "center", "-extent", "190x188", ")", "+append", "+repage",
            "-font", FONT, "-pointsize", "16", "-fill", "#1f2937", "-background", "#f4f5f7",
            "-gravity", "south", "-splice", "0x65", "-annotate", "+0+40", app["label"],
            "-pointsize", "11", "-annotate", "+0+23", package,
            "-annotate", "+0+6", "APK original            replacement", tile)
        tiles.append(tile)
        cards.append(f'<article><h2>{html.escape(app["label"])}</h2><p>{html.escape(package)}</p>'
                     f'<img src="{package}.original.png" alt="APK bitmap fallback">'
                     f'<img src="{package}.clean.png" alt="Replacement icon preview">'
                     '<p>左：APK 位图回退资源；右：替换图标的圆形预览。不是当前桌面截图。</p></article>')
    page_size = 18 if args.selected else 12
    for i in range(0, len(tiles), page_size):
        run("magick", "montage", *tiles[i:i + page_size], "-tile", "3x", "-geometry", "+8+8", "-background", "white",
            out / f"sheet-{i // page_size + 1}.png")
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>彩色图标对照</title>'
        '<style>body{font:15px system-ui;background:#f4f5f7;color:#202834;margin:32px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:20px}'
        'article{background:white;border-radius:14px;padding:20px}h2{font-size:18px}p{font-size:12px;color:#657080}'
        'img{width:160px;height:160px;margin:6px}</style><h1>彩色图标候选对照</h1>'
        '<p>这里只展示素材，不代表已安装或已经生效。最终启用清单另行记录。</p><main>' + ''.join(cards) + '</main>')
    print(f"Rendered {len(tiles)} comparisons in {out}")


if __name__ == "__main__":
    main()
