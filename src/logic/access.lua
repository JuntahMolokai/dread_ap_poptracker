function CanReachLocation(ap_id)
    local comp = GRAPH.pickup_comp[tonumber(ap_id)]
    if comp == nil then
        return AccessibilityLevel.None
    end
    return LevelForComp(comp)
end

function LocationExists(ap_id)
    local set = SETTINGS.existing_locations
    if set == nil then
        return true
    end
    return set[tonumber(ap_id)] == true
end

function DoorPinVisible(gi)
    gi = tonumber(gi)
    return DoorMode() ~= "vanilla" and not SETTINGS.known_vanilla[gi]
end

function DoorModeIs(mode)
    return DoorMode() == mode
end

function DoorAccess(gi)
    local best = AccessibilityLevel.None
    for _, comp in ipairs(GRAPH.doors[tonumber(gi)].comps) do
        local lvl = LevelForComp(comp)
        if lvl == AccessibilityLevel.Normal then
            return lvl
        elseif lvl == AccessibilityLevel.SequenceBreak then
            best = lvl
        end
    end
    return best
end

function TransportAccess(i)
    return LevelForComp(GRAPH.transports[tonumber(i)].comp)
end

function TransportRandoOff()
    return not TransportRandoOn()
end

function StartPoint()
    local comp = SETTINGS.start_comp or GRAPH.start_comp
    for _, sp in ipairs(GRAPH.start_points) do
        if sp.comp == comp then
            return sp
        end
    end
    return nil
end

function IsStartPoint(i)
    local sp = GRAPH.start_points[tonumber(i)]
    return sp ~= nil and sp.comp == (SETTINGS.start_comp or GRAPH.start_comp)
end

function StartPointAccess()
    return AccessibilityLevel.Normal
end

function DnaCount()
    return Tracker:ProviderCountForCode("metroid_dna")
end

function GoalAccess()
    local r = GetReach()
    local need = SETTINGS.options.required_artifacts or 0
    if DnaCount() < need then
        return AccessibilityLevel.None
    end
    if ReachEval(GRAPH.victory, r.ctx_n) then
        return AccessibilityLevel.Normal
    elseif ReachEval(GRAPH.victory, r.ctx_r) then
        return AccessibilityLevel.SequenceBreak
    end
    return AccessibilityLevel.None
end
