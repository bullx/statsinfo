"""NVMe health via our native IOKit helper (Apple IONVMeSMARTInterface)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


NVME_DATA_UNIT_BYTES = 1000 * 512  # NVMe spec


def _helper_path() -> Path | None:
    candidates: list[Path] = []
    here = Path(__file__).resolve().parent
    candidates.append(here / "bin" / "nvme_health")

    # py2app: Contents/Resources/ssdinfo/bin/nvme_health
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        resources = exe.parents[1] / "Resources"
        candidates.extend(
            [
                resources / "ssdinfo" / "bin" / "nvme_health",
                resources / "bin" / "nvme_health",
                resources / "nvme_health",
            ]
        )

    for path in candidates:
        if path.is_file():
            return path
    return None


def read_nvme_health() -> list[dict[str, Any]]:
    helper = _helper_path()
    if helper is None:
        return []
    try:
        result = subprocess.run(
            [str(helper)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    drives = payload.get("drives") or []
    return [d for d in drives if isinstance(d, dict)]


def units_to_tb(units: int | None) -> float | None:
    if units is None:
        return None
    return (units * NVME_DATA_UNIT_BYTES) / (1000**4)
