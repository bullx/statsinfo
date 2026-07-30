"""User preferences — Application Support JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .profiles import APP_SUPPORT

PREFS_PATH = APP_SUPPORT / "preferences.json"


def _in_app_bundle() -> bool:
    from .resources import app_bundle_path

    return app_bundle_path() is not None


def _defaults() -> dict:
    in_app = _in_app_bundle()
    return {
        "menu_bar_mode": in_app,
        "open_at_login": False,
        "start_hidden": False,
    }


def load_prefs() -> dict:
    defaults = _defaults()
    if not PREFS_PATH.is_file():
        return dict(defaults)
    try:
        raw = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(defaults)
    if not isinstance(raw, dict):
        return dict(defaults)
    out = dict(defaults)
    for key in defaults:
        if key in raw:
            out[key] = raw[key]
    return out


def save_prefs(prefs: dict) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    merged = _defaults()
    merged.update({k: prefs[k] for k in merged if k in prefs})
    PREFS_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
