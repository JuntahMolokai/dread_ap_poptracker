"""Item / door / trick / transport icons.

Major-item art comes from Randovania's tracker assets
(``randovania/data/gui_assets/tracker/game-images/dread``, GPL-3.0), fetched at
build time by ``external_assets`` (not stored in this repo). Everything
Randovania has no art for (expansions, door locks, trick dials, transports) is
drawn here with PIL so the pack has no external art dependency.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import external_assets

SIZE = 36
RDV_IMAGES = external_assets.ICONS_DIR

# AP item name -> Randovania image basename (when it exists).
RDV_ITEM_ART = {
    n: n for n in [
        "Bomb", "Charge Beam", "Cross Bomb", "Diffusion Beam", "Flash Shift",
        "Grapple Beam", "Gravity Suit", "Ice Missile", "Morph Ball",
        "Phantom Cloak", "Plasma Beam", "Power Bomb", "Pulse Radar",
        "Screw Attack", "Space Jump", "Speed Booster", "Spider Magnet",
        "Spin Boost", "Storm Missile", "Super Missile", "Varia Suit",
        "Wave Beam", "Wide Beam",
    ]
}
RDV_ITEM_ART["Metroid DNA"] = "DNA"

# Door weakness -> (fill colour, overlay item art or None, glyph)
DOOR_STYLE = {
    "Unknown":            ("#4a4f57", None, "?"),
    "Vanilla":            ("#2d3138", None, "V"),
    "Power Beam Door":    ("#8fa3b3", None, "P"),
    "Charge Beam Door":   ("#4fb3ff", "Charge Beam", None),
    "Wide Beam Door":     ("#e8c93a", "Wide Beam", None),
    "Plasma Beam Door":   ("#e0483a", "Plasma Beam", None),
    "Wave Beam Door":     ("#a65cf0", "Wave Beam", None),
    "Missile Door":       ("#ff8c1a", None, "M"),
    "Super Missile Door": ("#3cc95a", "Super Missile", None),
    "Grapple Beam Door":  ("#2b6cff", "Grapple Beam", None),
    "Sensor Lock Door":   ("#d84ac8", "Phantom Cloak", None),
    "Access Open":        ("#d9d9d9", None, "O"),
    "Ice Missile Door":   ("#9fe7ff", "Ice Missile", None),
    "Storm Missile Door": ("#ff5aa0", "Storm Missile", None),
    "Diffusion Beam Door": ("#6fe0d0", "Diffusion Beam", None),
    "Bomb Door":          ("#c0c0c0", "Bomb", None),
    "Cross Bomb Door":    ("#c0c0c0", "Cross Bomb", None),
    "Power Bomb Door":    ("#ffd84a", "Power Bomb", None),
    "Access Permanently Closed": ("#111111", None, "X"),
}


TRICK_ABBR = {
    "Knowledge": "KNOW", "Movement": "MOVE", "Combat": "CMBT", "Pseudo": "PWB",
    "IBJ": "IBJ", "WBJ": "WBJ", "WSJ": "WSJ", "SWJ": "SWJ", "Slide": "SLJ",
    "Speedbooster": "SBC", "Walljump": "WJ", "Suitless": "HEAT", "RGrapple": "RGB",
    "DBoost": "DMG", "FrozenEnemy": "FRZ", "GrappleMovement": "GRAP",
    "CrossSkip": "CBS", "TunnelSlope": "TUN", "ShortBoost": "SHB",
    "DiffusionAbuse": "DIFF", "FlashSkip": "FSS", "DBJ": "DBJ", "LedgeWarp": "LEDG",
    "CBL": "CBL", "FloorClip": "CLIP", "SlopeClimb": "SLOP",
}


def _font(size: int):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill="#ffffff",
          anchor="mm"):
    f = _font(size)
    draw.text(xy, text, font=f, fill=fill, anchor=anchor,
              stroke_width=2, stroke_fill="#000000")


def _art(name: str) -> Image.Image | None:
    p = RDV_IMAGES / f"{name}.png"
    if not p.exists():
        return None
    return Image.open(p).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)


def _canvas():
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def _tank(fill: str, label: str, base: str | None = None) -> Image.Image:
    im = _canvas()
    d = ImageDraw.Draw(im)
    if base and (art := _art(base)) is not None:
        im.alpha_composite(art)
        d = ImageDraw.Draw(im)
    else:
        d.rounded_rectangle([4, 4, SIZE - 5, SIZE - 5], radius=6, fill=fill,
                            outline="#ffffff", width=2)
    _text(d, (SIZE / 2, SIZE / 2 + (6 if base else 0)), label,
          13 if len(label) > 2 else 16)
    return im


def fetch_art() -> None:
    """Make sure every Randovania icon used here is in the local cache."""
    external_assets.fetch_icons(sorted(set(RDV_ITEM_ART.values())))


def write_item_icons(out_dir: Path) -> dict[str, str]:
    """Write item icons; returns AP item name -> pack-relative image path."""
    fetch_art()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    def save(name: str, im: Image.Image) -> None:
        fn = name.lower().replace("+", "_plus").replace(" ", "_") + ".png"
        im.save(out_dir / fn)
        paths[name] = f"images/items/{fn}"

    for ap_name, rdv in RDV_ITEM_ART.items():
        art = _art(rdv)
        if art is None:
            art = _tank("#555555", ap_name[:2])
        save(ap_name, art)

    save("Slide", _tank("#3b6ea8", "SL"))
    save("Energy Tank", _tank("#d9822b", "E"))
    save("Energy Part", _tank("#a8641f", "E¼"))
    save("Missile Tank", _tank("#b0402f", "M"))
    save("Missile+ Tank", _tank("#7a2a20", "M+"))
    save("Power Bomb Tank", _tank("#c9a227", "PB", base=None))
    save("Flash Shift Upgrade", _tank("", "+", base="Flash Shift"))
    save("Speed Booster Upgrade", _tank("", "+", base="Speed Booster"))

    goal = _canvas()
    d = ImageDraw.Draw(goal)
    d.ellipse([3, 3, SIZE - 4, SIZE - 4], fill="#5b1a6e", outline="#ffcc33", width=2)
    _text(d, (SIZE / 2, SIZE / 2), "RB", 14)
    save("Goal", goal)

    start = _canvas()
    d = ImageDraw.Draw(start)
    d.rounded_rectangle([2, 2, SIZE - 3, SIZE - 3], radius=6, fill="#1d7a3a",
                        outline="#ffffff", width=2)
    d.line([(12, 7), (12, 30)], fill="#ffffff", width=3)          # flag pole
    d.polygon([(13, 7), (28, 12), (13, 18)], fill="#ffd84a")      # flag
    save("Start", start)
    return paths


def door_icon_path(weakness: str) -> str:
    return "images/doors/" + weakness.lower().replace(" ", "_") + ".png"


def write_door_icons(out_dir: Path) -> None:
    fetch_art()
    out_dir.mkdir(parents=True, exist_ok=True)
    for weakness, (fill, art_name, glyph) in DOOR_STYLE.items():
        im = _canvas()
        d = ImageDraw.Draw(im)
        # A door is drawn as a tall capsule, like the in-game map hatch.
        d.rounded_rectangle([7, 2, SIZE - 8, SIZE - 3], radius=8, fill=fill,
                            outline="#ffffff", width=2)
        if art_name and (art := _art(art_name)) is not None:
            im.alpha_composite(art.resize((26, 26), Image.LANCZOS), (5, 5))
            d = ImageDraw.Draw(im)
        if glyph:
            _text(d, (SIZE / 2, SIZE / 2), glyph, 16)
        im.save(out_dir / Path(door_icon_path(weakness)).name)


def write_trick_icon(out_dir: Path, short: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    im = _canvas()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([1, 1, SIZE - 2, SIZE - 2], radius=5, fill="#1f2a44",
                        outline="#7aa2ff", width=2)
    label = TRICK_ABBR.get(short, short[:4])
    _text(d, (SIZE / 2, SIZE / 2 - 3), label, 11 if len(label) > 3 else 13)
    fn = f"trick_{short.lower()}.png"
    im.save(out_dir / fn)
    return f"images/tricks/{fn}"


def write_setting_icons(out_dir: Path) -> dict[str, str]:
    """On/off toggles for the automatic behaviours; returns code -> path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}

    def base(fill):
        im = _canvas()
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([1, 1, SIZE - 2, SIZE - 2], radius=6, fill=fill,
                            outline="#ffffff", width=2)
        return im, d

    # Auto doors: a door capsule with an "A" badge.
    im, d = base("#24405a")
    d.rounded_rectangle([10, 5, SIZE - 11, SIZE - 6], radius=6, fill="#a65cf0",
                        outline="#ffffff", width=2)
    _text(d, (SIZE - 9, 9), "A", 11, fill="#ffd84a")
    im.save(out_dir / "auto_doors.png")
    out["auto_doors"] = "images/settings/auto_doors.png"

    # Auto transports: elevator arrows with an "A" badge.
    im, d = base("#24405a")
    d.polygon([(15, 5), (8, 14), (22, 14)], fill="#ffffff")
    d.polygon([(15, 31), (8, 22), (22, 22)], fill="#ffffff")
    _text(d, (SIZE - 9, 9), "A", 11, fill="#ffd84a")
    im.save(out_dir / "auto_transports.png")
    out["auto_transports"] = "images/settings/auto_transports.png"

    # Auto map tab: a tab strip with an arrow.
    im, d = base("#24405a")
    d.rectangle([5, 9, 15, 15], fill="#8fa3b3")
    d.rectangle([17, 9, 27, 15], fill="#ffd84a")
    d.rectangle([5, 15, SIZE - 6, SIZE - 7], outline="#ffffff", width=2)
    d.polygon([(10, 24), (20, 19), (20, 29)], fill="#ffd84a")
    im.save(out_dir / "auto_maptab.png")
    out["auto_maptab"] = "images/settings/auto_maptab.png"
    return out


def write_transport_icons(out_dir: Path) -> dict[str, str]:
    """Generic elevator / shuttle / unknown glyphs; returns kind -> path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for kind, fill in (("elevator", "#2f7d6d"), ("shuttle", "#2f5f7d"),
                       ("unknown", "#4a4f57")):
        im = _canvas()
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([2, 2, SIZE - 3, SIZE - 3], radius=6, fill=fill,
                            outline="#ffffff", width=2)
        if kind == "elevator":
            d.polygon([(18, 5), (11, 14), (25, 14)], fill="#ffffff")
            d.polygon([(18, 31), (11, 22), (25, 22)], fill="#ffffff")
        elif kind == "shuttle":
            d.polygon([(5, 18), (14, 11), (14, 25)], fill="#ffffff")
            d.polygon([(31, 18), (22, 11), (22, 25)], fill="#ffffff")
        else:
            _text(d, (SIZE / 2, SIZE / 2), "?", 18)
        im.save(out_dir / f"{kind}.png")
        out[kind] = f"images/transports/{kind}.png"
    return out


def copy_maps(src_dir: Path, out_dir: Path, regions: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in regions:
        shutil.copyfile(src_dir / f"{r}.png", out_dir / f"{r}.png")
