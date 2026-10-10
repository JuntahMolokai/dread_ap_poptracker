CUR_INDEX = -1
SLOT_DATA = nil
PROG_COUNT = {}

local function reset_items()
    for _, row in pairs(PACK_DATA.item_ids) do
        local codes = {}
        if row.kind == "progressive" then
            codes = row.tiers
        elseif row.kind == "dna" then
            codes = {"metroid_dna"}
        else
            codes = {row.code}
        end
        for _, code in ipairs(codes) do
            local obj = Tracker:FindObjectForCode(code)
            if obj then
                if obj.Type == "consumable" then
                    obj.AcquiredCount = 0
                else
                    obj.Active = false
                end
            end
        end
    end
    PROG_COUNT = {}
end

local function reset_locations()
    for _, path in pairs(PACK_DATA.location_paths) do
        local sec = Tracker:FindObjectForCode(path)
        if sec then
            sec.AvailableChestCount = sec.ChestCount
        end
    end
end

local function reset_discoveries()
    for gi = 1, PACK_DATA.n_doors do
        SelectorSet("door_" .. gi, nil)
    end
    for _, w in ipairs(GRAPH.door_change_from) do
        SelectorSet(DoorTypeCode(w), nil)
    end
    ResetTransportSync()
    for i = 1, PACK_DATA.n_transports do
        SelectorSet("transport_" .. i, nil)
    end
end

-- 31-bit string hash; stored in a hidden counter so we can tell whether a
-- (re)connect is the same seed+slot and keep the player's door / transport
-- notes, or a new seed and clear them.
local function hash(s)
    local h = 5381
    for i = 1, #s do
        h = (h * 33 + string.byte(s, i)) % 2147483647
    end
    return h
end

local function apply_options(slot_data)
    local ut = slot_data.ut_state or {}
    local opts = ut.options or {}
    local o = {}
    for k, v in pairs(PACK_DATA.option_defaults) do
        o[k] = v
    end
    for k, v in pairs(opts) do
        if type(v) == "number" or type(v) == "boolean" then
            o[k] = (v == true and 1) or (v == false and 0) or v
        end
    end
    if slot_data.required_artifacts ~= nil then
        o.required_artifacts = slot_data.required_artifacts
    end
    SETTINGS.options = o

    if type(opts.doors_to_change) == "table" then
        local s = {}
        for _, w in pairs(opts.doors_to_change) do
            s[w] = true
        end
        SETTINGS.doors_to_change = s
    else
        SETTINGS.doors_to_change = nil
    end

    SETTINGS.tricks = {}
    for _, short in ipairs(PACK_DATA.tricks) do
        local lvl = (slot_data.trick_levels or {})[short]
        if lvl == nil then
            lvl = o.trick_level or 1
        end
        SETTINGS.tricks[short] = lvl
        local obj = Tracker:FindObjectForCode("trick_" .. string.lower(short))
        if obj then
            obj.AcquiredCount = lvl
        end
    end

    local sc = ut.start_comp
    if type(sc) == "number" and sc >= 0 and sc < GRAPH.n_comps then
        SETTINGS.start_comp = sc
    else
        if sc ~= nil then
            print(string.format("Dread: start_comp %s out of range for this pack's graph "
                .. "(pack graph randovania %s); using the default start", tostring(sc),
                GRAPH.pinned_commit))
        end
        SETTINGS.start_comp = GRAPH.start_comp
    end
    SETTINGS.start_extra_items = ut.start_extra_items or {}
    SETTINGS.connected = true

    ComputeKnownVanillaDoors(ut.transport_matching)
end

local function load_existing_locations()
    local set = nil
    if Archipelago.MissingLocations or Archipelago.CheckedLocations then
        set = {}
        for _, id in ipairs(Archipelago.MissingLocations or {}) do
            set[id] = true
        end
        for _, id in ipairs(Archipelago.CheckedLocations or {}) do
            set[id] = true
        end
    end
    SETTINGS.existing_locations = set
end

function OnClear(slot_data)
    SLOT_DATA = slot_data or {}
    CUR_INDEX = -1
    Tracker.BulkUpdate = true
    local new_seed = false
    local ok, err = pcall(function()
        reset_items()
        reset_locations()

        local NOTES_VERSION = 2
        local seed_key = hash(tostring(Archipelago.Seed or SLOT_DATA.seed_id or "")
            .. "/" .. tostring(Archipelago.PlayerNumber) .. "/v" .. NOTES_VERSION)
        local seed_obj = Tracker:FindObjectForCode("seed_hash")
        if seed_obj and seed_obj.AcquiredCount ~= seed_key then
            reset_discoveries()
            seed_obj.AcquiredCount = seed_key
            new_seed = true
        end

        apply_options(SLOT_DATA)
        load_existing_locations()
        StartDiscovery(SLOT_DATA)
        StartHints()
    end)
    Tracker.BulkUpdate = false
    if not ok then
        print("Dread OnClear error: " .. tostring(err))
    end
    TouchSettings()
    UpdateDnaOverlay()

    if new_seed and AutoEnabled("auto_maptab") then
        local sp = StartPoint()
        if sp then
            pcall(function() Tracker:UiHint("ActivateTab", sp.region) end)
        end
    end
end

function OnItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then
        return
    end
    CUR_INDEX = index
    local row = PACK_DATA.item_ids[item_id]
    if not row then
        return
    end
    if row.kind == "toggle" then
        local obj = Tracker:FindObjectForCode(row.code)
        if obj then
            obj.Active = true
        end
    elseif row.kind == "count" or row.kind == "dna" then
        local obj = Tracker:FindObjectForCode(row.code or "metroid_dna")
        if obj then
            obj.AcquiredCount = obj.AcquiredCount + 1
        end
    elseif row.kind == "progressive" then
        -- World.collect: the k-th copy of a progressive grants the k-th tier.
        local k = (PROG_COUNT[row.name] or 0) + 1
        PROG_COUNT[row.name] = k
        local code = row.tiers[k]
        if code then
            local obj = Tracker:FindObjectForCode(code)
            if obj then
                obj.Active = true
            end
        end
    end
end

function OnLocation(location_id, location_name)
    local path = PACK_DATA.location_paths[location_id]
    if not path then
        return
    end
    local sec = Tracker:FindObjectForCode(path)
    if sec then
        sec.AvailableChestCount = 0
    end
end

Archipelago:AddClearHandler("dread_clear", OnClear)
Archipelago:AddItemHandler("dread_item", OnItem)
Archipelago:AddLocationHandler("dread_location", OnLocation)
