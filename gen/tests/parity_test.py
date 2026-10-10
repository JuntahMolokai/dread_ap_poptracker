"""Lua-vs-apworld logic parity + door-reveal soundness.

Runs the pack's own Lua (src/data/*.lua, src/logic/reach.lua, state.lua) under
Lua 5.4 (``lupa``) with a stub ``Tracker``, and compares the reachable component
set against dread_ap's ``DoorRando.early_reachable`` — the same sweep the
apworld uses for its door / transport / start-area guards — over randomized
item sets, trick levels, door assignments and transport matchings.

Checks per scenario:
  * exact:   doors + transports fully known  -> Lua normal reach == apworld reach
  * sound:   doors / transports unknown      -> Lua normal reach  <= truth
             (never claims an unreachable spot is in logic)
  * relaxed: unknown + every trick at max    -> Lua relaxed reach >= truth
  * reveal:  every door the pack reveals as known-vanilla is really unassigned
  * discovered: every room visited and every ride taken, fed through the
             client's DataStorage room / ride keys -> doors and transports are
             filled in from the real assignment and Lua normal reach ==
             apworld reach, with no simplification (exact even for doors
             rolled onto their own vanilla lock)

Usage:  python gen/tests/parity_test.py [--seeds N]
Requires: pip install lupa
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import lupa.lua54 as lupa

PACK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACK / "gen"))
from dread_data import DREAD_AP, check_dread_ap  # noqa: E402
check_dread_ap()
sys.path.insert(0, str(DREAD_AP / "apworld"))

from dread.DoorRando import (DEFAULT_CHANGE_DOORS_TO, DEFAULT_DOORS_TO_CHANGE,  # noqa: E402
                             early_reachable, roll_assignments)
from dread.TransportRando import roll_connected_matching  # noqa: E402

GRAPH = json.loads((PACK / "gen" / "build" / "logic_graph.json").read_text())
ITEMS = json.loads((DREAD_AP / "apworld" / "dread" / "data" / "items.json").read_text())

STUB = r"""
AccessibilityLevel = {None=0, Partial=1, Inspect=3, SequenceBreak=5, Normal=6, Cleared=7}
Tracker = {counts = {}, objs = {}}
function Tracker:ProviderCountForCode(c) return self.counts[c] or 0 end
function Tracker:FindObjectForCode(c) return self.objs[c] end
ScriptHost = {AddWatchForCode = function() end}
Archipelago = {PlayerNumber = 1, TeamNumber = 0}
function Archipelago:AddRetrievedHandler() end
function Archipelago:AddSetReplyHandler() end
function TouchSettings() LOGIC_DIRTY = true end
"""

TIER_ITEMS = [n for it in ITEMS for n in (it.get("progression_tiers") or [])]
PLAIN = [it["name"] for it in ITEMS
         if not it.get("progression_tiers") and not it["name"].startswith("Metroid DNA")]
COUNTED = {"Energy Tank": 8, "Energy Part": 16, "Missile Tank": 60, "Missile+ Tank": 12,
           "Power Bomb Tank": 13, "Flash Shift Upgrade": 4, "Speed Booster Upgrade": 4}
TRICKS = ["Knowledge", "Movement", "Combat", "Pseudo", "IBJ", "WBJ", "WSJ", "SWJ", "Slide",
          "Speedbooster", "Walljump", "Suitless", "RGrapple", "DBoost", "FrozenEnemy",
          "GrappleMovement", "CrossSkip", "TunnelSlope", "ShortBoost", "DiffusionAbuse",
          "FlashSkip", "DBJ", "LedgeWarp", "CBL", "FloorClip", "SlopeClimb"]
BASE_KIT = {"Slide": 1, "Pulse Radar": 1, "Missile Tank": 1}
AMMO = {"missile_base": 15, "missile_tank_per_unit": 2, "missile_plus_tank_per_unit": 10,
        "pb_base": 0, "power_bomb_per_unit": 2, "power_bomb_tank_per_unit": 1}
FLASH_INCLUDED = 2


def slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("+", "_plus")).strip("_")


def make_lua():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(STUB)
    for f in ("src/data/graph.lua", "src/data/pack_data.lua",
              "src/logic/reach.lua", "src/logic/state.lua", "src/selectors.lua",
              "src/autotracking/discovery.lua"):
        L.execute((PACK / f).read_text(encoding="utf-8"))
    return L


def lua_table(L, d):
    t = L.table()
    for k, v in d.items():
        t[k] = v
    return t


def random_items(rng, richness: float) -> dict[str, int]:
    items = dict(BASE_KIT)
    for n in PLAIN + TIER_ITEMS:
        if n in COUNTED:
            items[n] = items.get(n, 0) + rng.randint(0, int(COUNTED[n] * richness))
        elif rng.random() < richness:
            items[n] = 1
    return items


def ap_items(items: dict[str, int]) -> dict[str, int]:
    """Items as AP's CollectionState sees them (World.collect's chain credit)."""
    out = dict(items)
    if out.get("Flash Shift", 0):
        out["Flash Shift Upgrade"] = out.get("Flash Shift Upgrade", 0) + FLASH_INCLUDED
    return out


def configure(L, items, tl, door_mode, transport_on):
    S = L.globals().SETTINGS
    T = L.globals().Tracker
    counts = L.table()
    for n, c in items.items():
        counts[slug(n)] = c
    for code in ("auto_doors", "auto_transports", "auto_maptab"):   # settings toggles on
        counts[code] = 1
    T.counts = counts
    T.objs = L.table()
    opts = L.globals().PACK_DATA.option_defaults
    o = L.table()
    for k, v in opts.items():
        o[k] = v
    o["door_lock_rando"] = {"vanilla": 0, "individual": 1, "types": 2}[door_mode]
    o["transport_rando"] = 1 if transport_on else 0
    S.options = o
    S.tricks = lua_table(L, tl)
    S.doors_to_change = lua_table(L, {w: True for w in DEFAULT_DOORS_TO_CHANGE})
    S.start_comp = GRAPH["start_comp"]
    S.start_extra_items = L.table()
    S.known_vanilla = L.table()
    S.door_exact = L.table()
    S.discovered_vanilla = L.table()


_MAKE_SELECTOR = None


def set_selector(L, code, stage_idx):
    """Stand-in selector: stage via :Get / :Set (see src/selectors.lua);
    0 = unknown, k = k-th choice."""
    global _MAKE_SELECTOR
    if _MAKE_SELECTOR is None:
        _MAKE_SELECTOR = L.eval("""function(st)
            local o = {stage = st}
            function o:Get(k) return self[k] end
            function o:Set(k, v) self[k] = v end
            return o
        end""")
    L.globals().Tracker.objs[code] = _MAKE_SELECTOR(stage_idx or 0)


def reach_sets(L):
    L.globals().LOGIC_DIRTY = True
    r = L.globals().GetReach()
    return ({int(k) for k, v in r.normal.items() if v},
            {int(k) for k, v in r.relaxed.items() if v})


def run(seeds: int) -> int:
    L = make_lua()
    doors = list(L.globals().GRAPH.doors.values())
    door_choices = list(L.globals().PACK_DATA.door_choices.values())
    side_ids = [s.id for s in L.globals().GRAPH.sides.values()]
    trs = list(L.globals().GRAPH.transports.values())
    tr_index = {t.id: i + 1 for i, t in enumerate(trs)}
    failures = 0
    for seed in range(seeds):
        rng = random.Random(seed)
        door_mode = ["vanilla", "individual", "types"][seed % 3]
        transport_on = seed % 2 == 1
        tl = {t: rng.choice([0, 1, 1, 2, 3, 5]) for t in TRICKS}
        matching = (roll_connected_matching(GRAPH, rng, tl,
                                            door_lock_rando=door_mode != "vanilla")
                    if transport_on else {})
        assign = (roll_assignments(GRAPH, rng, mode=door_mode, starting_items=BASE_KIT,
                                   trick_levels=tl, transport_matching=matching,
                                   doors_to_change=set(DEFAULT_DOORS_TO_CHANGE),
                                   change_doors_to=set(DEFAULT_CHANGE_DOORS_TO))
                  if door_mode != "vanilla" else {})
        items = random_items(rng, rng.choice([0.2, 0.5, 0.8, 1.0]))
        configure(L, items, tl, door_mode, transport_on)

        L.globals().ComputeKnownVanillaDoors(lua_table(L, matching) if matching else None)
        known = {int(k) for k, v in L.globals().SETTINGS.known_vanilla.items() if v}
        bad = [gi for gi in known
               if any(side_ids[s - 1] in assign for s in doors[gi - 1].sides.values())]
        if bad:
            failures += 1
            print(f"[seed {seed}] REVEAL UNSOUND: {len(bad)} known-vanilla doors were randomized")

        ref_assign = dict(assign)
        for d in doors:
            sides = [side_ids[s - 1] for s in d.sides.values()]
            if ref_assign.get(sides[0]) == d.weakness:
                for s in sides:
                    ref_assign.pop(s, None)
        truth, _ = early_reachable(GRAPH, ap_items(items), tl, None, use_events=True,
                                   transport_matching=matching, ammo_amounts=AMMO,
                                   dock_assignments=ref_assign,
                                   is_door_rando=door_mode != "vanilla")

        n_unknown, r_unknown = reach_sets(L)
        over = n_unknown - truth
        if over:
            failures += 1
            print(f"[seed {seed}] UNSOUND (unknown): {len(over)} comps in logic beyond truth")
        under = truth - r_unknown
        if under:
            failures += 1
            print(f"[seed {seed}] RELAXED MISSES: {len(under)} truly reachable comps")

        exceptions = 0
        if door_mode == "individual":
            for gi, d in enumerate(doors, start=1):
                side0 = side_ids[d.sides[1] - 1]
                w = assign.get(side0, d.weakness)
                set_selector(L, f"door_{gi}", door_choices.index(w) + 1)
        elif door_mode == "types":
            type_map = {}
            for d in doors:
                side0 = side_ids[d.sides[1] - 1]
                if side0 in assign:
                    type_map[d.weakness] = assign[side0]
            for src, w in type_map.items():
                set_selector(L, L.globals().DoorTypeCode(src), door_choices.index(w) + 1)
            believed = {}
            for gi, d in enumerate(doors, start=1):
                sides = [side_ids[s - 1] for s in d.sides.values()]
                w = type_map.get(d.weakness)
                if gi not in known and w is not None and w != d.weakness:
                    for sd in sides:
                        believed[sd] = w
                if (gi not in known and w is not None and w != d.weakness
                        and sides[0] not in assign):
                    exceptions += 1
            truth, _ = early_reachable(GRAPH, ap_items(items), tl, None, use_events=True,
                                       transport_matching=matching, ammo_amounts=AMMO,
                                       dock_assignments=believed, is_door_rando=True)
        if transport_on:
            for i, t in enumerate(trs, start=1):
                dest = tr_index[matching[t.id]] if t.id in matching else t.default_dest
                choices = list(t.choices.values())
                set_selector(L, f"transport_{i}", choices.index(dest) + 1)
        n_full, _ = reach_sets(L)

        if door_mode != "vanilla" or transport_on:
            exact_truth, _ = early_reachable(GRAPH, ap_items(items), tl, None,
                                             use_events=True,
                                             transport_matching=matching,
                                             ammo_amounts=AMMO, dock_assignments=assign,
                                             is_door_rando=door_mode != "vanilla")
            for gi in range(1, len(doors) + 1):
                set_selector(L, f"door_{gi}", None)
            for w in L.globals().GRAPH.door_change_from.values():
                set_selector(L, L.globals().DoorTypeCode(w), None)
            L.globals().SetDoorTruth(lua_table(L, assign))
            disc = L.globals().DISCOVERY
            disc.has_positions = False
            disc.seen = L.table()
            seen_keys = L.table()
            cells: dict[str, dict[str, int]] = {}
            for d in doors:
                scenario, cam = list(d.rooms.values())[0].split(":", 1)
                x, y = d.pos[1], d.pos[2]
                cells.setdefault(scenario, {})[f"{cam}:{int(x // 250)}:{int(y // 250)}"] = 1
                seen_keys[f"seen_{scenario}"] = scenario
            disc.seen_keys = seen_keys
            for scenario, value in cells.items():
                L.globals().OnDataStorage(f"seen_{scenario}", lua_table(L, value))
            if transport_on:
                for i in range(1, len(trs) + 1):
                    set_selector(L, f"transport_{i}", None)
                L.globals().SetTransportTruth(lua_table(L, matching))
                room = {t.id: t.room for t in trs}
                rides = {f"{room[a]}>{room[b]}": 1 for a, b in matching.items()}
                rides["s010_cave:collision_camera_000>s040_aqua:collision_camera_001"] = 1
                L.globals().DISCOVERY.rides_key = "rides"
                L.globals().OnDataStorage("rides", lua_table(L, rides))
            n_disc, _ = reach_sets(L)
            if n_disc != exact_truth:
                failures += 1
                print(f"[seed {seed}] DISCOVERY MISMATCH: lua-only={len(n_disc - exact_truth)} "
                      f"apworld-only={len(exact_truth - n_disc)}")

        if n_full != truth:
            failures += 1
            print(f"[seed {seed}] MISMATCH ({door_mode}, transports={transport_on}): "
                  f"lua-only={len(n_full - truth)} apworld-only={len(truth - n_full)}")
        else:
            print(f"[seed {seed}] ok  {door_mode:10s} transports={str(transport_on):5s} "
                  f"reach={len(truth):4d} unknown-normal={len(n_unknown):4d} "
                  f"relaxed={len(r_unknown):4d} known-vanilla={len(known)}"
                  + (f" type-exceptions={exceptions}" if door_mode == "types" else ""))
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=24)
    raise SystemExit(run(ap.parse_args().seeds))
