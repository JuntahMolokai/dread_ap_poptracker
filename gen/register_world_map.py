"""Build gen/combined_layout.json from a reference world map image.

Each region map is located in the reference by masked template matching
(backdrop and white title text excluded from the mask): a coarse scale sweep at
1/4 size, then a refinement at 1/2 size around the best hit. The resulting
offsets / scales are shifted to the top-left and scaled by --scale (0.5 keeps
the combined image manageable) and written as the combined-map layout.

  python gen/register_world_map.py path/to/reference.png [--scale 0.5]

The reference image is not part of the repo (the current layout was matched
against a fan-made Dread world map poster); any image showing all nine regions
in the same map style works.

Requires: pip install numpy opencv-python-headless
Then re-run gen/build_pack.py (and gen/calibrate.py to check the overlay).
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import external_assets

GEN = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("reference")
ap.add_argument("--scale", type=float, default=0.5)
args = ap.parse_args()
REF = args.reference
MAPS = str(external_assets.prepare_maps())
REGIONS = ["Artaria", "Cataris", "Dairon", "Burenia", "Ghavoran", "Elun", "Ferenia",
           "Hanubia", "Itorash"]
BG = np.array([12, 21, 28])

ref_full = cv2.cvtColor(cv2.imread(REF, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32)


def load_region(name):
    im = cv2.cvtColor(cv2.imread(f"{MAPS}/{name}.png", cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    im = im.astype(np.float32)
    not_bg = np.abs(im - BG).sum(axis=2) > 40
    not_text = ~(im.min(axis=2) > 200)          # white title / labels
    mask = (not_bg & not_text).astype(np.float32)
    return im, mask


def match(ref, tmpl, mask):
    if tmpl.shape[0] >= ref.shape[0] or tmpl.shape[1] >= ref.shape[1]:
        return -1, (0, 0)
    res = cv2.matchTemplate(ref, tmpl, cv2.TM_CCORR_NORMED, mask=np.dstack([mask] * 3))
    res = np.nan_to_num(res, nan=-1, posinf=-1, neginf=-1)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return mx, loc


def resize(a, s, interp=cv2.INTER_AREA):
    return cv2.resize(a, (max(1, round(a.shape[1] * s)), max(1, round(a.shape[0] * s))),
                      interpolation=interp)


out = {}
f1 = 0.25
ref1 = resize(ref_full, f1)
for name in REGIONS:
    im, mask = load_region(name)
    best = (-1, None, None)
    for s in np.arange(0.55, 1.30, 0.02):
        t = resize(im, s * f1)
        m = (resize(mask, s * f1, cv2.INTER_NEAREST) > 0.5).astype(np.float32)
        score, loc = match(ref1, t, m)
        if score > best[0]:
            best = (score, s, loc)
    score, s0, loc0 = best
    # Refine at half resolution in a window around the coarse hit.
    f2 = 0.5
    ref2 = resize(ref_full, f2)
    best2 = (-1, None, None)
    for s in np.arange(s0 - 0.03, s0 + 0.031, 0.005):
        t = resize(im, s * f2)
        m = (resize(mask, s * f2, cv2.INTER_NEAREST) > 0.5).astype(np.float32)
        cx, cy = loc0[0] * f2 / f1, loc0[1] * f2 / f1
        pad = 40
        x0, y0 = max(0, int(cx - pad)), max(0, int(cy - pad))
        x1 = min(ref2.shape[1], int(cx + t.shape[1] + pad))
        y1 = min(ref2.shape[0], int(cy + t.shape[0] + pad))
        win = ref2[y0:y1, x0:x1]
        sc, l = match(win, t, m)
        if sc > best2[0]:
            best2 = (sc, s, (l[0] + x0, l[1] + y0))
    sc, s, (lx, ly) = best2
    out[name] = {"scale": round(float(s), 4), "x": round(lx / f2, 1), "y": round(ly / f2, 1),
                 "score": round(float(sc), 4), "coarse_score": round(float(score), 4)}
    print(name, out[name], flush=True)

k = args.scale
minx = min(r["x"] for r in out.values())
miny = min(r["y"] for r in out.values())
layout = {"_comment": f"Registered against {Path(REF).name} by gen/register_world_map.py "
                      f"(scale {k}). See gen/combined.py for the format.",
          "scale": k, "margin": 40, "regions": {
              name: {"x": round((r["x"] - minx) * k, 1), "y": round((r["y"] - miny) * k, 1),
                     "scale": round(r["scale"] * k, 4)}
              for name, r in out.items()}}
(GEN / "combined_layout.json").write_text(json.dumps(layout, indent=2) + "\n")
print("wrote gen/combined_layout.json")
