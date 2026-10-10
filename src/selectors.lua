-- Door, door-type and transport selectors, built at load from GRAPH instead
-- of being spelled out in item JSON (one entry per possible choice).
--
--   door_<gi>              one per randomizable door; choices = door_choices
--   doortype_<weakness>    one per vanilla door type (Door Types mode)
--   transport_<i>          one per elevator / shuttle endpoint; choices are
--                          the other endpoints of the same kind
--
-- SelectorGet / SelectorSet are the only way the rest of the pack touches
-- them.

SELECTORS = {}

local function door_icon(weakness)
    return "images/doors/" .. string.lower(weakness):gsub(" ", "_") .. ".png"
end

local function short(weakness)
    return PACK_DATA.door_short[weakness] or weakness
end

-- spec: code, title, choices (list of {label, icon}), unknown_icon,
-- unknown_mods (optional icon mods while unknown).
local function create_selector(spec)
    local item = ScriptHost:CreateLuaItem()
    local n = #spec.choices
    item.ItemState = {stage = 0}

    local function refresh()
        local st = item.ItemState.stage
        if st > 0 then
            item.Name = spec.title .. ": " .. spec.choices[st].label
            item.Icon = ImageReference:FromPackRelativePath(spec.choices[st].icon)
            item.IconMods = "none"
        else
            item.Name = spec.title .. ": unknown"
            item.Icon = ImageReference:FromPackRelativePath(spec.unknown_icon)
            item.IconMods = spec.unknown_mods or "none"
        end
    end

    local function set_stage(st)
        if st < 0 or st > n then
            st = 0
        end
        item:Set("stage", st)      -- fires PopTracker's change signal
        refresh()
    end

    item.PotentialCodes = {spec.code}
    item.CanProvideCodeFunc = function(_, code)
        return code == spec.code
    end
    item.ProvidesCodeFunc = function(_, code)
        if code == spec.code and item.ItemState.stage > 0 then
            return 1
        end
        return 0
    end
    item.OnLeftClickFunc = function(_)
        set_stage((item.ItemState.stage + 1) % (n + 1))
    end
    item.OnRightClickFunc = function(_)
        set_stage((item.ItemState.stage - 1) % (n + 1))
    end
    item.SaveFunc = function(_)
        return {stage = item.ItemState.stage}
    end
    item.LoadFunc = function(_, data)
        set_stage(type(data) == "table" and tonumber(data.stage) or 0)
    end
    refresh()
    SELECTORS[spec.code] = {item = item, set = set_stage}
    return item
end

-- Selected choice index (1-based), or nil while the selector is unknown.
function SelectorGet(code)
    local sel = SELECTORS[code]
    if sel then
        local st = sel.item.ItemState.stage
        return st > 0 and st or nil
    end
    -- Fallback for stand-ins (tests) that expose stage via :Get.
    local obj = Tracker:FindObjectForCode(code)
    if obj and obj.Get then
        local st = obj:Get("stage") or 0
        return st > 0 and st or nil
    end
    return nil
end

-- Select choice index idx (1-based), or set unknown with nil.
function SelectorSet(code, idx)
    local sel = SELECTORS[code]
    if sel then
        sel.set(idx or 0)
        return true
    end
    local obj = Tracker:FindObjectForCode(code)
    if obj and obj.Set then
        obj:Set("stage", idx or 0)
        return true
    end
    return false
end

function CreateSelectors()
    local door_choices = {}
    for _, w in ipairs(PACK_DATA.door_choices) do
        door_choices[#door_choices + 1] = {label = short(w) .. " door", icon = door_icon(w)}
    end

    for gi, d in ipairs(GRAPH.doors) do
        create_selector({
            code = "door_" .. gi,
            title = "Door: " .. d.label,
            choices = door_choices,
            unknown_icon = door_icon("Unknown"),
        })
    end

    for _, w in ipairs(GRAPH.door_change_from) do
        local choices = {}
        for _, t in ipairs(PACK_DATA.door_choices) do
            choices[#choices + 1] = {label = short(t), icon = door_icon(t)}
        end
        create_selector({
            code = DoorTypeCode(w),
            title = short(w) .. " doors become",
            choices = choices,
            -- Unknown shows the vanilla type, dimmed, so the tab reads as a
            -- legend of which type each selector is for.
            unknown_icon = door_icon(w),
            unknown_mods = "brightness|0.6",
        })
    end

    for i, t in ipairs(GRAPH.transports) do
        local choices = {}
        for _, j in ipairs(t.choices) do
            choices[#choices + 1] = {label = GRAPH.transports[j].label,
                                     icon = "images/transports/" .. t.kind .. ".png"}
        end
        create_selector({
            code = "transport_" .. i,
            title = t.label .. " goes to",
            choices = choices,
            unknown_icon = "images/transports/unknown.png",
        })
    end
end
