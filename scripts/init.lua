-- Metroid Dread (Archipelago) PopTracker pack.

local variant = Tracker.ActiveVariantUID
local items_only = variant == "var_items_only"

Tracker:AddItems("items/items.json")
Tracker:AddItems("items/tricks.json")
Tracker:AddItems("items/settings.json")

ScriptHost:LoadScript("src/data/graph.lua")
ScriptHost:LoadScript("src/data/pack_data.lua")
ScriptHost:LoadScript("src/logic/reach.lua")
ScriptHost:LoadScript("src/logic/state.lua")
ScriptHost:LoadScript("src/selectors.lua")
CreateSelectors()
ScriptHost:LoadScript("src/logic/access.lua")
ScriptHost:LoadScript("src/watches.lua")

if not items_only then
    Tracker:AddMaps("maps/maps.json")
    for _, region in ipairs({"Artaria", "Cataris", "Dairon", "Burenia", "Ghavoran",
                             "Elun", "Ferenia", "Hanubia", "Itorash"}) do
        Tracker:AddLocations("locations/" .. region .. ".json")
    end
end

Tracker:AddLayouts("layouts/tracker.json")

if PopVersion and PopVersion >= "0.18.0" then
    ScriptHost:LoadScript("src/autotracking/discovery.lua")
    ScriptHost:LoadScript("src/autotracking/hints.lua")
    ScriptHost:LoadScript("src/autotracking/archipelago.lua")
end

ApplyCounterColors()
UpdateDnaOverlay()
