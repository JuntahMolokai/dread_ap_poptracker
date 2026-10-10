"""Load the whole pack under Lua 5.4 with a PopTracker API stub and drive it the
way PopTracker + an AP server would: init.lua, OnClear(slot_data), items,
locations, and every access / visibility rule in locations/*.json.

Catches Lua runtime errors and wiring mistakes (unknown codes, bad rule names)
without a PopTracker build. Usage:  python gen/tests/pack_sim_test.py
Requires: pip install lupa
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lupa.lua54 as lupa

PACK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACK / "gen"))
from dread_data import DREAD_AP  # noqa: E402

STUB = r"""
AccessibilityLevel = {None=0, Partial=1, Inspect=3, SequenceBreak=5, Normal=6, Cleared=7}
Highlight = {Avoid=-1, None=0, NoPriority=1, Unspecified=2, Priority=3}
PopVersion = "0.34.0"
local watches = {}
local items = {}
local by_code = {}
local sections = {}

local function fire(obj)
    for _, w in ipairs(watches) do
        if w.code == "*" or obj._codes[w.code] then
            w.cb(w.code)
        end
    end
end

local function make_item(def)
    local raw = {Type = def.type, Name = def.name, Active = false, CurrentStage = 0,
                 AcquiredCount = def.initial_quantity or 0, _codes = {}, _def = def}
    local codes = {}
    if def.codes then
        for c in string.gmatch(def.codes, "[^,]+") do codes[#codes + 1] = c end
    end
    for _, st in ipairs(def.stages or {}) do
        for c in string.gmatch(st.codes or "", "[^,]+") do codes[#codes + 1] = c end
    end
    for _, c in ipairs(codes) do
        raw._codes[c] = true
        by_code[c] = by_code[c] or {}
        table.insert(by_code[c], nil)
    end
    if def.type == "progressive" and def.allow_disabled == false then raw.Active = true end
    if def.initial_active_state then raw.Active = true end
    local selector = def.type == "progressive" and def.allow_disabled ~= false
    raw._stage2 = 0
    local obj = setmetatable({}, {
        __index = function(_, k)
            if k == "SetOverlay" then return function(self, s) raw.Overlay = s end end
            if k == "SetOverlayColor" then return function(self, c) raw.OverlayColor = c end end
            if selector and k == "CurrentStage" then
                return raw.Active and raw._stage2 + 1 or 0
            end
            if selector and k == "DisplayedStage" then   -- what the player sees
                return raw.Active and def.stages[raw._stage2 + 1].name or "unknown"
            end
            return raw[k]
        end,
        __newindex = function(_, k, v)
            if selector and k == "CurrentStage" then
                local on, st = v > 0, math.max(0, math.min(v - 1, #def.stages - 1))
                if v <= 0 then st = 0 end
                if raw.Active ~= on or raw._stage2 ~= st then
                    raw.Active, raw._stage2 = on, st; fire(raw)
                end
                return
            end
            if selector and k == "Active" and not v then raw._stage2 = 0 end
            if raw[k] ~= v then raw[k] = v; fire(raw) end
        end,
    })
    for _, c in ipairs(codes) do
        local l = by_code[c]
        l[#l + 1] = obj
    end
    items[#items + 1] = obj
    return obj
end

Tracker = {ActiveVariantUID = "standard", BulkUpdate = false}
UI_HINTS = {}
function Tracker:UiHint(name, value) UI_HINTS[#UI_HINTS + 1] = name .. "=" .. value end
function Tracker:AddItems(path)
    for _, def in ipairs(load_json(path)) do make_item(def) end
    return true
end
function Tracker:AddMaps(path) load_json(path) return true end
function Tracker:AddLayouts(path) load_json(path) return true end
LOCATIONS = {}
function Tracker:AddLocations(path)
    for _, top in ipairs(load_json(path)) do
        for _, child in ipairs(top.children) do
            local id = top.name .. "/" .. child.name
            LOCATIONS[#LOCATIONS + 1] = child
            for _, sec in ipairs(child.sections) do
                local count = sec.item_count or 1
                sections["@" .. id .. "/" .. sec.name] = {ChestCount = count, AvailableChestCount = count}
            end
        end
    end
    return true
end
function Tracker:FindObjectForCode(code)
    if string.sub(code, 1, 1) == "@" then return sections[code] end
    local l = by_code[code]
    return l and l[1] or nil
end
function Tracker:ProviderCountForCode(code)
    local n = 0
    for _, obj in ipairs(by_code[code] or {}) do
        local t = obj.Type
        if t == "custom" then
            n = n + obj.ProvidesCodeFunc(obj, code)
        elseif t == "consumable" then
            n = n + obj.AcquiredCount
        elseif obj.Active then
            n = n + 1
        end
    end
    return n
end
ScriptHost = {}
function ScriptHost:LoadScript(path) run_file(path) end
ImageReference = {}
function ImageReference:FromPackRelativePath(p) return p end
function ScriptHost:CreateLuaItem()
    local raw = {Type = "custom", _codes = {}}
    local obj
    obj = setmetatable({}, {
        __index = function(_, k)
            if k == "Get" then
                return function(self, key) return raw.ItemState[key] end
            elseif k == "Set" then
                return function(self, key, v)
                    if raw.ItemState[key] ~= v then raw.ItemState[key] = v; fire(raw) end
                end
            end
            return raw[k]
        end,
        __newindex = function(_, k, v)
            raw[k] = v
            if k == "PotentialCodes" then
                for _, c in ipairs(v) do
                    raw._codes[c] = true
                    by_code[c] = by_code[c] or {}
                    table.insert(by_code[c], obj)
                end
            end
        end,
    })
    items[#items + 1] = obj
    return obj
end
function ScriptHost:AddWatchForCode(name, code, cb)
    watches[#watches + 1] = {name = name, code = code, cb = cb}
end
Archipelago = {PlayerNumber = 1, TeamNumber = 0, Seed = "SIMSEED", handlers = {}, notify = {}}
function Archipelago:SetNotify(keys) for _, k in ipairs(keys) do self.notify[#self.notify + 1] = k end end
function Archipelago:Get(keys) end
Archipelago.registered = {}
for _, h in ipairs({"Clear", "Item", "Location", "Scout", "Bounced", "Retrieved", "SetReply"}) do
    Archipelago.registered[h] = {}
    Archipelago.handlers[h] = function(...)
        for _, cb in ipairs(Archipelago.registered[h]) do cb(...) end
    end
    Archipelago["Add" .. h .. "Handler"] = function(self, name, cb)
        table.insert(self.registered[h], cb)
    end
end
"""


def to_lua(L, v):
    if isinstance(v, dict):
        t = L.table()
        for k, x in v.items():
            t[k] = to_lua(L, x)
        return t
    if isinstance(v, list):
        t = L.table()
        for i, x in enumerate(v, start=1):
            t[i] = to_lua(L, x)
        return t
    return v


def main() -> int:
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = L.globals()
    g.load_json = lambda p: to_lua(L, json.loads((PACK / p).read_text(encoding="utf-8")))
    g.run_file = lambda p: L.execute((PACK / p).read_text(encoding="utf-8"))
    L.execute(STUB)
    L.execute((PACK / "scripts" / "init.lua").read_text(encoding="utf-8"))
    errors = 0

    bad = [c for c in g.PACK_DATA.counter_codes.values()
           if g.Tracker.FindObjectForCode(g.Tracker, c).OverlayColor != ""
           or g.Tracker.FindObjectForCode(g.Tracker, c)._def.overlay_background != "#000000"]
    print(f"counters: {len(list(g.PACK_DATA.counter_codes.values()))}, "
          f"not default colour on dark box: {bad}")
    if bad:
        errors += 1

    def eval_rule(rule: str):
        rule = rule.lstrip("^").lstrip("$")
        name, *args = rule.split("|")
        fn = g[name]
        if fn is None:
            raise RuntimeError(f"rule function {name} missing")
        return fn(*args)

    def sweep(label: str):
        nonlocal errors
        counts = {}
        for child in g.LOCATIONS.values():
            for key in ("access_rules", "visibility_rules"):
                for rule in (child[key] or {}).values():
                    try:
                        r = eval_rule(rule)
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        print(f"  ERROR {child.name}: {rule}: {exc}")
                        continue
                    if key == "access_rules":
                        counts[r] = counts.get(r, 0) + 1
            for sec in child.sections.values():
                for rule in (sec["visibility_rules"] or {}).values():
                    eval_rule(rule)
        pickups = [c for c in g.LOCATIONS.values() if not str(c.name).startswith(("Door ", "Transport", "Goal"))]
        lv = {}
        for c in pickups:
            r = eval_rule(c.access_rules[1])
            lv[r] = lv.get(r, 0) + 1
        print(f"{label}: pickup levels {dict(sorted(lv.items()))} (6=normal 5=seqbreak 0=none)")
        return lv

    sweep("offline, no items")

    slot = {
        "seed_id": "SIMSEED", "required_artifacts": 3,
        "trick_levels": {"Knowledge": 2, "Movement": 1},
        "ut_state": {
            "options": {"door_lock_rando": 1, "transport_rando": 1, "trick_level": 1,
                        "energy_per_tank": 100, "starting_missiles": 15,
                        "doors_to_change": ["Access Open", "Charge Beam Door", "Grapple Beam Door",
                                            "Missile Door", "Plasma Beam Door", "Power Beam Door",
                                            "Sensor Lock Door", "Super Missile Door",
                                            "Wave Beam Door", "Wide Beam Door"]},
            "dock_assignments": {}, "transport_matching": {},
            "start_comp": None, "start_extra_items": [],
        },
    }
    g.Archipelago.MissingLocations = to_lua(L, [31154, 31155])
    g.Archipelago.CheckedLocations = to_lua(L, [])
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    known = sum(1 for v in g.SETTINGS.known_vanilla.values() if v)
    print(f"connected: door mode {g.DoorMode()}, known-vanilla doors {known}, "
          f"tricks Knowledge={g.SETTINGS.tricks['Knowledge']}")
    sweep("connected, door+transport rando, no items")

    item_ids = json.loads((DREAD_AP / "apworld" / "dread" / "data"
                           / "items.json").read_text())
    by_name = {it["name"]: it["ap_id"] for it in item_ids}
    idx = 0
    for name in ["Slide", "Pulse Radar", "Missile Tank", "Progressive Beam", "Progressive Beam",
                 "Morph Ball", "Charge Beam", "Bomb", "Energy Tank", "Metroid DNA 1"]:
        g.Archipelago.handlers["Item"](idx, by_name[name], name, 1)
        idx += 1
    print("plasma tier active:", g.Tracker.FindObjectForCode(g.Tracker, "plasma_beam").Active,
          " wave tier:", g.Tracker.FindObjectForCode(g.Tracker, "wave_beam").Active,
          " dna overlay:", g.Tracker.FindObjectForCode(g.Tracker, "metroid_dna").Overlay)
    g.Archipelago.handlers["Location"](31154, "x")
    sec = g.Tracker.FindObjectForCode(g.Tracker, g.PACK_DATA.location_paths[31154])
    print("location cleared:", sec.AvailableChestCount == 0)
    sweep("connected, some items")

    dest = g.GRAPH.transports[1].choices[1]
    g.SelectorSet("transport_1", 1)
    back = g.TransportDest(dest)
    print(f"transport 1 -> {dest}; transport {dest} -> {back}")
    if back != 1:
        errors += 1
        print("  ERROR: reciprocal transport not set")

    g.SelectorSet("door_20", 3)
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    kept = g.SelectorGet("door_20") is not None
    g.Archipelago.Seed = "OTHER"
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    cleared = g.SelectorGet("door_20") is None
    print(f"door note kept on same-seed reconnect: {kept}; cleared on new seed: {cleared}")
    if not (kept and cleared):
        errors += 1

    hints = list(g.UI_HINTS.values())
    print("tab hints:", hints)
    if hints != ["ActivateTab=Artaria", "ActivateTab=Artaria"]:
        errors += 1
        print("  ERROR: unexpected tab hints")

    def visible_starts():
        return [str(c.name) for c in g.LOCATIONS.values()
                if str(c.name).startswith("Start:") and eval_rule(c.visibility_rules[1])]

    print("start pin (Artaria spawn):", visible_starts())
    burenia = next(sp for sp in g.GRAPH.start_points.values() if sp.region == "Burenia")
    slot["ut_state"]["start_comp"] = int(burenia.comp)
    g.Archipelago.Seed = "THIRD"
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    shown = visible_starts()
    last = list(g.UI_HINTS.values())[-1]
    print("start pin (Burenia spawn):", shown, " last hint:", last)
    if len(shown) != 1 or not shown[0].endswith(f"{burenia.label}") or last != "ActivateTab=Burenia":
        errors += 1
        print("  ERROR: start pin / tab for Burenia spawn")
    d20 = g.GRAPH.doors[20]
    side20 = g.GRAPH.sides[d20.door_side].id
    side21 = g.GRAPH.sides[g.GRAPH.doors[21].door_side].id
    slot["ut_state"]["dock_assignments"] = {side20: "Wave Beam Door", side21: "Missile Door"}
    slot["ut_state"]["start_comp"] = None
    g.Archipelago.Seed = "FOURTH"
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    print("subscribed keys:", list(g.Archipelago.notify.values())[-2:])
    room = d20.rooms[1]
    g.Archipelago.handlers["Retrieved"]("dread_visited_rooms_0_1", to_lua(L, {room: 1}))
    w20 = g.DoorWeakness(20)
    item20 = g.Tracker.FindObjectForCode(g.Tracker, "door_20")
    shown20 = (str(item20.Name).rsplit(": ", 1)[-1], item20.Icon)
    d21 = g.SelectorGet("door_21") is not None
    print(f"after visiting {room}: door 20 logic = {w20}, shown = {shown20!r}, "
          f"door 21 revealed = {d21}")
    if w20 != "Wave Beam Door" or shown20 != ("Wave door", "images/doors/wave_beam_door.png") or d21:
        errors += 1
        print("  ERROR: door discovery")
    g.SelectorSet("door_21", list(g.PACK_DATA.door_choices.values()).index("Grapple Beam Door") + 1)
    g.Archipelago.handlers["SetReply"]("dread_visited_rooms_0_1",
                                       to_lua(L, {room: 1, g.GRAPH.doors[21].rooms[1]: 1}), None)
    if g.DoorWeakness(21) != "Grapple Beam Door":
        errors += 1
        print("  ERROR: manual lock overwritten:", g.DoorWeakness(21))
    d30 = g.GRAPH.doors[30]
    slot["ut_state"]["dock_assignments"] = {g.GRAPH.sides[d30.door_side].id: "Wave Beam Door"}
    g.Archipelago.Seed = "POSITIONS"
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    scenario, cam = d30.rooms[1].split(":", 1)
    x, y = d30.pos[1], d30.pos[2]
    key = f"dread_seen_0_1_{scenario}"
    far = {f"{cam}:{int((x + 4000) // 250)}:{int(y // 250)}": 1}
    g.Archipelago.handlers["Retrieved"](key, to_lua(L, far))
    far_known = g.SelectorGet("door_30") is not None
    near = dict(far, **{f"{cam}:{int((x - 700) // 250)}:{int((y + 300) // 250)}": 1})
    g.Archipelago.handlers["SetReply"](key, to_lua(L, near), None)
    near_lock = g.DoorWeakness(30)
    print(f"door 30 ({d30.label}): 4000 units away known={far_known}; "
          f"on screen -> {near_lock}")
    if far_known or near_lock != "Wave Beam Door":
        errors += 1
        print("  ERROR: position-based door discovery")

    hint_key = "_read_hints_0_1"
    def hint(loc, status, finder=1, found=False):
        return {"class": "Hint", "receiving_player": 3, "finding_player": finder,
                "location": loc, "item": 1, "found": found, "entrance": "",
                "item_flags": 1, "status": status}
    def hl(loc):
        return g.Tracker.FindObjectForCode(g.Tracker, g.PACK_DATA.location_paths[loc]).Highlight
    g.Archipelago.handlers["Retrieved"](hint_key, to_lua(L, [
        hint(31154, 0), hint(31155, 30), hint(31156, 40, found=True),
        hint(31157, 20), hint(31158, 30, finder=3)]))
    got = [hl(i) for i in (31154, 31155, 31156, 31157, 31158)]
    print("hint highlights (unspec, priority, found, avoid, other slot):", got)
    if got != [3, 3, 0, -1, None]:
        errors += 1
        print("  ERROR: hint highlights")
    g.Archipelago.handlers["SetReply"](hint_key, to_lua(L, [hint(31155, 30)]), None)
    if hl(31154) != 0 or hl(31155) != 3:
        errors += 1
        print("  ERROR: removed hint not cleared")

    n = len(list(g.UI_HINTS.values()))
    for v in ("s030_baselab:", "s030_baselab:collision_camera_000", "s040_aqua:collision_camera_003"):
        g.Archipelago.handlers["SetReply"]("dread_current_room_0_1", v, None)
    new_hints = list(g.UI_HINTS.values())[n:]
    print("region hints:", new_hints)
    if new_hints != ["ActivateTab=Dairon", "ActivateTab=Burenia"]:
        errors += 1
        print("  ERROR: region follow")
    trs = list(g.GRAPH.transports.values())
    a, b = trs[0], next(t for t in trs if t.kind == trs[0].kind and t.id != trs[0].id
                        and t.id != g.GRAPH.transports[trs[0].default_dest].id)
    other = next(t for t in trs if t.kind == a.kind and t.id not in (a.id, b.id))
    slot["ut_state"]["transport_matching"] = {a.id: b.id, b.id: a.id}
    g.Archipelago.Seed = "FIFTH"
    g.Archipelago.handlers["Clear"](to_lua(L, slot))
    idx = {t.id: i for i, t in enumerate(trs, start=1)}
    ia, ib, io = idx[a.id], idx[b.id], idx[other.id]
    g.Archipelago.handlers["Retrieved"]("dread_rides_0_1", to_lua(L, {
        f"{a.room}>{other.room}": 1,          # not the real matching: ignored
    }))
    print(f"false pair -> transport {ia} known: {g.TransportDest(ia) is not None}")
    g.Archipelago.handlers["SetReply"]("dread_rides_0_1", to_lua(L, {
        f"{a.room}>{other.room}": 1, f"{a.room}>{b.room}": 1}), None)
    print(f"ride {a.label} -> {b.label}: dest {g.TransportDest(ia)} (want {ib}), "
          f"return {g.TransportDest(ib)} (want {ia})")
    if g.TransportDest(ia) != ib or g.TransportDest(ib) != ia or g.TransportDest(io) is not None:
        errors += 1
        print("  ERROR: transport discovery")

    item = g.Tracker.FindObjectForCode(g.Tracker, "door_40")
    n_choices = len(list(g.PACK_DATA.door_choices.values()))
    g.SelectorSet("door_40", None)
    item.OnLeftClickFunc(item)
    after_left = (g.SelectorGet("door_40"), str(item.Name).rsplit(": ", 1)[-1])
    g.SelectorSet("door_40", None)
    item.OnRightClickFunc(item)
    after_right = g.SelectorGet("door_40")
    item.OnLeftClickFunc(item)
    wrapped = g.SelectorGet("door_40")
    saved = item.SaveFunc(item)
    g.SelectorSet("door_40", 2)
    item.LoadFunc(item, saved)
    print(f"clicks: left from unknown -> {after_left}; right from unknown -> {after_right}; "
          f"left past last -> {wrapped}; save/load -> {g.SelectorGet('door_40')}; "
          f"provides while unknown: {g.Tracker.ProviderCountForCode(g.Tracker, 'door_40')}")
    if (after_left != (1, "Power door") or after_right != n_choices or wrapped is not None
            or g.SelectorGet("door_40") is not None
            or g.Tracker.ProviderCountForCode(g.Tracker, "door_40") != 0):
        errors += 1
        print("  ERROR: selector clicks / save")

    def toggle(code, on):
        g.Tracker.FindObjectForCode(g.Tracker, code).Active = on
    slot["ut_state"]["dock_assignments"] = {side20: "Wave Beam Door"}
    g.Archipelago.Seed = "TOGGLES"
    for code in ("auto_doors", "auto_transports", "auto_maptab"):
        toggle(code, False)
    n_hints = len(list(g.UI_HINTS.values()))
    g.Archipelago.handlers["Clear"](to_lua(L, slot))       # new seed, map tab off
    g.Archipelago.handlers["Retrieved"]("dread_visited_rooms_0_1", to_lua(L, {room: 1}))
    g.Archipelago.handlers["Retrieved"]("dread_rides_0_1", to_lua(L, {f"{a.room}>{b.room}": 1}))
    g.Archipelago.handlers["Retrieved"]("dread_current_room_0_1", "s040_aqua:collision_camera_003")
    off = (g.SelectorGet("door_20"), g.TransportDest(ia), list(g.UI_HINTS.values())[n_hints:])
    print("toggles off -> door 20, transport, tab hints:", off)
    for code in ("auto_doors", "auto_transports", "auto_maptab"):
        toggle(code, True)
    on = (g.DoorWeakness(20), g.TransportDest(ia), list(g.UI_HINTS.values())[n_hints:])
    print("toggles on  -> door 20, transport, tab hints:", on)
    if off != (None, None, []) or on != ("Wave Beam Door", ib, ["ActivateTab=Burenia"]):
        errors += 1
        print("  ERROR: settings toggles")
    print("ERRORS:", errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
