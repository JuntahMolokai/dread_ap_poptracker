"""Art that belongs to other projects, fetched at build time instead of being
stored in this repo.

  Randovania (GPL-3.0), pinned to RANDOVANIA_COMMIT:
    randovania/games/dread/assets/maps/<Region>.png             region maps
    randovania/data/gui_assets/tracker/game-images/dread/*.png  item icons

Files are downloaded from GitHub once into gen/build/cache/randovania/<commit>/
(or copied from a local checkout when RANDOVANIA_DIR is set). The pack's own
changes to the maps are not stored as images either: gen/map_edits.json
describes them as operations, re-applied to the fetched originals into
gen/build/maps/, which is what the rest of the generator reads.

map_edits.json operations (per region, applied in order):
  {"op": "move_color", "box": [x0, y0, x1, y1], "by": [dx, dy],
   "color": [r, g, b], "background": [r, g, b]}
      move every pixel of `color` inside the inclusive box by (dx, dy),
      filling the vacated pixels with `background` (e.g. relocating a label)
  {"op": "border", "width": n, "color": [r, g, b]}
      paint an n-pixel frame around the image (e.g. removing an outline)
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

GEN_DIR = Path(__file__).resolve().parent
BUILD_DIR = GEN_DIR / "build"
EDITS_FILE = GEN_DIR / "map_edits.json"

RANDOVANIA_REPO = "randovania/randovania"
RANDOVANIA_COMMIT = "078b3c64681891579f9eae0edec2280cb85bf4c6"
RDV_MAPS = "randovania/games/dread/assets/maps"
RDV_ICONS = "randovania/data/gui_assets/tracker/game-images/dread"

REGIONS = ["Artaria", "Cataris", "Dairon", "Burenia", "Ghavoran",
           "Elun", "Ferenia", "Hanubia", "Itorash"]

CACHE_DIR = BUILD_DIR / "cache" / "randovania" / RANDOVANIA_COMMIT
MAPS_DIR = BUILD_DIR / "maps"            # fetched maps with map_edits applied
ICONS_DIR = CACHE_DIR / RDV_ICONS        # fetched item icons


def _fetch(rel_path: str) -> Path:
    """Return a cached copy of a Randovania file at the pinned commit."""
    dest = CACHE_DIR / rel_path
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = os.environ.get("RANDOVANIA_DIR")
    if local:
        shutil.copyfile(Path(local) / rel_path, dest)
        return dest
    url = (f"https://raw.githubusercontent.com/{RANDOVANIA_REPO}/{RANDOVANIA_COMMIT}/"
           + urllib.parse.quote(rel_path))
    print(f"  fetching {rel_path}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def fetch_icons(names: list[str]) -> Path:
    """Fetch the named item icons (basenames without .png); returns their dir."""
    for n in names:
        _fetch(f"{RDV_ICONS}/{n}.png")
    return ICONS_DIR


def _apply_edits(im: Image.Image, edits: list[dict]) -> Image.Image:
    im = im.convert("RGB")
    px = im.load()
    w, h = im.size
    for e in edits:
        op = e["op"]
        if op == "move_color":
            x0, y0, x1, y1 = e["box"]
            dx, dy = e["by"]
            color, bg = tuple(e["color"]), tuple(e["background"])
            moved = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
                     if px[x, y] == color]
            for x, y in moved:
                px[x, y] = bg
            for x, y in moved:
                px[x + dx, y + dy] = color
        elif op == "border":
            n, color = int(e["width"]), tuple(e["color"])
            for y in range(h):
                for x in range(w):
                    if x < n or y < n or x >= w - n or y >= h - n:
                        px[x, y] = color
        else:
            raise ValueError(f"unknown map edit op {op!r}")
    return im


def prepare_maps() -> Path:
    """Fetch every region map and write the edited versions to MAPS_DIR."""
    edits = json.loads(EDITS_FILE.read_text(encoding="utf-8")) if EDITS_FILE.exists() else {}
    stamp = MAPS_DIR / ".source"
    want = json.dumps({"commit": RANDOVANIA_COMMIT, "edits": edits}, sort_keys=True)
    if stamp.exists() and stamp.read_text(encoding="utf-8") == want and all(
            (MAPS_DIR / f"{r}.png").exists() for r in REGIONS):
        return MAPS_DIR
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    for r in REGIONS:
        src = _fetch(f"{RDV_MAPS}/{r}.png")
        region_edits = [e for e in edits.get(r, []) if isinstance(e, dict)]
        if region_edits:
            with Image.open(src) as im:
                _apply_edits(im, region_edits).save(MAPS_DIR / f"{r}.png", optimize=True)
        else:
            shutil.copyfile(src, MAPS_DIR / f"{r}.png")
    stamp.write_text(want, encoding="utf-8")
    return MAPS_DIR
