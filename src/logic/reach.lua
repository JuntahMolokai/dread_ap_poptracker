-- Reachability over the apworld's logic graph (dread_ap graph_logic.py).
--
-- The graph is a set of components (Randovania node SCCs) joined by entrances
-- whose rules are interned ASTs (GRAPH.ast). Door ("k") atoms resolve per seed
-- through DoorWeakness(); transport rides come from TransportDest(). Events are
-- triggered the moment any of their components is reached, exactly like the
-- apworld's Event:<name> regions.
--
-- Two passes are computed per state change:
--   normal  - the seed's trick levels; unknown doors / transports impassable
--   relaxed - every trick at max; unknown doors open with any candidate lock;
--             unknown transports may lead anywhere of their kind
-- A location reached only in the relaxed pass is shown as a sequence break.
--
-- This file only depends on GRAPH, PACK_DATA, SETTINGS and the Count / Active
-- helpers in state.lua, so the parity harness can run it outside PopTracker.

local A = GRAPH.ast
local DYN = GRAPH.ast_dynamic
local ES, ED, EA = GRAPH.es, GRAPH.ed, GRAPH.ea
local SIDES = GRAPH.sides
local DOORS = GRAPH.doors
local WAST = GRAPH.weakness_ast
local TRS = GRAPH.transports
local COMP_EVENTS = GRAPH.comp_events

