"""Load the Dread logic graph exactly as the apworld builds it, plus the
node-level geometry the graph itself discards (coordinates, room bounds).

The graph comes from ``dread_ap/scripts/extract_dread_rules.py`` run against the
pinned Randovania logic cache (``dread_ap/.dread-cache/randovania-logic``), so the
component ids match the ones the apworld ships in ``slot_data.ut_state``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
PACK_DIR = GEN_DIR.parent
# dread_ap (apworld data + logic extractor) is the external/dread_ap git
# submodule; DREAD_AP_DIR can point at another checkout instead.
DREAD_AP = Path(os.environ.get("DREAD_AP_DIR") or PACK_DIR / "external" / "dread_ap").resolve()
# Region maps: fetched from Randovania with gen/map_edits.json applied
# (gen/external_assets.py). Prepared on first use by load(with_geometry=True).
import external_assets  # noqa: E402
MAPS_SRC = external_assets.MAPS_DIR
BUILD_DIR = GEN_DIR / "build"

EXPECTED_GRAPH_SCHEMA = 8

REGIONS = ["Artaria", "Cataris", "Dairon", "Burenia", "Ghavoran",
           "Elun", "Ferenia", "Hanubia", "Itorash"]


def check_dread_ap() -> None:
    if not (DREAD_AP / "scripts" / "extract_dread_rules.py").exists():
        raise SystemExit(
            f"dread_ap not found at {DREAD_AP}.\n"
            "Fetch the submodule:  git submodule update --init external/dread_ap\n"
            "or point DREAD_AP_DIR at a dread_ap checkout.")


def _load_extractor():
    check_dread_ap()
    path = DREAD_AP / "scripts" / "extract_dread_rules.py"
    spec = importlib.util.spec_from_file_location("extract_dread_rules", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["extract_dread_rules"] = mod
    spec.loader.exec_module(mod)
    return mod


def ensure_cache() -> None:
    check_dread_ap()
    edr_cache = DREAD_AP / ".dread-cache" / "randovania-logic" / "header.json"
    if not edr_cache.exists():
        subprocess.check_call([sys.executable,
                               str(DREAD_AP / "scripts" / "cache_randovania_logic.py")])


@dataclass
class Transform:
    """World (x, y) -> map pixel, per region."""
    sx: float
    ox: float
    sy: float
    oy: float

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return self.sx * x + self.ox, self.sy * y + self.oy


@dataclass
class DreadData:
    graph: dict
    areas: dict                       # region -> raw Randovania region JSON
    comp: dict                        # (region, area, node) -> component id
    nodes: dict                       # (region, area, node) -> raw node
    transforms: dict = field(default_factory=dict)   # region -> Transform
    image_sizes: dict = field(default_factory=dict)  # region -> (w, h)

    # ---- geometry helpers -------------------------------------------------
    def node_world_xy(self, key) -> tuple[float, float]:
        n = self.nodes[key]
        c = n.get("coordinates")
        if c:
            return c["x"], c["y"]
        tb = self.areas[key[0]]["areas"][key[1]]["extra"]["total_boundings"]
        return (tb["x1"] + tb["x2"]) / 2, (tb["y1"] + tb["y2"]) / 2

    def node_pixel(self, key) -> tuple[float, float]:
        return self.transforms[key[0]](*self.node_world_xy(key))


def _default_transform(region: str, region_json: dict, size: tuple[int, int]) -> Transform:
    """Randovania's data-editor calibration (gui/lib/data_editor_canvas.py): the
    union of every room's total_boundings maps onto the image rectangle
    [map_min_x, W - map_max_x] x [map_min_y, H - map_max_y], Y flipped."""
    xs, ys = [], []
    for a in region_json["areas"].values():
        tb = a["extra"].get("total_boundings")
        if tb:
            xs += [tb["x1"], tb["x2"]]
            ys += [tb["y1"], tb["y2"]]
    wx0, wx1, wy0, wy1 = min(xs), max(xs), min(ys), max(ys)
    ex = region_json["extra"]
    w, h = size
    ix0, iy0 = ex.get("map_min_x", 0), ex.get("map_min_y", 0)
    ix1, iy1 = w - ex.get("map_max_x", 0), h - ex.get("map_max_y", 0)
    sx = (ix1 - ix0) / (wx1 - wx0)
    sy = -(iy1 - iy0) / (wy1 - wy0)
    return Transform(sx, ix0 - sx * wx0, sy, iy0 - sy * wy1)


def _two_point_transform(pairs: list) -> Transform:
    """Solve scale+offset per axis from two (world, pixel) reference pairs:
    [{"world": [x, y], "pixel": [px, py]}, {...}]."""
    (w0, p0), (w1, p1) = [(p["world"], p["pixel"]) for p in pairs[:2]]
    sx = (p1[0] - p0[0]) / (w1[0] - w0[0])
    sy = (p1[1] - p0[1]) / (w1[1] - w0[1])
    return Transform(sx, p0[0] - sx * w0[0], sy, p0[1] - sy * w0[1])


def load_calibration() -> dict:
    path = GEN_DIR / "calibration.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_transforms(areas: dict) -> tuple[dict, dict]:
    from PIL import Image

    external_assets.prepare_maps()
    calib = load_calibration()
    transforms, sizes = {}, {}
    for region in REGIONS:
        with Image.open(MAPS_SRC / f"{region}.png") as im:
            size = im.size
        sizes[region] = size
        rj = areas[region]
        override = calib.get(region) or {}
        if "pairs" in override:
            t = _two_point_transform(override["pairs"])
        else:
            if "margins" in override:
                rj = dict(rj)
                rj["extra"] = {**rj["extra"], **override["margins"]}
            t = _default_transform(region, rj, size)
        if "nudge" in override:                 # final pixel offset [dx, dy]
            t = Transform(t.sx, t.ox + override["nudge"][0],
                          t.sy, t.oy + override["nudge"][1])
        transforms[region] = t
    return transforms, sizes


def load(with_geometry: bool = True) -> DreadData:
    ensure_cache()
    edr = _load_extractor()

    graph_path = BUILD_DIR / "logic_graph.json"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    rc = edr.main(["--all", "--out", str(graph_path)])
    if rc:
        raise SystemExit(f"extract_dread_rules failed ({rc})")
    graph = json.loads(graph_path.read_text())
    if graph.get("graph_schema_version") != EXPECTED_GRAPH_SCHEMA:
        raise SystemExit(f"graph schema {graph.get('graph_schema_version')} != "
                         f"{EXPECTED_GRAPH_SCHEMA}; update the pack generator")

    # Recover node -> component exactly like emit_graph does (same node order,
    # same translated connection edges, same SCC routine).
    header = edr.Header.from_json(json.loads((edr.CACHE_DIR / "header.json").read_text()))
    areas = {r: json.loads((edr.CACHE_DIR / f"{r}.json").read_text())
             for r in edr.ALL_AREAS}
    nodes, conn_edges = {}, []
    for region, ad in areas.items():
        for sub_name, sub in ad["areas"].items():
            pneg = edr._rotatable_pessimistic_neg(sub)
            for n_name, n in sub["nodes"].items():
                key = (region, sub_name, n_name)
                nodes[key] = n
                for tgt, req in n.get("connections", {}).items():
                    conn_edges.append((key, (region, sub_name, tgt),
                                       edr.translate_requirement(req, header,
                                                                 pessimistic_neg=pneg)))
    comp = edr._trivial_scc(nodes, conn_edges)
    n_regions = max(comp.values()) + 1
    if n_regions != graph["n_regions"]:
        raise SystemExit(f"component recount mismatch {n_regions} != {graph['n_regions']}")

    data = DreadData(graph=graph, areas=areas, comp=comp, nodes=nodes)
    if with_geometry:
        data.transforms, data.image_sizes = build_transforms(areas)
    return data


def split_side(side_id: str) -> tuple[str, str, str]:
    r, a, n = side_id.split("::")
    return r, a, n


def pickup_node_keys(data: DreadData) -> dict[str, tuple]:
    """AP location name -> Randovania node key, resolved exactly like
    emit_graph (actor pickups by (region, actor), others by pickup_index)."""
    locs = json.loads((DREAD_AP / "apworld" / "dread" / "data" / "locations.json").read_text())
    by_actor = {(l["region"], l["actor"]): l["name"] for l in locs
                if l.get("pickup_type") == "actor" and l.get("actor")}
    by_index = {l["pickup_index"]: l["name"] for l in locs
                if l.get("pickup_type") not in ("actor", "event")
                and l.get("pickup_index") is not None}
    out = {}
    for key, n in data.nodes.items():
        if n.get("node_type") != "pickup":
            continue
        actor = n.get("extra", {}).get("actor_name")
        name = by_actor.get((key[0], actor)) or by_index.get(n.get("pickup_index"))
        if name:
            out[name] = key
    return out


def event_node_keys(data: DreadData) -> dict[str, list]:
    out: dict[str, list] = {}
    for key, n in data.nodes.items():
        if n.get("node_type") == "event":
            out.setdefault(n["event_name"], []).append(key)
    return out
