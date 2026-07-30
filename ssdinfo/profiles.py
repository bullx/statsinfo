"""Fan curve profiles — builtins + user saves."""

from __future__ import annotations

import json
from pathlib import Path

from .models import FanCurvePoint, FanProfile

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Mac Hardware Info"
PROFILES_PATH = APP_SUPPORT / "fan_profiles.json"
STATE_PATH = APP_SUPPORT / "fan_control_state.json"


def _builtin() -> list[FanProfile]:
    return [
        FanProfile(
            name="Silent",
            builtin=True,
            points=[
                FanCurvePoint(35, 15),
                FanCurvePoint(50, 25),
                FanCurvePoint(65, 40),
                FanCurvePoint(80, 70),
                FanCurvePoint(95, 100),
            ],
        ),
        FanProfile(
            name="Balanced",
            builtin=True,
            points=[
                FanCurvePoint(35, 25),
                FanCurvePoint(50, 40),
                FanCurvePoint(65, 55),
                FanCurvePoint(80, 80),
                FanCurvePoint(95, 100),
            ],
        ),
        FanProfile(
            name="Performance",
            builtin=True,
            points=[
                FanCurvePoint(35, 40),
                FanCurvePoint(50, 60),
                FanCurvePoint(65, 80),
                FanCurvePoint(80, 95),
                FanCurvePoint(95, 100),
            ],
        ),
        FanProfile(
            name="Full",
            builtin=True,
            points=[
                FanCurvePoint(30, 100),
                FanCurvePoint(95, 100),
            ],
        ),
    ]


def _parse_profile(data: dict) -> FanProfile | None:
    name = data.get("name")
    pts = data.get("points") or []
    if not isinstance(name, str) or not name.strip():
        return None
    points: list[FanCurvePoint] = []
    for p in pts:
        if not isinstance(p, dict):
            continue
        try:
            points.append(FanCurvePoint(temp_c=float(p["temp_c"]), duty_pct=float(p["duty_pct"])))
        except (KeyError, TypeError, ValueError):
            continue
    points.sort(key=lambda x: x.temp_c)
    if len(points) < 2:
        return None
    emergency = float(data.get("emergency_c") or 95.0)
    return FanProfile(
        name=name.strip(),
        points=points,
        builtin=bool(data.get("builtin", False)),
        emergency_c=emergency,
    )


def load_profiles() -> list[FanProfile]:
    builtins = {p.name: p for p in _builtin()}
    custom: list[FanProfile] = []
    if PROFILES_PATH.is_file():
        try:
            raw = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            for item in raw.get("profiles") or []:
                if not isinstance(item, dict):
                    continue
                prof = _parse_profile(item)
                if prof is None or prof.name in builtins:
                    continue
                prof.builtin = False
                custom.append(prof)
        except (OSError, json.JSONDecodeError):
            pass
    return list(builtins.values()) + custom


def save_profiles(profiles: list[FanProfile]) -> None:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    custom = [p for p in profiles if not p.builtin]
    payload = {"profiles": [p.to_dict() for p in custom]}
    PROFILES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def upsert_profile(profiles: list[FanProfile], profile: FanProfile) -> list[FanProfile]:
    profile.points = sorted(profile.points, key=lambda p: p.temp_c)
    out: list[FanProfile] = []
    replaced = False
    for p in profiles:
        if p.name == profile.name:
            if p.builtin:
                # save as custom copy name
                continue
            out.append(profile)
            replaced = True
        else:
            out.append(p)
    if not replaced:
        out.append(profile)
    # ensure builtins remain
    names = {p.name for p in out}
    for b in _builtin():
        if b.name not in names:
            out.insert(0, b)
    save_profiles(out)
    return load_profiles()


def delete_profile(profiles: list[FanProfile], name: str) -> list[FanProfile]:
    for p in profiles:
        if p.name == name and p.builtin:
            return profiles
    save_profiles([p for p in profiles if p.name != name])
    return load_profiles()


def write_control_state(profile: FanProfile, *, active: bool, stop: bool = False) -> Path:
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": active,
        "stop": stop,
        "emergency_c": profile.emergency_c,
        "profile": profile.name,
        "points": [p.to_dict() for p in sorted(profile.points, key=lambda x: x.temp_c)],
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return STATE_PATH


def request_pause() -> None:
    """Return fans to Auto but keep privileged daemon alive (no password)."""
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    data: dict = {"active": False, "stop": False, "points": []}
    if STATE_PATH.is_file():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    data["active"] = False
    data["stop"] = False
    if "points" not in data:
        data["points"] = []
    STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def request_stop() -> None:
    """Ask daemon to restore Auto and exit (app quit)."""
    if not STATE_PATH.is_file():
        APP_SUPPORT.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps({"active": False, "stop": True, "points": []}, indent=2),
            encoding="utf-8",
        )
        return
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["stop"] = True
    data["active"] = False
    STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
