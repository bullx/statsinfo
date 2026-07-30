"""Resolve bundled and development asset paths."""

from __future__ import annotations

import sys
from pathlib import Path

_ICON_NAMES = ("AppIcon-128.png", "icons/C-settings-tool.png", "AppIcon.png", "AppIcon.icns")


def app_bundle_path() -> Path | None:
    """Return the .app bundle path when running from py2app, else None."""
    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
        return exe.parent.parent.parent
    return None


def assets_dir() -> Path:
    bundle = app_bundle_path()
    if bundle is not None:
        return bundle / "Contents" / "Resources" / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def find_asset(name: str) -> Path | None:
    """Find an asset file in the .app bundle or source tree."""
    bundle = app_bundle_path()
    candidates: list[Path] = []
    if bundle is not None:
        resources = bundle / "Contents" / "Resources"
        candidates.append(resources / "assets" / name)
        if name.endswith(".png"):
            candidates.append(resources / name)
        if name == "AppIcon.icns":
            candidates.append(resources / "AppIcon.icns")
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / name)
    for path in candidates:
        if path.is_file():
            return path
    return None


def menu_bar_icon_path() -> Path | None:
    for name in _ICON_NAMES:
        found = find_asset(name)
        if found is not None:
            return found
    return None
