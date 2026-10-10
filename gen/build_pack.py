"""Generate the Metroid Dread (Archipelago) PopTracker pack.

Inputs (all read-only):
  external/dread_ap                     apworld data + logic extractor (git
                                        submodule; or set DREAD_AP_DIR)
  external/dread_ap/.dread-cache/...    pinned Randovania logic DB (auto-fetched)
  Randovania region maps + item art     fetched at build time at a pinned commit
                                        (gen/external_assets.py); map edits in
                                        gen/map_edits.json
  gen/combined_layout.json              world-map arrangement

Outputs (inside the pack):
  src/data/graph.lua      the apworld's logic graph as Lua tables
  src/data/pack_data.lua  item / location / door / transport / trick tables
  items/*.json  locations/*.json  maps/maps.json  layouts/*.json  images/**

Run:  python gen/build_pack.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import combined
import dread_data as dd
import icons

PACK = dd.PACK_DIR
ITEMS_JSON = dd.DREAD_AP / "apworld" / "dread" / "data" / "items.json"
LOCATIONS_JSON = dd.DREAD_AP / "apworld" / "dread" / "data" / "locations.json"

# Door weaknesses a door can show in a seed: the BASIC rando pool
# (DoorRando.BASIC_DOOR_TYPES) plus every vanilla type that is rando-eligible
# (door_rando.change_from). Order = selector stage order.
DOOR_CHOICES = [
    "Power Beam Door", "Charge Beam Door", "Wide Beam Door", "Plasma Beam Door",
    "Wave Beam Door", "Missile Door", "Super Missile Door", "Grapple Beam Door",
    "Sensor Lock Door", "Access Open",
]
DOOR_SHORT = {
    "Power Beam Door": "Power", "Charge Beam Door": "Charge", "Wide Beam Door": "Wide",
    "Plasma Beam Door": "Plasma", "Wave Beam Door": "Wave", "Missile Door": "Missile",
    "Super Missile Door": "Super Missile", "Grapple Beam Door": "Grapple",
    "Sensor Lock Door": "Sensor Lock", "Access Open": "Open Frame",
}

ITEM_GRID = [
    ["Wide Beam", "Plasma Beam", "Wave Beam", "Charge Beam", "Diffusion Beam",
     "Grapple Beam", "Super Missile", "Ice Missile", "Storm Missile"],
    ["Morph Ball", "Bomb", "Cross Bomb", "Power Bomb", "Varia Suit",
     "Gravity Suit", "Spin Boost", "Space Jump", "Screw Attack"],
    ["Spider Magnet", "Speed Booster", "Flash Shift", "Phantom Cloak",
     "Pulse Radar", "Slide", "Energy Tank", "Energy Part", "Missile Tank"],
    ["Missile+ Tank", "Power Bomb Tank", "Flash Shift Upgrade",
     "Speed Booster Upgrade", "Metroid DNA", "Goal"],
]
# Dark box behind counter numbers (PopTracker can't outline overlay text).
COUNTER_BG = "#000000"
COUNTED = {"Energy Tank", "Energy Part", "Missile Tank", "Missile+ Tank",
           "Power Bomb Tank", "Flash Shift Upgrade", "Speed Booster Upgrade"}

# Logic-relevant option defaults (Options.py) used until slot_data arrives.
OPTION_DEFAULTS = {
    "door_lock_rando": 0, "transport_rando": 0, "trick_level": 1,
    "energy_per_tank": 100, "starting_missiles": 15, "missile_tank_ammo": 2,
    "missile_plus_tank_ammo": 10, "starting_power_bombs": 2,
    "power_bomb_tank_ammo": 1, "flash_shift_included_ammo": 2,
    "required_artifacts": 3, "start_with_pulse_radar": 1,
}
BASE_STARTING_ITEMS = ["Slide", "Pulse Radar", "Missile Tank"]   # World.BASE_STARTING_ITEMS

PIN_SIZE = {"pickup": 26, "door": 16, "transport": 24, "goal": 30, "start": 34}
# Pin sizes on the scaled-down combined world map (doors aren't shown there).
COMBINED_PIN_SIZE = {"pickup": 32, "transport": 28, "goal": 36, "start": 40}


def slug(name: str) -> str:
    s = name.lower().replace("+", "_plus")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def load_tricks() -> list[tuple[str, str]]:
    path = dd.DREAD_AP / "apworld" / "dread" / "Tricks.py"
    spec = importlib.util.spec_from_file_location("dread_tricks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [(t.short_name, t.long_name) for t in mod.DREAD_TRICKS]


# ---------------------------------------------------------------------------
# Lua serialisation
# ---------------------------------------------------------------------------

def lua(v) -> str:
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "{" + ",".join(lua(x) for x in v) + "}"
    if isinstance(v, dict):
        parts = []
        for k, x in v.items():
            if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                parts.append(f"{k}={lua(x)}")
            else:
                parts.append(f"[{lua(k)}]={lua(x)}")
        return "{" + ",".join(parts) + "}"
    raise TypeError(type(v))


class AstTable:
    """Interns rule ASTs into a flat 1-based array of compact Lua tuples."""

    def __init__(self, name_to_code: dict[str, str], side_index: dict[str, int]):
        self.rows: list[list] = []
        self.dyn: list[bool] = []         # subtree depends on events / docks
        self.index: dict[str, int] = {}
        self.code = name_to_code
        self.side_index = side_index
        self.TRUE = self.add({"type": "trivial"})
        self.FALSE = self.add({"type": "impossible"})

    def add(self, ast: dict) -> int:
        key = json.dumps(ast, sort_keys=True)
        hit = self.index.get(key)
        if hit is not None:
            return hit
        t = ast["type"]
        dyn = False
        if t == "trivial":
            row = ["T"]
        elif t == "impossible":
            row = ["F"]
        elif t == "item":
            row = ["i", self.code[ast["name"]], int(ast.get("amount", 1))]
        elif t == "trick":
            row = ["t", ast["name"], int(ast.get("level", 1))]
        elif t == "event":
            row = ["e", ast["name"]]
            dyn = True
        elif t == "misc":
            assert ast["name"] == "DoorLocks", ast
            row = ["m", bool(ast.get("negate", False))]
        elif t == "sum":
            row = ["s", int(ast["base"]), int(ast["threshold"])]
            for term in ast["terms"]:
                row += [self.code[term["name"]], int(term["per_unit"])]
        elif t == "damage_threshold":
            row = ["d", int(ast["hp_needed"])] + [self.code[s] for s in ast.get("suit_options", [])]
        elif t in ("and", "or"):
            kids = [self.add(c) for c in ast["items"]]
            row = ["&" if t == "and" else "|"] + kids
            dyn = any(self.dyn[k - 1] for k in kids)
        elif t == "dock":
            row = ["k", self.side_index[ast["side_id"]]]
            dyn = True
        else:
            raise ValueError(t)
        self.rows.append(row)
        self.dyn.append(dyn)
        idx = len(self.rows)
        self.index[key] = idx
        return idx


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def room_id(data, key) -> str:
    """Randovania room -> "scenario:collision_camera" (the room's asset_id)."""
    region, area = key[0], key[1]
    return (f"{data.areas[region]['extra']['scenario_id']}:"
            f"{data.areas[region]['areas'][area]['extra']['asset_id']}")


def physical_doors(dock_sides: dict) -> list[list[str]]:
    """Mirror of DoorRando._physical_doors (same iteration order)."""
    seen, groups = set(), []
    for sid, meta in dock_sides.items():
        if sid in seen:
            continue
        group = [sid]
        seen.add(sid)
        pair = meta.get("paired_side_id")
        if pair and pair in dock_sides and pair not in seen:
            group.append(pair)
            seen.add(pair)
        groups.append(group)
    return groups


def spread(pins: list[dict], min_dist: float) -> None:
    """Nudge pins on the same map apart so overlapping checks stay clickable."""
    by_map = defaultdict(list)
    for p in pins:
        by_map[p["map"]].append(p)
    for group in by_map.values():
        for _ in range(30):
            moved = False
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                    d = math.hypot(dx, dy)
                    if d >= min_dist:
                        continue
                    if d < 1e-6:
                        dx, dy, d = 1.0, 0.0, 1.0
                    push = (min_dist - d) / 2 + 0.5
                    ux, uy = dx / d, dy / d
                    a["x"] -= ux * push
                    a["y"] -= uy * push
                    b["x"] += ux * push
                    b["y"] += uy * push
                    moved = True
            if not moved:
                break


def main() -> int:
    data = dd.load()
    g = data.graph
    items = json.loads(ITEMS_JSON.read_text())
    locations = json.loads(LOCATIONS_JSON.read_text())
    tricks = load_tricks()

    # ---- images -----------------------------------------------------------
    img_items = icons.write_item_icons(PACK / "images" / "items")
    icons.write_door_icons(PACK / "images" / "doors")
    trick_imgs = {s: icons.write_trick_icon(PACK / "images" / "tricks", s) for s, _ in tricks}
    tr_imgs = icons.write_transport_icons(PACK / "images" / "transports")
    setting_imgs = icons.write_setting_icons(PACK / "images" / "settings")
    icons.copy_maps(dd.MAPS_SRC, PACK / "images" / "maps", dd.REGIONS)

    # ---- items ------------------------------------------------------------
    name_to_code = {it["name"]: slug(it["name"]) for it in items}
    item_by_name = {it["name"]: it for it in items}
    progressives = {it["name"]: it["progression_tiers"] for it in items
                    if it.get("progression_tiers")}

    items_out = []
    for name in [n for row in ITEM_GRID for n in row]:
        code = slug(name)
        if name == "Metroid DNA":
            items_out.append({"name": "Metroid DNA", "type": "consumable",
                              "codes": "metroid_dna", "img": img_items[name],
                              "min_quantity": 0, "max_quantity": 12,
                              "overlay_background": COUNTER_BG})
        elif name == "Goal":
            items_out.append({"name": "Goal: Escape Raven Beak", "type": "toggle",
                              "codes": "goal", "img": img_items[name]})
        elif name in COUNTED:
            items_out.append({"name": name, "type": "consumable", "codes": code,
                              "img": img_items[name], "min_quantity": 0,
                              "max_quantity": -1, "overlay_background": COUNTER_BG})
        else:
            items_out.append({"name": name, "type": "toggle", "codes": code,
                              "img": img_items[name]})
    # Hidden helper: bumped from Lua whenever non-item settings change, so
    # PopTracker re-runs every access / visibility rule.
    items_out.append({"name": "Settings revision", "type": "consumable",
                      "codes": "settings_rev", "img": img_items["Goal"],
                      "min_quantity": 0, "max_quantity": -1})
    # Hidden helper: hash of the connected seed+slot, so reconnecting to the
    # same seed keeps the player's door / transport notes.
    items_out.append({"name": "Seed hash", "type": "consumable",
                      "codes": "seed_hash", "img": img_items["Goal"],
                      "min_quantity": 0, "max_quantity": -1})

    trick_items = []
    for short, long_name in tricks:
        trick_items.append({
            "name": f"Trick: {long_name}", "type": "consumable",
            "codes": f"trick_{short.lower()}", "img": trick_imgs[short],
            "min_quantity": 0, "max_quantity": 5,
            "initial_quantity": OPTION_DEFAULTS["trick_level"],
            "overlay_background": COUNTER_BG})

    # ---- doors ------------------------------------------------------------
    dock_sides = g["dock_sides"]
    side_ids = list(dock_sides)
    side_index = {sid: i + 1 for i, sid in enumerate(side_ids)}
    ast = AstTable(name_to_code, side_index)

    wreq_idx = {k[len("door::"):]: ast.add(v) for k, v in g["weakness_requirements"].items()
                if k.startswith("door::")}

    groups = physical_doors(dock_sides)
    side_group = {}
    door_entries = []
    for gi, group in enumerate(groups, start=1):
        door_sid = next((s for s in group if not dock_sides[s].get("companion")), group[0])
        for s in group:
            side_group[s] = gi
        incompat = sorted({w for s in group for w in dock_sides[s].get("incompatible_weaknesses", [])})
        keys = [dd.split_side(s) for s in group]
        pix = [data.node_pixel(k) for k in keys]
        region = keys[0][0]
        x = sum(p[0] for p in pix) / len(pix)
        y = sum(p[1] for p in pix) / len(pix)
        rooms = [k[1] for k in keys]
        label = " <> ".join(rooms) if len(rooms) > 1 else f"{rooms[0]} ({keys[0][2]})"
        door_entries.append({
            "sides": [side_index[s] for s in group],
            "door_side": side_index[door_sid],
            "weakness": dock_sides[door_sid]["default_weakness"],
            "incompat": incompat,
            "region": region, "label": label, "x": x, "y": y,
            "comps": sorted({data.comp[k] for k in keys}),
            # "scenario:collision_camera" of the rooms on either side, matched
            # against the Dread client's dread_visited_rooms DataStorage key.
            "rooms": sorted({room_id(data, k) for k in keys}),
            # World position of the doorway (both sides sit on it), for
            # revealing the door only once it has been on screen.
            "pos": [round(sum(data.node_world_xy(k)[0] for k in keys) / len(keys)),
                    round(sum(data.node_world_xy(k)[1] for k in keys) / len(keys))],
        })

    sides_lua = []
    for sid in side_ids:
        meta = dock_sides[sid]
        if meta.get("vanilla_ast") is not None:
            van = ast.add(meta["vanilla_ast"])
        else:
            key = f"{meta['dock_type']}::{meta['default_weakness']}"
            van = ast.add(g["weakness_requirements"].get(key, {"type": "impossible"}))
        sides_lua.append({"id": sid, "group": side_group[sid], "vanilla": van,
                          "companion": bool(meta.get("companion")),
                          "weakness": meta["default_weakness"]})

    # ---- transports -------------------------------------------------------
    transports = g["transports"]
    tr_ids = list(transports)
    tr_index = {sid: i + 1 for i, sid in enumerate(tr_ids)}
    tr_lua, tr_pins = [], []

    def tr_label(sid: str) -> str:
        r, a, _n = dd.split_side(sid)
        return f"{r} - {a}"

    for i, sid in enumerate(tr_ids, start=1):
        meta = transports[sid]
        same_type = [s for s in tr_ids if transports[s]["type"] == meta["type"] and s != sid]
        tr_lua.append({"id": sid, "comp": meta["comp"], "kind": meta["type"],
                       "default_dest": tr_index[meta["default_dest"]],
                       "label": tr_label(sid),
                       "room": room_id(data, dd.split_side(sid)),
                       "choices": [tr_index[s] for s in same_type]})
        key = dd.split_side(sid)
        px, py = data.node_pixel(key)
        tr_pins.append({"kind": "transport", "i": i, "sid": sid, "map": key[0],
                        "x": px, "y": py,
                        "vanilla": tr_label(meta["default_dest"]), "type": meta["type"]})

    # ---- entrances / events / pickups -------------------------------------
    es, ed, ea = [], [], []
    dock_entrance = {}
    for i, (c0, c1, a) in enumerate(g["entrances"], start=1):
        es.append(c0)
        ed.append(c1)
        ea.append(ast.add(a))
        if a.get("type") == "dock":
            dock_entrance[side_index[a["side_id"]]] = i
    comp_events: dict[int, list[str]] = defaultdict(list)
    for c, e in g["events"]:
        if e not in comp_events[c]:
            comp_events[c].append(e)
    victory = ast.add(g["victory_condition"])

    loc_by_name = {l["name"]: l for l in locations}
    pickup_comp = {loc_by_name[n]["ap_id"]: c for c, n in g["pickups"]}

    # Every valid spawn (more-starting-areas). Each has its own component, so
    # the seed's ut_state.start_comp picks exactly one.
    start_points = []
    for key_str, meta in g["start_comps"].items():
        key = dd.split_side(key_str)
        sx, sy = data.node_pixel(key)
        start_points.append({"comp": meta["comp"], "region": key[0],
                             "label": f"{key[1]} ({key[2]})", "x": sx, "y": sy})

    # ---- graph.lua --------------------------------------------------------
    write_graph_lua(PACK / "src" / "data" / "graph.lua", g, ast, es, ed, ea,
                    sides_lua, door_entries, wreq_idx, tr_lua, comp_events,
                    pickup_comp, victory, dock_entrance, start_points,
                    {data.areas[r]["extra"]["scenario_id"]: r for r in dd.REGIONS})

    # ---- pins -------------------------------------------------------------
    pk_keys = dd.pickup_node_keys(data)
    pins = []
    for c, name in g["pickups"]:
        loc = loc_by_name[name]
        key = pk_keys[name]
        px, py = data.node_pixel(key)
        pins.append({"kind": "pickup", "loc": loc, "map": key[0], "x": px, "y": py})
    for gi, d in enumerate(door_entries, start=1):
        pins.append({"kind": "door", "gi": gi, "door": d, "map": d["region"],
                     "x": d["x"], "y": d["y"]})
    pins += tr_pins
    # The victory condition is the "Ship" event (Raven Beak arena escape).
    goal_key = dd.event_node_keys(data)["Ship"][0]
    gx, gy = data.node_pixel(goal_key)
    pins.append({"kind": "goal", "map": goal_key[0], "x": gx, "y": gy})
    for si, sp in enumerate(start_points, start=1):
        pins.append({"kind": "start", "si": si, "label": sp["label"],
                     "map": sp["region"], "x": sp["x"], "y": sp["y"]})

    # Pickups first (they matter most), then doors / transports around them.
    spread([p for p in pins if p["kind"] in ("pickup", "goal", "transport", "start")], 18)

    # Combined world map: same pins, placed by gen/combined_layout.json and
    # spread again at the smaller scale.
    layout = combined.CombinedLayout(combined.load_layout(), dd.REGIONS)
    size = layout.render(dd.MAPS_SRC, PACK / "images" / "maps" / f"{combined.MAP_NAME}.png")
    proxies = []
    for p in pins:
        if p["kind"] in COMBINED_PIN_SIZE:
            cx, cy = layout.to_combined(p["map"], p["x"], p["y"])
            proxies.append({"map": combined.MAP_NAME, "x": cx, "y": cy, "pin": p})
    spread(proxies, 24)   # keep the larger pins from overlapping
    for q in proxies:
        q["pin"]["combined"] = (round(q["x"]), round(q["y"]))
    print(f"combined map: {size[0]}x{size[1]} px, {len(proxies)} pins")

    write_locations(PACK / "locations", pins, img_items, item_by_name)
    # ---- json outputs -----------------------------------------------------
    write_json(PACK / "items" / "items.json", items_out)
    write_json(PACK / "items" / "tricks.json", trick_items)
    # Player settings: toggles for the automatic behaviours (on by default).
    write_json(PACK / "items" / "settings.json", [
        {"name": "Auto-fill door locks when seen (needs the Dread client room feed)",
         "type": "toggle", "codes": "auto_doors", "img": setting_imgs["auto_doors"],
         "initial_active_state": True},
        {"name": "Auto-fill transport destinations when ridden",
         "type": "toggle", "codes": "auto_transports", "img": setting_imgs["auto_transports"],
         "initial_active_state": True},
        {"name": "Auto-switch the map tab to the region you're in",
         "type": "toggle", "codes": "auto_maptab", "img": setting_imgs["auto_maptab"],
         "initial_active_state": True},
    ])
    write_json(PACK / "maps" / "maps.json", [
        {"name": r, "location_size": PIN_SIZE["pickup"],
         "location_border_thickness": 3, "img": f"images/maps/{r}.png"}
        for r in dd.REGIONS] + [
        {"name": combined.MAP_NAME, "location_size": COMBINED_PIN_SIZE["pickup"],
         "location_border_thickness": 4,
         "img": f"images/maps/{combined.MAP_NAME}.png"}])
    write_layouts(PACK / "layouts", tricks, g["door_rando"]["change_from"], len(tr_ids))

    write_pack_data(PACK / "src" / "data" / "pack_data.lua", items, locations,
                    progressives, tricks, door_entries, len(tr_ids), g)

    print(f"graph: {g['n_regions']} comps, {len(es)} entrances, {len(ast.rows)} AST rows")
    print(f"pins: {sum(p['kind']=='pickup' for p in pins)} pickups, "
          f"{len(door_entries)} doors, {len(tr_ids)} transports")
    return 0


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_graph_lua(path, g, ast, es, ed, ea, sides, doors, wreq, trs,
                    comp_events, pickup_comp, victory, dock_entrance,
                    start_points, scenario_region) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    L = ["-- AUTO-GENERATED by gen/build_pack.py from the dread_ap logic graph.",
         f"-- graph_schema_version={g['graph_schema_version']} "
         f"randovania={g.get('pinned_commit', '?')}",
         "-- Do not edit by hand.", "",
         "GRAPH = {}",
         f"GRAPH.schema = {g['graph_schema_version']}",
         f"GRAPH.pinned_commit = {lua(g.get('pinned_commit', ''))}",
         f"GRAPH.n_comps = {g['n_regions']}",
         f"GRAPH.start_comp = {g['start_comp']}",
         f"GRAPH.victory = {victory}", ""]
    # AST rows, chunked into functions to stay well inside Lua's per-function
    # constant / register limits.
    L.append("local A = {}")
    L.append("local D = {}")
    chunk = 1500
    for start in range(0, len(ast.rows), chunk):
        L.append("do")
        for i in range(start, min(start + chunk, len(ast.rows))):
            L.append(f"A[{i + 1}]={lua(ast.rows[i])}")
        L.append("end")
    L.append("do")
    dyn_ids = [i + 1 for i, d in enumerate(ast.dyn) if d]
    for start in range(0, len(dyn_ids), 400):
        L.append("for _, i in ipairs(" + lua(dyn_ids[start:start + 400]) + ") do D[i] = true end")
    L.append("end")
    L.append("GRAPH.ast = A")
    L.append("GRAPH.ast_dynamic = D")
    L.append("")
    for name, arr in (("es", es), ("ed", ed), ("ea", ea)):
        L.append(f"GRAPH.{name} = {{}}")
        for start in range(0, len(arr), 500):
            L.append(f"for _, v in ipairs({lua(arr[start:start + 500])}) do "
                     f"table.insert(GRAPH.{name}, v) end")
    L.append("")
    L.append("GRAPH.sides = {")
    for s in sides:
        L.append("  " + lua(s) + ",")
    L.append("}")
    L.append("GRAPH.doors = {")
    for d in doors:
        L.append("  " + lua({k: d[k] for k in ("sides", "door_side", "weakness",
                                               "incompat", "comps", "label",
                                               "rooms", "pos")}) + ",")
    L.append("}")
    L.append(f"GRAPH.dock_entrance = {lua({k: v for k, v in dock_entrance.items()})}")
    L.append(f"GRAPH.weakness_ast = {lua(wreq)}")
    L.append(f"GRAPH.door_change_from = {lua(g['door_rando']['change_from'])}")
    L.append(f"GRAPH.scenario_region = {lua(scenario_region)}")
    L.append("GRAPH.transports = {")
    for t in trs:
        L.append("  " + lua(t) + ",")
    L.append("}")
    L.append("GRAPH.comp_events = {")
    for c in sorted(comp_events):
        L.append(f"  [{c}]={lua(comp_events[c])},")
    L.append("}")
    L.append(f"GRAPH.pickup_comp = {lua(pickup_comp)}")
    L.append("GRAPH.start_points = {")
    for sp in start_points:
        L.append("  " + lua({k: sp[k] for k in ("comp", "region", "label")}) + ",")
    L.append("}")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_locations(out_dir: Path, pins: list[dict], img_items: dict, item_by_name: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_region = defaultdict(list)
    for p in pins:
        x, y = round(p["x"]), round(p["y"])
        if p["kind"] == "pickup":
            loc = p["loc"]
            img = img_items.get(loc["vanilla_item"]) if loc["vanilla_item"] in img_items else None
            by_region[p["map"]].append({"_pin": p,
                "name": loc["name"],
                "access_rules": [f"^$CanReachLocation|{loc['ap_id']}"],
                "visibility_rules": [f"$LocationExists|{loc['ap_id']}"],
                "map_locations": [{"map": p["map"], "x": x, "y": y}],
                "sections": [{"name": "Pickup", "item_count": 1,
                              **({"chest_unopened_img": img} if img and loc["pickup_type"] != "actor" else {})}],
            })
        elif p["kind"] == "door":
            gi, d = p["gi"], p["door"]
            by_region[p["map"]].append({"_pin": p,
                "name": f"Door {gi}: {d['label']}",
                "access_rules": [f"^$DoorAccess|{gi}"],
                "visibility_rules": [f"$DoorPinVisible|{gi}"],
                "map_locations": [{"map": p["map"], "x": x, "y": y,
                                   "size": PIN_SIZE["door"], "border_thickness": 2,
                                   "shape": "diamond"}],
                "sections": [
                    {"name": f"Lock (vanilla: {DOOR_SHORT.get(d['weakness'], d['weakness'])})",
                     "item_count": 0, "hosted_item": f"door_{gi}",
                     # Door Types mode sets locks per type, not per door.
                     "visibility_rules": ["$DoorModeIs|individual"]},
                    {"name": f"{DOOR_SHORT.get(d['weakness'], d['weakness'])} doors become",
                     "item_count": 0, "hosted_item": f"doortype_{slug(d['weakness'])}",
                     "visibility_rules": ["$DoorModeIs|types"]},
                ],
            })
        elif p["kind"] == "transport":
            i = p["i"]
            by_region[p["map"]].append({"_pin": p,
                "name": f"Transport: {dd.split_side(p['sid'])[1]}",
                "access_rules": [f"^$TransportAccess|{i}"],
                "map_locations": [{"map": p["map"], "x": x, "y": y,
                                   "size": PIN_SIZE["transport"], "shape": "trapezoid"}],
                "sections": [
                    {"name": "Destination", "item_count": 0,
                     "hosted_item": f"transport_{i}",
                     "visibility_rules": ["$TransportRandoOn"]},
                    {"name": f"Goes to {p['vanilla']}", "item_count": 0,
                     "visibility_rules": ["$TransportRandoOff"]},
                ],
            })
        elif p["kind"] == "goal":
            by_region[p["map"]].append({"_pin": p,
                "name": "Goal: Escape Raven Beak",
                "access_rules": ["^$GoalAccess"],
                "map_locations": [{"map": p["map"], "x": x, "y": y,
                                   "size": PIN_SIZE["goal"], "shape": "diamond"}],
                "sections": [{"name": "Defeat Raven Beak and escape", "item_count": 0,
                              "hosted_item": "goal"}],
            })
        elif p["kind"] == "start":
            by_region[p["map"]].append({"_pin": p,
                "name": f"Start: {p['label']}",
                "access_rules": ["^$StartPointAccess"],
                "visibility_rules": [f"$IsStartPoint|{p['si']}"],
                "chest_unopened_img": img_items["Start"],
                "chest_opened_img": img_items["Start"],
                "map_locations": [{"map": p["map"], "x": x, "y": y,
                                   "size": PIN_SIZE["start"], "border_thickness": 4,
                                   "shape": "rect"}],
                "sections": [{"name": "Starting point", "item_count": 1}],
            })
    # Second pin on the combined world map for everything except doors.
    for region, children in by_region.items():
        for child in children:
            p = child.pop("_pin", None)
            if p is not None and "combined" in p:
                cx, cy = p["combined"]
                ml = dict(child["map_locations"][0])
                ml.update({"map": combined.MAP_NAME, "x": cx, "y": cy,
                           "size": COMBINED_PIN_SIZE[p["kind"]], "border_thickness": 4})
                child["map_locations"].append(ml)
        write_json(out_dir / f"{region}.json", [{"name": region, "children": children}])


def write_layouts(out_dir: Path, tricks, change_from, n_transports) -> None:
    def grid(rows, size=36):
        return {"type": "itemgrid", "item_margin": "3,3", "item_size": size,
                "h_alignment": "left", "rows": rows}

    item_rows = [[slug(n) if n not in ("Metroid DNA", "Goal") else
                  {"Metroid DNA": "metroid_dna", "Goal": "goal"}[n] for n in row]
                 for row in ITEM_GRID]
    trick_codes = [f"trick_{s.lower()}" for s, _ in tricks]
    # PopTracker always centres tab buttons over the tab widget's width, so the
    # seed grids are kept about as wide as the button row to keep them flush left.
    trick_rows = [trick_codes[i:i + 7] for i in range(0, len(trick_codes), 7)]
    type_codes = [f"doortype_{slug(w)}" for w in change_from]
    tr_codes = [f"transport_{i}" for i in range(1, n_transports + 1)]

    map_tabs = [{"title": r, "content": {"type": "map", "maps": [r]}}
                for r in sorted(dd.REGIONS)]
    map_tabs.append({"title": "World", "content": {"type": "map", "maps": [combined.MAP_NAME]}})

    def panel(rows):
        return {"type": "array", "orientation": "vertical", "margin": "6,6",
                "content": [grid(rows)]}

    # Seed-knowledge tabs shown next to the item list in the bottom bar.
    seed_tabs = [
        {"title": "Door Types", "content": panel(
            [type_codes[i:i + 5] for i in range(0, len(type_codes), 5)])},
        {"title": "Transports", "content": panel(
            [tr_codes[i:i + 8] for i in range(0, len(tr_codes), 8)])},
        {"title": "Tricks", "content": panel(trick_rows)},
        {"title": "Settings", "content": panel([["auto_doors", "auto_transports", "auto_maptab"]])},
    ]

    layouts = {
        "maps": {"type": "tabbed", "tabs": map_tabs},
        "seed_info": {"type": "tabbed", "tabs": seed_tabs},
        "equipment": {"type": "array", "orientation": "vertical", "margin": "6,6",
                      "content": [grid(item_rows)]},
        "tracker_default": {
            "type": "container", "background": "#0c151c",
            "content": {"type": "dock", "dropshadow": True, "content": [
                {"type": "dock", "dock": "bottom", "content": [
                    {"type": "group", "header": "Equipment", "dock": "left",
                     "content": {"type": "layout", "key": "equipment"}},
                    {"type": "group", "header": "Seed", "dock": "left",
                     "content": {"type": "layout", "key": "seed_info"}},
                    # A dock stretches its last child over the remaining width;
                    # this empty filler takes that role so "Seed" keeps its own
                    # width and its tabs sit at the left.
                    {"type": "array", "dock": "left", "content": []}]},
                {"type": "layout", "key": "maps"},
            ]}},
        "tracker_broadcast": {"type": "container", "background": "#00ff00",
                              "content": {"type": "layout", "key": "equipment"}},
    }
    side_bar = dict(layouts)
    side_bar["tracker_default"] = {
        "type": "container", "background": "#0c151c",
        "content": {"type": "dock", "dropshadow": True, "content": [
            {"type": "array", "dock": "left", "orientation": "vertical", "content": [
                {"type": "group", "header": "Equipment",
                 "content": {"type": "layout", "key": "equipment"}},
                {"type": "group", "header": "Seed",
                 "content": {"type": "layout", "key": "seed_info"}}]},
            {"type": "layout", "key": "maps"},
        ]}}
    items_only = {
        "tracker_default": {"type": "container", "background": "#0c151c",
                            "content": {"type": "layout", "key": "equipment"}},
    }
    write_json(out_dir / "tracker.json", layouts)
    write_json(PACK / "var_side_bar" / "layouts" / "tracker.json", side_bar)
    write_json(PACK / "var_items_only" / "layouts" / "tracker.json", items_only)


def write_pack_data(path: Path, items, locations, progressives, tricks, doors,
                    n_transports, g) -> None:
    item_ids = {}
    for it in items:
        name = it["name"]
        if name.startswith("Metroid DNA"):
            item_ids[it["ap_id"]] = {"kind": "dna"}
        elif name in progressives:
            item_ids[it["ap_id"]] = {"kind": "progressive", "name": name,
                                     "tiers": [slug(t) for t in progressives[name]]}
        elif name in COUNTED:
            item_ids[it["ap_id"]] = {"kind": "count", "code": slug(name)}
        else:
            item_ids[it["ap_id"]] = {"kind": "toggle", "code": slug(name)}
    loc_paths = {l["ap_id"]: f"@{l['region']}/{l['name']}/Pickup" for l in locations
                 if l.get("pickup_type") != "event"}
    L = ["-- AUTO-GENERATED by gen/build_pack.py. Do not edit by hand.", "",
         "PACK_DATA = {}",
         f"PACK_DATA.item_ids = {lua(item_ids)}",
         f"PACK_DATA.location_paths = {lua(loc_paths)}",
         f"PACK_DATA.tricks = {lua([s for s, _ in tricks])}",
         f"PACK_DATA.option_defaults = {lua(OPTION_DEFAULTS)}",
         f"PACK_DATA.base_starting_items = {lua([slug(n) for n in BASE_STARTING_ITEMS])}",
         f"PACK_DATA.door_choices = {lua(DOOR_CHOICES)}",
         f"PACK_DATA.door_short = {lua(DOOR_SHORT)}",
         f"PACK_DATA.n_doors = {len(doors)}",
         f"PACK_DATA.n_transports = {n_transports}",
         f"PACK_DATA.item_codes_by_name = {lua({it['name']: slug(it['name']) for it in items})}",
         # Items whose number overlay is a count (coloured for readability).
         f"PACK_DATA.counter_codes = {lua(sorted(slug(n) for n in COUNTED) + ['metroid_dna'] + [f'trick_{s.lower()}' for s, _ in tricks])}",
         ]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