-- Outgoing entrance lists per component, and transport endpoints per component.
local OUT = {}
for e = 1, #ES do
    local s = ES[e]
    local l = OUT[s]
    if not l then
        l = {}
        OUT[s] = l
    end
    l[#l + 1] = e
end
local TR_AT = {}
for i, t in ipairs(TRS) do
    local l = TR_AT[t.comp]
    if not l then
        l = {}
        TR_AT[t.comp] = l
    end
    l[#l + 1] = i
end

local AMMO_BASE = {
    missile_tank = "missile_base", missile_plus_tank = "missile_base",
    power_bomb = "pb_base", power_bomb_tank = "pb_base",
}
local AMMO_PER = {
    missile_tank = "missile_tank_per_unit",
    missile_plus_tank = "missile_plus_tank_per_unit",
    power_bomb = "power_bomb_per_unit",
    power_bomb_tank = "power_bomb_tank_per_unit",
}

local function ammo_amounts()
    local o = SETTINGS.options
    return {
        missile_base = o.starting_missiles,
        missile_tank_per_unit = o.missile_tank_ammo,
        missile_plus_tank_per_unit = o.missile_plus_tank_ammo,
        pb_base = 0,
        power_bomb_per_unit = o.starting_power_bombs,
        power_bomb_tank_per_unit = o.power_bomb_tank_ammo,
    }
end

-- ---------------------------------------------------------------------------
-- AST evaluation
-- ---------------------------------------------------------------------------

local eval

local function eval_dock(side_idx, ctx)
    local side = SIDES[side_idx]
    if not ctx.door_rando then
        return eval(side.vanilla, ctx)
    end
    local w = ctx.door_state[side.group]
    if w == "vanilla" then
        return eval(side.vanilla, ctx)
    elseif w ~= nil then
        local a = WAST[w]
        return a ~= nil and eval(a, ctx)
    end
    -- Unknown lock.
    if not ctx.relaxed then
        return false
    end
    if eval(side.vanilla, ctx) then
        return true
    end
    local incompat = DOORS[side.group].incompat_set
    for _, cand in ipairs(PACK_DATA.door_choices) do
        if not incompat[cand] then
            local a = WAST[cand]
            if a and eval(a, ctx) then
                return true
            end
        end
    end
    return false
end

eval = function(i, ctx)
    local memo = ctx.memo
    local m = memo[i]
    if m ~= nil then
        return m
    end
    local row = A[i]
    local op = row[1]
    local r
    if op == "i" then
        r = ctx.count(row[2]) >= row[3]
    elseif op == "&" then
        r = true
        for k = 2, #row do
            if not eval(row[k], ctx) then
                r = false
                break
            end
        end
    elseif op == "|" then
        r = false
        for k = 2, #row do
            if eval(row[k], ctx) then
                r = true
                break
            end
        end
    elseif op == "t" then
        r = row[3] <= ctx.trick(row[2])
    elseif op == "e" then
        r = ctx.events[row[2]] == true
    elseif op == "k" then
        r = eval_dock(row[2], ctx)
    elseif op == "T" then
        r = true
    elseif op == "F" then
        r = false
    elseif op == "m" then
        -- DoorLocks misc resource: true while door-lock rando is active.
        if row[2] then
            r = not ctx.door_rando
        else
            r = ctx.door_rando
        end
    elseif op == "s" then
        local amounts = ctx.ammo
        local base = row[2]
        local total = 0
        for k = 4, #row, 2 do
            local code, per = row[k], row[k + 1]
            local bkey = AMMO_BASE[code]
            if bkey then
                base = amounts[bkey]
            end
            local pkey = AMMO_PER[code]
            if pkey then
                per = amounts[pkey]
            end
            total = total + ctx.count(code) * per
        end
        r = base + total >= row[3]
    elseif op == "d" then
        r = false
        for k = 3, #row do
            if ctx.count(row[k]) > 0 then
                r = true
                break
            end
        end
        if not r then
            local ept = ctx.ept
            local budget = (ept - 1) + ept * ctx.count("energy_tank")
                + (ept / 4) * ctx.count("energy_part")
            r = budget >= row[2]
        end
    else
        error("unknown AST op " .. tostring(op))
    end
    if not DYN[i] then
        memo[i] = r
    end
    return r
end

-- ---------------------------------------------------------------------------
-- Sweep
-- ---------------------------------------------------------------------------

-- ctx fields: count(code), trick(short), relaxed, door_rando, door_state,
-- transport_dest(i) -> dest index | nil | "any", ept, ammo, start
function ReachSweep(ctx)
    ctx.memo = {}
    ctx.events = {}
    local reach = {}
    local queue = {}
    local pending = {}
    local new_events = false

    local function visit(c)
        if reach[c] then
            return
        end
        reach[c] = true
        queue[#queue + 1] = c
        local evs = COMP_EVENTS[c]
        if evs then
            for _, name in ipairs(evs) do
                if not ctx.events[name] then
                    ctx.events[name] = true
                    new_events = true
                end
            end
        end
    end

    visit(ctx.start)
    while true do
        while #queue > 0 do
            local c = table.remove(queue)
            local outs = OUT[c]
            if outs then
                for _, e in ipairs(outs) do
                    local d = ED[e]
                    if not reach[d] then
                        if eval(EA[e], ctx) then
                            visit(d)
                        else
                            pending[#pending + 1] = e
                        end
                    end
                end
            end
            local trs = TR_AT[c]
            if trs then
                for _, ti in ipairs(trs) do
                    local dest = ctx.transport_dest(ti)
                    if dest == "any" then
                        for _, j in ipairs(TRS[ti].choices) do
                            visit(TRS[j].comp)
                        end
                    elseif dest then
                        visit(TRS[dest].comp)
                    end
                end
            end
        end
        if not new_events then
            break
        end
        new_events = false
        local retry = pending
        pending = {}
        for _, e in ipairs(retry) do
            local d = ED[e]
            if not reach[d] then
                if eval(EA[e], ctx) then
                    visit(d)
                else
                    pending[#pending + 1] = e
                end
            end
        end
        if #queue == 0 and not new_events then
            break
        end
    end
    return reach
end

function ReachEval(ast_idx, ctx)
    return eval(ast_idx, ctx)
end

ReachAmmo = ammo_amounts

for _, d in ipairs(DOORS) do
    local s = {}
    for _, w in ipairs(d.incompat) do
        s[w] = true
    end
    d.incompat_set = s
end
