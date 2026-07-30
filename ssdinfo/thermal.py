"""Thermal sensors + fans via native smc_thermal helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import FanInfo, ThermalSensor, ThermalSnapshot


def _helper_path() -> Path | None:
    candidates: list[Path] = []
    here = Path(__file__).resolve().parent
    candidates.append(here / "bin" / "smc_thermal")

    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        resources = exe.parents[1] / "Resources"
        candidates.extend(
            [
                resources / "ssdinfo" / "bin" / "smc_thermal",
                resources / "bin" / "smc_thermal",
                resources / "smc_thermal",
            ]
        )

    for path in candidates:
        if path.is_file():
            return path
    return None


def helper_path() -> Path | None:
    return _helper_path()


def scan_thermal() -> ThermalSnapshot:
    helper = _helper_path()
    if helper is None:
        return ThermalSnapshot(error="smc_thermal helper missing — run: make helper")

    try:
        result = subprocess.run(
            [str(helper), "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ThermalSnapshot(error=str(exc))

    raw = (result.stdout or "").strip()
    if not raw:
        err = (result.stderr or "").strip() or "empty status"
        return ThermalSnapshot(error=err)

    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return ThermalSnapshot(error="invalid thermal JSON")

    if "error" in payload and not payload.get("apple_silicon", True):
        return ThermalSnapshot(apple_silicon=False, error=str(payload.get("error")))

    sensors = [
        ThermalSensor(key=s["key"], label=s["label"], celsius=float(s["celsius"]))
        for s in (payload.get("sensors") or [])
        if isinstance(s, dict) and "key" in s and "celsius" in s
    ]
    fans = []
    for f in payload.get("fans") or []:
        if not isinstance(f, dict):
            continue
        fans.append(
            FanInfo(
                index=int(f.get("index", 0)),
                rpm=_num(f.get("rpm")),
                min_rpm=_num(f.get("min_rpm")),
                max_rpm=_num(f.get("max_rpm")),
                target_rpm=_num(f.get("target_rpm")),
                mode=_num(f.get("mode")),
            )
        )
    summary = payload.get("summary") or {}
    return ThermalSnapshot(
        apple_silicon=bool(payload.get("apple_silicon", False)),
        fanless=bool(payload.get("fanless", True)),
        fan_count=int(payload.get("fan_count") or 0),
        privileged=bool(payload.get("privileged", False)),
        cpu_c=_num(summary.get("cpu_c")),
        gpu_c=_num(summary.get("gpu_c")),
        hottest_c=_num(summary.get("hottest_c")),
        sensors=sensors,
        fans=fans,
    )


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
