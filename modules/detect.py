import os
from pathlib import Path

SUBNAUTICA_APPID = "264710"

# Any of these inside a directory confirms it holds Subnautica game files.
_SUBNAUTICA_MARKERS = (
    "Subnautica.exe",
    "Subnautica_Data",
    "Subnautica.x86_64",
)

_NITROX_SAVE_SUBPATH = ".local/share/Nitrox/saves"


def _candidate_homes():
    homes = {Path.home(), Path("/root")}
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        homes.add(Path("/home") / sudo_user)
    home_base = Path("/home")
    if home_base.is_dir():
        for d in home_base.iterdir():
            if d.is_dir():
                homes.add(d)
    return homes


def _steam_library_roots():
    roots = []
    for h in _candidate_homes():
        roots.append(h / ".steam/steam")
        roots.append(h / ".local/share/Steam")
        roots.append(h / "Steam")
        roots.append(h / "snap/steam/common/.local/share/Steam")
    return roots


def detect_subnautica(default_dir):
    """Return dirs that look like a Subnautica install, deduped and ordered.

    The default install dir is probed first so it wins when present.
    """
    candidates = [Path(default_dir)]
    for root in _steam_library_roots():
        candidates.append(root / "steamapps/common/Subnautica")

    found = []
    seen = set()
    for c in candidates:
        try:
            key = c.resolve()
        except OSError:
            key = c
        if key in seen:
            continue
        seen.add(key)
        if c.is_dir() and any((c / m).exists() for m in _SUBNAUTICA_MARKERS):
            found.append(c)
    return found


def detect_nitrox_saves():
    """Return (name, path) for each existing Nitrox world save directory."""
    save_roots = [h / _NITROX_SAVE_SUBPATH for h in _candidate_homes()]
    save_roots.append(Path("/opt/nitrox/saves"))

    saves = []
    seen = set()
    for root in save_roots:
        if not root.is_dir():
            continue
        for world in sorted(root.iterdir()):
            try:
                key = world.resolve()
            except OSError:
                key = world
            if world.is_dir() and key not in seen:
                seen.add(key)
                saves.append((world.name, world))
    return saves
