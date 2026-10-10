HINTS = {key = nil, highlighted = {}}

local HINT_UNSPECIFIED, HINT_NO_PRIORITY, HINT_AVOID, HINT_PRIORITY, HINT_FOUND =
    0, 10, 20, 30, 40

local function highlight_for(status)
    if Highlight == nil then
        return nil
    end
    if status == HINT_FOUND then
        return Highlight.None
    elseif status == HINT_NO_PRIORITY then
        return Highlight.NoPriority
    elseif status == HINT_AVOID then
        return Highlight.Avoid
    end
    return Highlight.Priority
end

local function set_highlight(ap_id, level)
    local path = PACK_DATA.location_paths[ap_id]
    local sec = path and Tracker:FindObjectForCode(path)
    if sec then
        sec.Highlight = level
    end
end

local function on_hints(value)
    if Highlight == nil then
        return
    end
    local me = Archipelago.PlayerNumber
    local want = {}
    if type(value) == "table" then
        for _, hint in pairs(value) do
            if type(hint) == "table" and hint.finding_player == me
                    and PACK_DATA.location_paths[hint.location] then
                local status = hint.status
                if status == nil then
                    status = hint.found and HINT_FOUND or HINT_UNSPECIFIED
                end
                want[hint.location] = highlight_for(status)
            end
        end
    end
    for ap_id, _ in pairs(HINTS.highlighted) do
        if want[ap_id] == nil then
            set_highlight(ap_id, Highlight.None)
        end
    end
    for ap_id, level in pairs(want) do
        set_highlight(ap_id, level)
    end
    HINTS.highlighted = want
end

function StartHints()
    if Highlight ~= nil then
        for ap_id, _ in pairs(HINTS.highlighted) do
            set_highlight(ap_id, Highlight.None)
        end
    end
    HINTS.highlighted = {}
    local team = Archipelago.TeamNumber or 0
    if team < 0 then
        team = 0
    end
    HINTS.key = string.format("_read_hints_%d_%d", team, Archipelago.PlayerNumber)
    Archipelago:SetNotify({HINTS.key})
    Archipelago:Get({HINTS.key})
end

Archipelago:AddRetrievedHandler("dread_hints_retrieved", function(key, value)
    if key == HINTS.key then
        on_hints(value)
    end
end)
Archipelago:AddSetReplyHandler("dread_hints_set_reply", function(key, value, _old)
    if key == HINTS.key then
        on_hints(value)
    end
end)
