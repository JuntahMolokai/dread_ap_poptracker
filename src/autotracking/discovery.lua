-- In-game discovery, fed by the Dread client (dread_ap DreadContext._publish_room)
-- through AP DataStorage:
--   dread_visited_rooms_<team>_<slot>  {"scenario:collision_camera": 1, ...}
--   dread_current_room_<team>_<slot>   "live_scenario:collision_camera"
--   dread_rides_<team>_<slot>          {"scenario:cam>scenario:cam": 1, ...}
--   dread_seen_<team>_<slot>_<scenario> {"cam:cx:cy": 1, ...}  250-unit cells
--                                      Samus has stood in, per room

DISCOVERY = {visited = {}, truth = {}, transport_truth = {}, region = nil,
             rooms_key = nil, current_key = nil, rides_key = nil,
             seen = {}, seen_keys = {}, has_positions = false}

-- One screen around Samus, in world units (half-extents), plus half a feed
-- cell of slack since positions arrive quantized to 250-unit cells.
local SEEN_CELL = 250
local VIEW_HALF_W = 1050 + SEEN_CELL / 2
local VIEW_HALF_H = 600 + SEEN_CELL / 2

local function door_seen(d)
    if DISCOVERY.has_positions then
        local x, y = d.pos[1], d.pos[2]
        for _, room in ipairs(d.rooms) do
            local scenario, cam = string.match(room, "^([^:]*):(.*)$")
            local cells = (DISCOVERY.seen[scenario] or {})[cam]
            if cells then
                for _, c in ipairs(cells) do
                    if math.abs(c[1] - x) <= VIEW_HALF_W
                            and math.abs(c[2] - y) <= VIEW_HALF_H then
                        return true
                    end
                end
            end
        end
        return false
    end
    for _, room in ipairs(d.rooms) do
        if DISCOVERY.visited[room] then
            return true
        end
    end
    return false
end

function SetDoorTruth(dock_assignments)
    local truth = {}
    for gi, d in ipairs(GRAPH.doors) do
        local sid = GRAPH.sides[d.door_side].id
        local w = dock_assignments and dock_assignments[sid]
        if w then
            truth[gi] = {weakness = w, assigned = true}
        else
            truth[gi] = {weakness = d.weakness, assigned = false}
        end
    end
    DISCOVERY.truth = truth
end

function SetTransportTruth(matching)
    local by_id = {}
    for i, t in ipairs(GRAPH.transports) do
        by_id[t.id] = i
    end
    local truth = {}
    if matching then
        for i, t in ipairs(GRAPH.transports) do
            local dest = matching[t.id]
            if dest and by_id[dest] then
                truth[i] = by_id[dest]
            end
        end
    end
    DISCOVERY.transport_truth = truth
end

local function set_if_unknown(code, weakness)
    if SelectorGet(code) ~= nil then
        return false
    end
    for k, w in ipairs(PACK_DATA.door_choices) do
        if w == weakness then
            return SelectorSet(code, k)
        end
    end
    return false
end

function AutoEnabled(code)
    return Tracker:ProviderCountForCode(code) > 0
end

function ApplyDoorDiscoveries()
    if DoorMode() == "vanilla" then
        return
    end
    if not AutoEnabled("auto_doors") then
        SETTINGS.door_exact = {}
        SETTINGS.discovered_vanilla = {}
        TouchSettings()
        return
    end
    local exact = {}
    local exceptions = {}
    Tracker.BulkUpdate = true
    local ok, err = pcall(function()
        for gi, d in ipairs(GRAPH.doors) do
            local t = DISCOVERY.truth[gi]
            if t and not SETTINGS.known_vanilla[gi] then
                if door_seen(d) then
                    if t.assigned and t.weakness == d.weakness then
                        exact[gi] = true
                    end
                    if DoorMode() == "types" then
                        if t.assigned then
                            set_if_unknown(DoorTypeCode(d.weakness), t.weakness)
                        else
                            exceptions[gi] = true
                        end
                    else
                        set_if_unknown("door_" .. gi, t.weakness)
                    end
                end
            end
        end
    end)
    Tracker.BulkUpdate = false
    if not ok then
        print("Dread door discovery error: " .. tostring(err))
    end
    SETTINGS.door_exact = exact
    SETTINGS.discovered_vanilla = exceptions
    TouchSettings()
end

local function on_seen_cells(scenario, value)
    local by_cam = {}
    if type(value) == "table" then
        for cell, _ in pairs(value) do
            local cam, cx, cy = string.match(cell, "^(.*):(-?%d+):(-?%d+)$")
            if cam then
                local l = by_cam[cam]
                if not l then
                    l = {}
                    by_cam[cam] = l
                end
                l[#l + 1] = {tonumber(cx) * SEEN_CELL + SEEN_CELL / 2,
                             tonumber(cy) * SEEN_CELL + SEEN_CELL / 2}
                DISCOVERY.has_positions = true
            end
        end
    end
    DISCOVERY.seen[scenario] = by_cam
    ApplyDoorDiscoveries()
