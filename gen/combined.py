"""Combined world map: every region map scaled and placed on one canvas.

Dread's regions each use their own world coordinates and nothing in the game
data relates them, so the arrangement is a layout choice kept in
gen/combined_layout.json:

  {
    "scale": 0.5,                      default scale for every region
    "margin": 40,                      empty border around the canvas (pixels)
    "regions": {
      "Artaria": {"x": 0, "y": 0},     top-left of the region image on the
      "Cataris": {"x": 1400, "y": 0,   canvas, in canvas pixels (after scaling)
                  "scale": 0.45},      optional per-region scale override
      ...
    }
  }

Each region image's background colour is made transparent before it is
composited, so regions can interlock without their empty rectangles covering
each other. A pin at (px, py) on a region map lands at
(x + px * scale, y + py * scale) on the combined map.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

GEN_DIR = Path(__file__).resolve().parent
LAYOUT_FILE = GEN_DIR / "combined_layout.json"
MAP_NAME = "Combined"
BACKGROUND = (12, 21, 28, 255)        # the region maps' backdrop colour


def load_layout() -> dict:
    return json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))


class CombinedLayout:
    def __init__(self, layout: dict, regions: list[str]):
        self.default_scale = float(layout.get("scale", 0.5))
        self.margin = int(layout.get("margin", 40))
        self.placement = {}
        for r in regions:
            spec = layout["regions"][r]
            self.placement[r] = (float(spec["x"]), float(spec["y"]),
                                 float(spec.get("scale", self.default_scale)))

    def to_combined(self, region: str, x: float, y: float) -> tuple[float, float]:
        ox, oy, s = self.placement[region]
        return self.margin + ox + x * s, self.margin + oy + y * s

    def scale(self, region: str) -> float:
        return self.placement[region][2]

    def render(self, maps_dir: Path, out_path: Path) -> tuple[int, int]:
        placed = []
        w = h = 0
        for region, (ox, oy, s) in self.placement.items():
            im = Image.open(maps_dir / f"{region}.png").convert("RGBA")
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
            px = im.load()
            # Knock out the backdrop (resampling blurs edges, so allow a little
            # tolerance around the exact colour).
            for yy in range(im.height):
                for xx in range(im.width):
                    r, g, b, a = px[xx, yy]
                    if (abs(r - BACKGROUND[0]) + abs(g - BACKGROUND[1])
                            + abs(b - BACKGROUND[2])) < 24:
                        px[xx, yy] = (r, g, b, 0)
            placed.append((im, round(self.margin + ox), round(self.margin + oy)))
            w = max(w, round(self.margin + ox) + im.width)
            h = max(h, round(self.margin + oy) + im.height)
        canvas = Image.new("RGBA", (w + self.margin, h + self.margin), BACKGROUND)
        for im, x, y in placed:
            canvas.alpha_composite(im, (x, y))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(out_path, optimize=True)
        return canvas.size
