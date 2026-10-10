-- Tracker state: seed settings, item counts, door / transport knowledge and the
-- cached reachability passes.

local function copy(t)
    local o = {}
    for k, v in pairs(t) do
        o[k] = v
    end
    return o
end

SETTINGS = {
    options = copy(PACK_DATA.option_defaults),
    tricks = {},                -- short_name -> level; nil = use the dial item
    connected = false,
    start_comp = GRAPH.start_comp,
    start_extra_items = {},     -- AP item names (more-starting-areas kit)
    doors_to_change = nil,      -- set of weakness names; nil = Randovania default
    known_vanilla = {},         -- door index -> true (provably never randomized)
    discovered_vanilla = {},    -- door index -> true: Door Types mode, discovered
                                -- in-game, and left unchanged by the generator
                                -- (its type's new lock didn't fit this door)
    door_exact = {},            -- door index -> true: discovered in-game AND
                                -- randomized onto its own vanilla lock
                                -- (both sides shielded, unlike a vanilla door)
    existing_locations = nil,   -- set of AP location ids; nil = all
}

-- ---------------------------------------------------------------------------
-- Item counts
-- ---------------------------------------------------------------------------

local count_cache = {}

local function raw_count(code)
    return Tracker:ProviderCountForCode(code)
end

function Count(code)
    local c = count_cache[code]
    if c ~= nil then
        return c
    end
    c = raw_count(code)
    if code == "flash_shift_upgrade" and raw_count("flash_shift") > 0 then
        -- World.MAIN_CHAIN_CREDIT: the main Flash Shift bundles its chain.
        c = c + (SETTINGS.options.flash_shift_included_ammo or 0)
    end
    count_cache[code] = c
    return c
end

-- Door / transport selectors: see src/selectors.lua (SelectorGet / SelectorSet).
local function selector_stage(code)
    return SelectorGet(code)
end

-- ---------------------------------------------------------------------------
-- Doors / transports
-- ---------------------------------------------------------------------------

function DoorMode()
    local v = SETTINGS.options.door_lock_rando or 0
    if v == 1 then
        return "individual"
    elseif v == 2 then
        return "types"
    end
    return "vanilla"
end

function DoorTypeCode(weakness)
    return "doortype_" .. string.lower(weakness):gsub("[^a-z0-9]+", "_"):gsub("^_", ""):gsub("_$", "")
end

-- Weakness of door group gi as currently known: "vanilla", a weakness name, or
-- nil (unknown). A per-door selection always wins; in Door Types mode the
-- door's vanilla type mapping applies otherwise.
--
-- A door marked with its own vanilla lock is treated as unrandomized, which
-- keeps the free back side of an asymmetric door (e.g. the Open Passage behind
-- a one-way Sensor Lock) passable. The rare roll that re-picks the vanilla lock
-- shields both sides in-game; once the door has been discovered through the
-- client's room feed, door_exact marks that case so logic matches it exactly.
--
-- Individual Doors mode reads the door's own selector; Door Types mode reads
-- only the shared "<type> doors become" selector of the door's vanilla type.
function DoorWeakness(gi)
    if SETTINGS.known_vanilla[gi] or SETTINGS.discovered_vanilla[gi] then
        return "vanilla"
    end
    local st
    if DoorMode() == "types" then
        st = selector_stage(DoorTypeCode(GRAPH.doors[gi].weakness))
    else
        st = selector_stage("door_" .. gi)
    end
    local w = st and PACK_DATA.door_choices[st] or nil
    if w ~= nil and w == GRAPH.doors[gi].weakness and not SETTINGS.door_exact[gi] then
        return "vanilla"
    end
    return w
end

function TransportRandoOn()
    return (SETTINGS.options.transport_rando or 0) ~= 0
end

-- Destination transport index of transport i, or nil if unknown.
function TransportDest(i)
    local t = GRAPH.transports[i]
    if not TransportRandoOn() then
        return t.default_dest
    end
    local st = selector_stage("transport_" .. i)
    if st then
        return t.choices[st]
    end
    return nil
end

-- ---------------------------------------------------------------------------
-- Contexts
-- ---------------------------------------------------------------------------

local function base_ctx()
    local ctx = {
        count = Count,
        door_rando = DoorMode() ~= "vanilla",
        ept = SETTINGS.options.energy_per_tank or 100,
        ammo = ReachAmmo(),
        start = SETTINGS.start_comp or GRAPH.start_comp,
    }
    local ds = {}
    if ctx.door_rando then
        for gi = 1, #GRAPH.doors do
            ds[gi] = DoorWeakness(gi)
        end
    end
    ctx.door_state = ds
    local td = {}
    for i = 1, #GRAPH.transports do
        td[i] = TransportDest(i)
    end
    ctx.td = td
    return ctx