end

local function on_visited_rooms(value)
    local visited = {}
    if type(value) == "table" then
        for room, _ in pairs(value) do
            visited[room] = true
        end
    end
    DISCOVERY.visited = visited
    ApplyDoorDiscoveries()
end

local function transport_dest_of(i)
    local st = SelectorGet("transport_" .. i)
    return st and GRAPH.transports[i].choices[st] or nil
end

local function reveal_ride(i, j)
    if transport_dest_of(i) ~= nil then
        return
    end
    local b_dest = transport_dest_of(j)
    if b_dest ~= nil and b_dest ~= i then
        return 
    end
    for k, c in ipairs(GRAPH.transports[i].choices) do
        if c == j then
            SelectorSet("transport_" .. i, k)
            return
        end
    end
end

local function on_rides(value)
    DISCOVERY.rides_value = value
    if type(value) ~= "table" or not TransportRandoOn()
            or not AutoEnabled("auto_transports") then
        return
    end
    local at_room = {}
    for i, t in ipairs(GRAPH.transports) do
        local l = at_room[t.room]
        if not l then
            l = {}
            at_room[t.room] = l
        end
        l[#l + 1] = i
    end
    local truth = DISCOVERY.transport_truth
    for pair, _ in pairs(value) do
        local from, to = string.match(pair, "^(.-)>(.*)$")
        for _, i in ipairs(at_room[from] or {}) do
            for _, j in ipairs(at_room[to] or {}) do
                if truth[i] == j then
                    reveal_ride(i, j)
                end
            end
        end
    end
    TouchSettings()
end

local function on_current_room(value)
    DISCOVERY.current_value = value
    if type(value) ~= "string" or not AutoEnabled("auto_maptab") then
        return
    end
    local scenario = value:match("^([^:]*)")
    local region = GRAPH.scenario_region[scenario]
    if region and region ~= DISCOVERY.region then
        DISCOVERY.region = region
        pcall(function() Tracker:UiHint("ActivateTab", region) end)
    end
end

function StartDiscovery(slot_data)
    DISCOVERY.visited = {}
    DISCOVERY.region = nil
    DISCOVERY.rides_value = nil
    DISCOVERY.current_value = nil
    SETTINGS.door_exact = {}
    SETTINGS.discovered_vanilla = {}
    local ut = slot_data.ut_state or {}
    SetDoorTruth(ut.dock_assignments)
    SetTransportTruth(ut.transport_matching)
    local team = Archipelago.TeamNumber or 0
    if team < 0 then
        team = 0
    end
    local slot = Archipelago.PlayerNumber
    DISCOVERY.rooms_key = string.format("dread_visited_rooms_%d_%d", team, slot)
    DISCOVERY.current_key = string.format("dread_current_room_%d_%d", team, slot)
    DISCOVERY.rides_key = string.format("dread_rides_%d_%d", team, slot)
    local keys = {DISCOVERY.rooms_key, DISCOVERY.current_key, DISCOVERY.rides_key}
    DISCOVERY.seen = {}
    DISCOVERY.seen_keys = {}
    DISCOVERY.has_positions = false
    for scenario, _ in pairs(GRAPH.scenario_region) do
        local k = string.format("dread_seen_%d_%d_%s", team, slot, scenario)
        DISCOVERY.seen_keys[k] = scenario
        keys[#keys + 1] = k
    end
    Archipelago:SetNotify(keys)
    Archipelago:Get(keys)
end

ScriptHost:AddWatchForCode("auto_doors_toggle", "auto_doors", function(_)
    ApplyDoorDiscoveries()
end)
ScriptHost:AddWatchForCode("auto_transports_toggle", "auto_transports", function(_)
    on_rides(DISCOVERY.rides_value)
end)
ScriptHost:AddWatchForCode("auto_maptab_toggle", "auto_maptab", function(_)
    DISCOVERY.region = nil
    on_current_room(DISCOVERY.current_value)
end)

function OnDataStorage(key, value)
    if key == DISCOVERY.rooms_key then
        on_visited_rooms(value)
    elseif key == DISCOVERY.current_key then
        on_current_room(value)
    elseif key == DISCOVERY.rides_key then
        on_rides(value)
    elseif DISCOVERY.seen_keys[key] then
        on_seen_cells(DISCOVERY.seen_keys[key], value)
    end
end

Archipelago:AddRetrievedHandler("dread_retrieved", function(key, value)
    OnDataStorage(key, value)
end)
Archipelago:AddSetReplyHandler("dread_set_reply", function(key, value, _old)
    OnDataStorage(key, value)
end)
