# Metroid Dread — Archipelago PopTracker pack

A map tracker for the [dread_ap](https://github.com/mdietz94/dread_ap) Archipelago world. It has
pins for every pickup on the nine region maps, and its logic is the apworld's
own region graph. This pack is built on version 0.28.0 of the APWorld, and requires it for the 
Automatic Discovery.

## Installing

Download the latest `metroid_dread_ap_map-<version>.zip` from the
[releases](https://github.com/JuntahMolokai/dread_ap_poptracker/releases) and
put it in PopTracker's `packs` folder. PopTracker 0.32 or newer is
recommended; hint outlines need it.

## Using It

1. Load the pack in PopTracker, then connect to your AP server (AP button → slot name).
2. On connect, the pack configures itself from slot_data:
   - trick levels;
   - required Metroid DNA;
   - door-lock and transport rando modes;
   - ammo and energy settings;
   - spawn point.

   No manual settings are needed.
3. Items and checked locations update automatically.

### Doors

Randomized doors start as **Unknown**, and logic treats them as closed until
their lock is known. With the Dread client connected, a door's real lock fills
in as soon as you enter a room next to it (see "Automatic discovery" below).
You can also set it yourself on the small diamond pin in the door's doorway.

- **Individual Doors** mode: set each door as you find it.
- **Door Types** mode: each door pin shows a single "<type> doors become"
  selector, shared by every door of that original type. Setting it once (for
  example, Missile doors became Wave doors) applies to all of them, and the
  **Door Types** tab holds the same selectors. The generator occasionally
  leaves a door unchanged when its type's new lock doesn't fit it. Once the
  Dread client reports you've reached such a door, it's quietly treated as its
  original lock.
- Some doors can never be randomized: doors the starting kit can open near your
  spawn, and door types your options don't change. These are known to be vanilla
  and get no pin.
- If you mark a door with its own vanilla lock, the pack treats it as
  unrandomized. That keeps the free back side of one-way doors open.

### Transports

Each elevator and shuttle has a pin, and its popup shows where it goes. With
transport rando on, destinations start Unknown. With the Dread client
connected, riding a transport fills in its destination. You can also pick one
yourself. Either way, the return trip is filled in automatically. With rando
off, the pin just shows the vanilla destination.

Door and transport notes persist across reconnects to the same seed and
clear when you connect to a different seed.

## Automatic Discovery

The pack allows for automatic discovery of door types and transport destinations, 
as well as automatic map tab swapping on transitions:

- **Doors:** a randomized door's real lock is filled in from slot_data once
  the door has been on screen. That means Samus stood within about one screen
  (roughly 2100 × 1150 world units, the size of a single-screen station room)
  of it, in one of the two rooms it joins. A door at the far end of a huge room
  stays unknown until you get near it. In Door Types mode the door's type
  mapping is filled in instead. Locks you set by hand are never overwritten.
  Clients that don't send positions fall back to revealing every door of a
  room as soon as you enter it.
- **Map tab:** follows the region you're in, so riding an elevator, shuttle or
  teleportal switches the map automatically.
- **Transports:** a ride fills in that transport's destination, and its
  return trip follows automatically. Each candidate ride is checked against
  the seed's real matching, so death reloads, warps and teleportals (which
  also produce room pairs) never fill in anything. Destinations you set by
  hand are never overwritten.

Older clients that don't publish the necessary info leave everything manual.

### Settings

Each of these can be switched off in the **Settings** tab. All three are on
by default and saved with your tracker state.

- **Auto doors**
- **Auto transports**
- **Auto map tab:** also covers the jump to the start region on a new seed.

Turning one off stops that behaviour. Anything already filled in, and anything
you set by hand, stays. With auto doors off, doors are exactly what you've
entered; the seed's real door data isn't consulted at all. Turning a toggle
back on catches up from what the client has already reported.

### World map

The **World** tab is every region on one map, with pins for pickups, transports,
the start and the goal. Door pins stay on the region tabs only.

The arrangement lives in `gen/combined_layout.json`. It holds an offset and
scale for each region, and you can edit it by hand.
`gen/register_world_map.py reference.png` regenerates the file by matching
each region map against a reference image, which isn't included in this repo.
This needs numpy and opencv-python-headless. After changing it, re-run `build_pack.py`;
`calibrate.py` writes a check overlay to
`gen/build/overlays/Combined.png`.

### Start

A green flag square marks your spawn point. On the first connect to a new seed, the map tab switches to the starting region. Reconnecting to the same seed leaves your current tab alone.

### Goal

The diamond in Itorash's Raven Beak arena turns green once the escape is in
logic and you hold the required Metroid DNA. The DNA counter shows
`held/required`.

### Map calibration

Pin positions come from Randovania's node coordinates.
To check or adjust the placement:

```
python gen/calibrate.py                    # overlays -> gen/build/overlays/*.png
python gen/calibrate.py --pair Elun "Bridge Gate/Dock to Purple Drapes" 912 412 \
                        --pair Elun "Transport to Ghavoran/Start Point 1" 430 420
```

The second form solves a per-map override from two reference points (room or
node ↔ pixel) and stores it in `gen/calibration.json`. You can also give
`margins` or a `nudge` there.

## Building from source

Clone with the submodule:

```
git clone --recursive https://github.com/JuntahMolokai/dread_ap_poptracker
# or, in an existing clone:
git submodule update --init external/dread_ap
pip install -r gen/requirements.txt
python gen/build_pack.py
```

Everything under `src/data`, `items`, `locations`, `maps` and `layouts` is
generated; commit those alongside your source changes. `images/` is generated
too, but isn't committed: it contains art from other projects (Randovania),
which this repo doesn't store. The build fetches that art, so the repo itself
isn't a loadable pack until you've built it. Use a release zip to just play.

| Input | Where | Notes |
|---|---|---|
| dread_ap (apworld data, logic extractor) | `external/dread_ap` (submodule) | Pinned to the apworld release the pack targets. Set `DREAD_AP_DIR` to use another checkout. |
| Randovania logic DB | fetched into `external/dread_ap/.dread-cache/` | Downloaded automatically by dread_ap's `cache_randovania_logic.py`, at its pinned commit. |
| Region maps | fetched from Randovania (pinned commit in `gen/external_assets.py`) into `gen/build/` | The pack's edits are stored as operations in `gen/map_edits.json` (move a label, clear a border) and re-applied at build time. Add new edits there, not to image files. Set `RANDOVANIA_DIR` to copy from a local Randovania checkout instead of downloading. |
| Item art | fetched from Randovania the same way | Randovania tracker icons. The pack's own icons (expansions, doors, tricks, transports, settings) are drawn by `gen/icons.py`. |
| World-map arrangement | `gen/combined_layout.json` | See *World map* below. |

The pack's logic graph must match the apworld players generate with, because
`ut_state.start_comp` is a numeric component id. To move to a new apworld
release:

1. Check out its tag in `external/dread_ap`.
2. Rebuild.
3. Run the tests.

`src/data/graph.lua` records the Randovania commit it was built from.

### Tests

Both tests need the `lupa` package (`pip install lupa`).

```
python gen/tests/parity_test.py --seeds 90   # Lua logic == apworld logic
python gen/tests/pack_sim_test.py            # whole pack under a PopTracker API stub
```

`parity_test` runs the pack's Lua against `DoorRando.early_reachable` over
random items, trick levels, door rolls and transport matchings. It checks:

- with every door and transport known, the reachable set is exactly the apworld's;
- with them unknown, nothing extra is marked in logic, and the yellow pass covers everything truly reachable;
- no door the pack reveals as vanilla was actually randomized.

## Credits and license

This pack is licensed under the **GNU GPL v3** (see `LICENSE`), because it
bundles data and art from GPL-3.0 projects:

- **[dread_ap](https://github.com/mdietz94/dread_ap)**: the Metroid Dread
  Archipelago world. The pack's logic is generated from its logic graph and
  item / location data.
- **[Randovania](https://github.com/randovania/randovania)**:
  - the Dread logic database the graph is built from;
  - the region map images, with small edits from `gen/map_edits.json`;
  - the item icons.

  Both are fetched from Randovania at build time and aren't stored in this
  repo; release zips include them.

Metroid Dread is © Nintendo. This is an unofficial fan project.
