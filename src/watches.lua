-- Item watches: logic invalidation, transport return trips, DNA overlay.

function TouchSettings()
    MarkLogicDirty()
    local obj = Tracker:FindObjectForCode("settings_rev")
    if obj then
        obj.AcquiredCount = obj.AcquiredCount + 1
    end
end

COUNTER_COLOR = ""

function ApplyCounterColors()
    for _, code in ipairs(PACK_DATA.counter_codes) do
        local obj = Tracker:FindObjectForCode(code)
        if obj then
            pcall(function() obj:SetOverlayColor(COUNTER_COLOR) end)
        end
    end
end

if ScriptHost.AddOnFrameHandler then
    ScriptHost:AddOnFrameHandler("counter_colors_once", function()
        ApplyCounterColors()
        UpdateDnaOverlay()
        if ScriptHost.RemoveOnFrameHandler then
            ScriptHost:RemoveOnFrameHandler("counter_colors_once")
        end
    end)
end

function UpdateDnaOverlay()
    local obj = Tracker:FindObjectForCode("metroid_dna")
    if obj then
        local need = SETTINGS.options.required_artifacts or 0
        obj:SetOverlay(string.format("%d/%d", obj.AcquiredCount, need))
    end
end

local syncing = false

local function stage_of(i)
    local st = SelectorGet("transport_" .. i)
    return nil, st and GRAPH.transports[i].choices[st] or nil
end

local function set_dest(i, dest)
    if dest == nil then
        SelectorSet("transport_" .. i, nil)
        return
    end
    for k, j in ipairs(GRAPH.transports[i].choices) do
        if j == dest then
            SelectorSet("transport_" .. i, k)
            return
        end
    end
end

local last_dest = {}

local function on_transport_changed(i)
    if syncing then
        return
    end
    syncing = true
    local _, dest = stage_of(i)
    local prev = last_dest[i]
    if prev and prev ~= dest then
        local _, back = stage_of(prev)
        if back == i then
            set_dest(prev, nil)
            last_dest[prev] = nil
        end
    end
    if dest then
        -- Whatever dest pointed at before now loses its partner too.
        local _, old = stage_of(dest)
        if old and old ~= i then
            set_dest(old, nil)
            last_dest[old] = nil
        end
        set_dest(dest, i)
        last_dest[dest] = i
    end
    last_dest[i] = dest
    syncing = false
end

function ResetTransportSync()
    last_dest = {}
end

ScriptHost:AddWatchForCode("logic_dirty", "*", function(_)
    MarkLogicDirty()
end)
ScriptHost:AddWatchForCode("dna_overlay", "metroid_dna", function(_)
    UpdateDnaOverlay()
end)
for i = 1, PACK_DATA.n_transports do
    ScriptHost:AddWatchForCode("transport_sync_" .. i, "transport_" .. i, function(_)
        on_transport_changed(i)
    end)
end