end

local function trick_level(short)
    local v = SETTINGS.tricks[short]
    if v ~= nil then
        return v
    end
    return Count("trick_" .. string.lower(short))
end

-- ---------------------------------------------------------------------------
-- Cached passes
-- ---------------------------------------------------------------------------

local cache = nil
LOGIC_DIRTY = true

function MarkLogicDirty()
    LOGIC_DIRTY = true
end

function GetReach()
    if cache and not LOGIC_DIRTY then
        return cache
    end
    count_cache = {}
    local normal = base_ctx()
    normal.trick = trick_level
    normal.relaxed = false
    normal.transport_dest = function(i) return normal.td[i] end
    local reach_n = ReachSweep(normal)

    local relaxed = base_ctx()
    relaxed.trick = function(_) return 5 end
    relaxed.relaxed = true
    relaxed.transport_dest = function(i) return relaxed.td[i] or "any" end
    local reach_r = ReachSweep(relaxed)

    cache = {normal = reach_n, relaxed = reach_r, ctx_n = normal, ctx_r = relaxed}
    LOGIC_DIRTY = false
    return cache
end

function LevelForComp(comp)
    local r = GetReach()
    if r.normal[comp] then
        return AccessibilityLevel.Normal
    elseif r.relaxed[comp] then
        return AccessibilityLevel.SequenceBreak
    end
    return AccessibilityLevel.None
end

-- ---------------------------------------------------------------------------
-- Start-door guard (DoorRando.roll_assignments): doors on the early frontier
-- that the starting kit can open stay vanilla, and doors of a vanilla type the
-- seed does not change are never randomized. Both are deterministic from the
-- settings, so they are revealed as known-vanilla without spoiling anything.
-- ---------------------------------------------------------------------------

function ComputeKnownVanillaDoors(transport_matching)
    local known = {}
    if DoorMode() == "vanilla" then
        SETTINGS.known_vanilla = known
        return
    end
    local kit = {}
    for _, code in ipairs(PACK_DATA.base_starting_items) do
        kit[code] = 1
    end
    for _, name in ipairs(SETTINGS.start_extra_items or {}) do
        local code = PACK_DATA.item_codes_by_name[name]
        if code then
            kit[code] = 1
        end
    end
    local function kit_count(code)
        return kit[code] or 0
    end
    local function tricks(short)
        return SETTINGS.tricks[short] or 0
    end
    local tr_index = {}
    for i, t in ipairs(GRAPH.transports) do
        tr_index[t.id] = i
    end

    -- early_reachable(..., is_door_rando=True) with vanilla doors.
    local ctx = {
        count = kit_count, trick = tricks, relaxed = false, door_rando = true,
        door_state = setmetatable({}, {__index = function() return "vanilla" end}),
        ept = SETTINGS.options.energy_per_tank or 100, ammo = ReachAmmo(),
        start = SETTINGS.start_comp or GRAPH.start_comp,
    }
    ctx.transport_dest = function(i)
        local t = GRAPH.transports[i]
        local dest = transport_matching and transport_matching[t.id]
        if dest and tr_index[dest] then
            return tr_index[dest]
        end
        return t.default_dest
    end
    local reach = ReachSweep(ctx)

    -- _vanilla_passable: evaluated with is_door_rando=False, no events.
    local vctx = {
        count = kit_count, trick = tricks, relaxed = false, door_rando = false,
        door_state = {}, ept = ctx.ept, ammo = ctx.ammo, memo = {}, events = {},
    }
    local change = SETTINGS.doors_to_change
    for gi, d in ipairs(GRAPH.doors) do
        local protected = false
        for _, s in ipairs(d.sides) do
            local e = GRAPH.dock_entrance[s]
            if e and (reach[GRAPH.es[e]] or reach[GRAPH.ed[e]]) then
                protected = true
            end
        end
        if protected then
            local passable = false
            for _, s in ipairs(d.sides) do
                if ReachEval(GRAPH.sides[s].vanilla, vctx) then
                    passable = true
                end
            end
            protected = passable
        end
        if protected or (change and not change[d.weakness]) then
            known[gi] = true
        end
    end
    SETTINGS.known_vanilla = known
end
