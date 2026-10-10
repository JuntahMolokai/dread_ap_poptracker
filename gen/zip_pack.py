"""Zip the pack for distribution (excludes the generator, its build output and
the source assets) and optionally record the release in versions.json.

  python gen/zip_pack.py                     -> dist/<package_uid>-<version>.zip
  python gen/zip_pack.py --release "note" ["another note" ...]
        also writes this version's entry (download URL, sha256, changelog) into
        versions.json, replacing an existing entry for the same version

The zip is deterministic (fixed timestamps, sorted entries), so a given pack
version always has the same sha256. Upload it to the GitHub release tagged
<version> (no "v" prefix) under the same file name, so versions.json's download_url resolves.
PopTracker reads versions.json via manifest.json's versions_url to offer updates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
INCLUDE = ["manifest.json", "settings.json", "README.md", "LICENSE", "scripts", "src", "items",
           "locations", "maps", "layouts", "images", "var_side_bar", "var_items_only"]
REPO_URL = "https://github.com/JuntahMolokai/dread_ap_poptracker"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def build_zip(manifest: dict) -> Path:
    if not (PACK / "images" / "maps" / "Combined.png").exists():
        raise SystemExit("images/ is generated and not in the repo: run gen/build_pack.py first")
    out = PACK / "dist" / f"{manifest['package_uid']}-{manifest['package_version']}.zip"
    out.parent.mkdir(exist_ok=True)
    files = []
    for name in INCLUDE:
        p = PACK / name
        files += [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files, key=lambda f: f.relative_to(PACK).as_posix()):
            info = zipfile.ZipInfo(f.relative_to(PACK).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, f.read_bytes())
    return out


def record_release(manifest: dict, zip_path: Path, changelog: list[str]) -> None:
    version = manifest["package_version"]
    path = PACK / "versions.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"versions": []}
    entry = {
        "package_version": version,
        "download_url": f"{REPO_URL}/releases/download/{version}/{zip_path.name}",
        "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "changelog": changelog,
    }
    others = [v for v in data["versions"] if v.get("package_version") != version]
    data["versions"] = [entry] + others
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"versions.json: v{version} sha256={entry['sha256']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release", nargs="+", metavar="CHANGELOG",
                    help="record this version in versions.json with these changelog lines")
    args = ap.parse_args()
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    out = build_zip(manifest)
    print(out)
    if args.release:
        record_release(manifest, out, args.release)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
