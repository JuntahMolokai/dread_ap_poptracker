"""Map calibration helper.

Default calibration needs no input: Randovania's region JSON carries the image
margins its own data editor uses (see dread_data._default_transform), and they
fit the (fetched, gen/map_edits.json-edited) region maps directly. This tool is for checking that, and for
overriding a map if a different image is ever dropped in.

  python gen/calibrate.py                 render overlays for every map
  python gen/calibrate.py --region Elun   one map
  python gen/calibrate.py --pair Elun "Bridge Gate/Dock to Purple Drapes" 912 412 \
                          --pair Elun "Transport to Ghavoran/Start Point 1" 430 420
        solve a two-point override (room/node name -> pixel you clicked in an
        image editor) and write it to gen/calibration.json

Overlays go to gen/build/overlays/<Region>.png: room polygons (red), pickups
(green), doors (yellow), transports (cyan), goal (magenta). Re-run
build_pack.py after changing calibration.json.

calibration.json format (per region, all optional):
  {"Elun": {"pairs": [{"world": [x, y], "pixel": [px, py]}, {...}],
            "margins": {"map_min_x": 98, "map_max_x": 147, ...},
            "nudge": [dx, dy]}}
"""
from __future__ import annotations

import argparse
import json
import sys

from PIL import Image, ImageDraw

import dread_data as dd

COLORS = {"pickup": (0, 255, 0), "door": (255, 220, 0), "transport": (0, 220, 255),
          "goal": (255, 0, 255)}


def classify(name: str) -> str:
    if name.startswith("Door "):
        return "door"
    if name.startswith("Transport:"):
        return "transport"
    if name.startswith("Goal"):
        return "goal"
    return "pickup"


def render(data: dd.DreadData, region: str) -> str:
    im = Image.open(dd.MAPS_SRC / f"{region}.png").convert("RGB")
    dr = ImageDraw.Draw(im)
    t = data.transforms[region]
    for area in data.areas[region]["areas"].values():
        poly = area["extra"].get("polygon")
        if poly:
            dr.polygon([t(p[0], p[1]) for p in poly], outline=(255, 0, 0))
    loc_file = dd.PACK_DIR / "locations" / f"{region}.json"
    if loc_file.exists():
        for top in json.loads(loc_file.read_text(encoding="utf-8")):
            for child in top.get("children", []):
                kind = classify(child["name"])
                for ml in child.get("map_locations", []):
                    x, y = ml["x"], ml["y"]
                    r = 7 if kind == "pickup" else 5
                    dr.ellipse([x - r, y - r, x + r, y + r], outline=COLORS[kind], width=2)
    out = dd.BUILD_DIR / "overlays" / f"{region}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return str(out)


def render_combined() -> str:
    """Overlay for the combined world map: region outlines + every pin."""
    import combined
    layout = combined.CombinedLayout(combined.load_layout(), dd.REGIONS)
    im = Image.open(dd.PACK_DIR / "images" / "maps" / f"{combined.MAP_NAME}.png").convert("RGB")
    dr = ImageDraw.Draw(im)
    for region in dd.REGIONS:
        with Image.open(dd.MAPS_SRC / f"{region}.png") as src:
            w, h = src.size
        x0, y0 = layout.to_combined(region, 0, 0)
        x1, y1 = layout.to_combined(region, w, h)
        dr.rectangle([x0, y0, x1, y1], outline=(255, 0, 0))
        dr.text((x0 + 4, y0 + 4), region, fill=(255, 80, 80))
    for region in dd.REGIONS:
        loc_file = dd.PACK_DIR / "locations" / f"{region}.json"
        for top in json.loads(loc_file.read_text(encoding="utf-8")):
            for child in top.get("children", []):
                for ml in child.get("map_locations", []):
                    if ml["map"] != combined.MAP_NAME:
                        continue
                    x, y = ml["x"], ml["y"]
                    dr.ellipse([x - 5, y - 5, x + 5, y + 5],
                               outline=COLORS[classify(child["name"])], width=2)
    out = dd.BUILD_DIR / "overlays" / f"{combined.MAP_NAME}.png"
    im.save(out)
    return str(out)


def node_world(data: dd.DreadData, region: str, ref: str) -> tuple[float, float]:
    area, _, node = ref.partition("/")
    if node:
        return data.node_world_xy((region, area, node))
    tb = data.areas[region]["areas"][area]["extra"]["total_boundings"]
    return (tb["x1"] + tb["x2"]) / 2, (tb["y1"] + tb["y2"]) / 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", choices=dd.REGIONS)
    ap.add_argument("--pair", nargs=4, action="append",
                    metavar=("REGION", "ROOM[/NODE]", "PX", "PY"))
    args = ap.parse_args(argv)

    data = dd.load()
    if args.pair:
        calib = dd.load_calibration()
        by_region: dict[str, list] = {}
        for region, ref, px, py in args.pair:
            by_region.setdefault(region, []).append(
                {"world": list(node_world(data, region, ref)),
                 "pixel": [float(px), float(py)]})
        for region, pairs in by_region.items():
            if len(pairs) != 2:
                print(f"{region}: need exactly two --pair entries", file=sys.stderr)
                return 2
            calib.setdefault(region, {})["pairs"] = pairs
        (dd.GEN_DIR / "calibration.json").write_text(json.dumps(calib, indent=2))
        print("wrote gen/calibration.json; re-run gen/build_pack.py")
        data.transforms, data.image_sizes = dd.build_transforms(data.areas)

    for region in [args.region] if args.region else dd.REGIONS:
        print(render(data, region))
    if not args.region:
        print(render_combined())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
