"""Battery health via AppleSmartBattery (IOKit) — design / full / current mAh fields."""

from __future__ import annotations

import plistlib
import re
import subprocess
from typing import Any

from .models import BatteryInfo, HealthStatus


def _run(cmd: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _signed_amperage(value: Any) -> int | None:
    """
    InstantAmperage is often a bit-pattern for signed mA.
    Positive = charging, negative = discharging (normal).
    """
    n = _int(value)
    if n is None:
        return None
    # Already signed (plist sometimes gives negative directly)
    if n < 0:
        return int(n)
    # Common: unsigned 64-bit / 32-bit encoding of a signed value
    if n >= 1 << 63:
        n -= 1 << 64
    elif n >= 1 << 31:
        n -= 1 << 32
    # Sanity: battery pack current is rarely beyond ±20 A
    if abs(n) > 30000:
        return None
    return int(n)


def _temp_c_from_apple(raw: Any) -> float | None:
    """
    AppleSmartBattery Temperature is deci-Kelvin (Kelvin × 10).
    Example: 3012 → 301.2 K → 28.05 °C  ⇒  value/10 - 273.15
    """
    n = _int(raw)
    if n is None or n <= 0:
        return None

    # Already Celsius
    if n <= 80:
        return float(n)

    # Deci-Kelvin (normal Apple path)
    if 2500 <= n <= 4000:  # roughly -23°C … 127°C
        c = round(n / 10.0 - 273.15, 1)
        if -20.0 <= c <= 80.0:
            return c

    # Some firmwares use centi-Kelvin (Kelvin × 100)
    if n > 20000:
        c = round(n / 100.0 - 273.15, 1)
        if -20.0 <= c <= 80.0:
            return c

    # Tenths of a degree Celsius (e.g. 321 = 32.1°C)
    if 100 <= n < 800:
        c = round(n / 10.0, 1)
        if 0.0 <= c <= 80.0:
            return c

    return None


def _looks_like_mah(n: int | None) -> bool:
    """Raw mAh on MacBooks is typically hundreds–tens of thousands, not 0–100%."""
    return n is not None and n > 100


def _ioreg_battery() -> dict[str, Any] | None:
    result = _run(["ioreg", "-a", "-r", "-c", "AppleSmartBattery"])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = plistlib.loads(result.stdout)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(data, list) and data:
        return data[0]
    return None


def _system_profiler_battery() -> dict[str, str]:
    result = _run(["system_profiler", "SPPowerDataType"])
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key in {
            "Cycle Count",
            "Condition",
            "Maximum Capacity",
            "State of Charge",
            "Charging",
            "Fully Charged",
        }:
            out[key] = val
    return out


def _pmset_percent() -> tuple[int | None, str]:
    result = _run(["pmset", "-g", "batt"])
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    source = ""
    for line in text.splitlines():
        if "drawing from" in line.lower():
            source = line.split("'")[1] if "'" in line else line.strip()
        m = re.search(r"(\d+)%", line)
        if m and "Battery" in line:
            return int(m.group(1)), source
    m = re.search(r"(\d+)%", text)
    return (int(m.group(1)) if m else None), source


def _assess(battery: BatteryInfo) -> None:
    reasons: list[str] = []
    status = HealthStatus.UNKNOWN

    if not battery.installed:
        battery.health = HealthStatus.UNKNOWN
        battery.health_reasons = [
            battery.error or "No internal battery detected (desktop Mac or battery not installed)"
        ]
        return

    status = HealthStatus.GOOD
    cond = (battery.condition or "").lower()
    if "service" in cond or "replace now" in cond or "failure" in cond:
        status = HealthStatus.BAD
        reasons.append(f"Condition: {battery.condition}")
    elif "replace" in cond or "poor" in cond or "check" in cond:
        status = HealthStatus.CAUTION
        reasons.append(f"Condition: {battery.condition}")
    elif battery.condition:
        reasons.append(f"Condition: {battery.condition}")

    if battery.max_capacity_percent is not None:
        if battery.max_capacity_percent < 60:
            status = HealthStatus.BAD
            reasons.append(f"Full charge capacity {battery.max_capacity_percent}% of design")
        elif battery.max_capacity_percent < 80:
            if status != HealthStatus.BAD:
                status = HealthStatus.CAUTION
            reasons.append(f"Full charge capacity {battery.max_capacity_percent}% of design")

    if battery.cycle_count is not None and battery.design_cycle_count:
        ratio = battery.cycle_count / max(1, battery.design_cycle_count)
        if ratio >= 1.0:
            if status != HealthStatus.BAD:
                status = HealthStatus.CAUTION
            reasons.append(
                f"Cycle count {battery.cycle_count} at/above design {battery.design_cycle_count}"
            )
        elif ratio >= 0.8:
            if status == HealthStatus.GOOD:
                status = HealthStatus.CAUTION
            reasons.append(f"Cycle count {battery.cycle_count} / {battery.design_cycle_count}")

    if battery.temperature_c is not None:
        if battery.temperature_c >= 45:
            status = HealthStatus.BAD
            reasons.append(f"Temperature {battery.temperature_c}°C")
        elif battery.temperature_c >= 40:
            if status != HealthStatus.BAD:
                status = HealthStatus.CAUTION
            reasons.append(f"Temperature {battery.temperature_c}°C")

    if status == HealthStatus.GOOD and not any("Condition" in r for r in reasons):
        reasons.insert(0, "Battery health within normal ranges")

    battery.health = status
    battery.health_reasons = reasons


def _fill_mah_fields(battery: BatteryInfo, raw: dict[str, Any]) -> None:
    """
    Capacities from AppleSmartBattery:

    - DesignCapacity              → design capacity (mAh)
    - AppleRawMaxCapacity         → full charge capacity (mAh)  [what 100% can hold now]
    - NominalChargeCapacity       → fallback for full charge (mAh)
    - AppleRawCurrentCapacity     → current charge (mAh)
    - MaxCapacity / CurrentCapacity → often 0–100% on modern macOS (not mAh)
    """
    nested = raw.get("BatteryData") if isinstance(raw.get("BatteryData"), dict) else {}

    design = _int(raw.get("DesignCapacity")) or _int(nested.get("DesignCapacity"))
    full = (
        _int(raw.get("AppleRawMaxCapacity"))
        or _int(raw.get("NominalChargeCapacity"))
        or _int(nested.get("AppleRawMaxCapacity"))
        or _int(nested.get("NominalChargeCapacity"))
    )
    current = _int(raw.get("AppleRawCurrentCapacity")) or _int(nested.get("AppleRawCurrentCapacity"))

    # Legacy / alternate: CurrentCapacity & MaxCapacity may be mAh OR percent
    cur_field = _int(raw.get("CurrentCapacity"))
    max_field = _int(raw.get("MaxCapacity"))

    if _looks_like_mah(design):
        battery.design_capacity_mah = design
    if _looks_like_mah(full):
        battery.max_capacity_mah = full
    if _looks_like_mah(current):
        battery.current_capacity_mah = current
    elif _looks_like_mah(cur_field) and not _looks_like_mah(current):
        battery.current_capacity_mah = cur_field

    # Percent fields (modern Apple Silicon often uses these for Max/CurrentCapacity)
    if max_field is not None and 0 < max_field <= 100:
        battery.max_capacity_percent = max_field
    if cur_field is not None and 0 <= cur_field <= 100 and not _looks_like_mah(cur_field):
        battery.charge_percent = cur_field

    # Derive missing pieces
    if (
        battery.max_capacity_percent is None
        and battery.design_capacity_mah
        and battery.max_capacity_mah
    ):
        battery.max_capacity_percent = int(
            round(100.0 * battery.max_capacity_mah / battery.design_capacity_mah)
        )

    if (
        battery.max_capacity_mah is None
        and battery.design_capacity_mah
        and battery.max_capacity_percent is not None
    ):
        battery.max_capacity_mah = int(
            round(battery.design_capacity_mah * battery.max_capacity_percent / 100.0)
        )

    if (
        battery.current_capacity_mah is None
        and battery.max_capacity_mah
        and battery.charge_percent is not None
    ):
        battery.current_capacity_mah = int(
            round(battery.max_capacity_mah * battery.charge_percent / 100.0)
        )

    if (
        battery.charge_percent is None
        and battery.max_capacity_mah
        and battery.current_capacity_mah is not None
        and battery.max_capacity_mah > 0
    ):
        battery.charge_percent = int(
            round(100.0 * battery.current_capacity_mah / battery.max_capacity_mah)
        )


def scan_battery() -> BatteryInfo:
    battery = BatteryInfo()
    raw = _ioreg_battery()
    profiler = _system_profiler_battery()
    percent, power_source = _pmset_percent()

    if raw is None and not profiler:
        battery.error = "Could not read battery information"
        _assess(battery)
        return battery

    if raw:
        installed = bool(raw.get("BatteryInstalled", True))
        design = _int(raw.get("DesignCapacity"))
        full = _int(raw.get("AppleRawMaxCapacity") or raw.get("NominalChargeCapacity"))
        cycles = _int(raw.get("CycleCount"))

        # Desktop stub: no battery installed / all zeros
        if not installed or (
            not _looks_like_mah(design)
            and not _looks_like_mah(full)
            and cycles in (None, 0)
            and not percent
            and not profiler.get("Cycle Count")
        ):
            battery.installed = False
            battery.external_connected = (
                bool(raw.get("ExternalConnected")) if "ExternalConnected" in raw else None
            )
            battery.power_source = power_source or (
                "AC Power" if battery.external_connected else ""
            )
            battery.error = "No internal battery (this Mac is likely a desktop)"
            _assess(battery)
            return battery

        battery.installed = True
        nested = raw.get("BatteryData") if isinstance(raw.get("BatteryData"), dict) else {}
        battery.device_name = str(
            raw.get("DeviceName") or nested.get("DeviceName") or "Built-in Battery"
        ).strip() or "Built-in Battery"
        battery.serial = str(
            nested.get("BatterySerialNumber")
            or raw.get("BatterySerialNumber")
            or raw.get("Serial")
            or ""
        ).strip()
        battery.manufacturer = str(raw.get("Manufacturer") or nested.get("Manufacturer") or "").strip()

        _fill_mah_fields(battery, raw)

        battery.cycle_count = cycles
        battery.design_cycle_count = _int(
            raw.get("DesignCycleCount9C") or raw.get("DesignCycleCount") or nested.get("DesignCycleCount")
        )
        battery.temperature_c = _temp_c_from_apple(raw.get("Temperature"))
        battery.voltage_mv = _int(raw.get("Voltage"))
        battery.amperage_ma = _signed_amperage(raw.get("InstantAmperage") or raw.get("Amperage"))
        battery.is_charging = bool(raw.get("IsCharging")) if "IsCharging" in raw else None
        battery.fully_charged = bool(raw.get("FullyCharged")) if "FullyCharged" in raw else None
        battery.external_connected = (
            bool(raw.get("ExternalConnected")) if "ExternalConnected" in raw else None
        )
        tr = _int(raw.get("TimeRemaining") or raw.get("AvgTimeToEmpty"))
        if tr is not None and 0 < tr < 6000:
            battery.time_remaining_min = tr

    # system_profiler overlays (Condition / Maximum Capacity %)
    if profiler.get("Condition"):
        battery.condition = profiler["Condition"]
    if profiler.get("Cycle Count") and battery.cycle_count is None:
        battery.cycle_count = _int(profiler["Cycle Count"].split()[0])
    if profiler.get("Maximum Capacity"):
        m = re.search(r"(\d+)", profiler["Maximum Capacity"])
        if m:
            pct = int(m.group(1))
            battery.max_capacity_percent = pct
            if battery.design_capacity_mah and battery.max_capacity_mah is None:
                battery.max_capacity_mah = int(round(battery.design_capacity_mah * pct / 100.0))

    if percent is not None:
        battery.charge_percent = percent
        # refresh current mAh from full × % if we have full charge capacity
        if battery.max_capacity_mah and battery.current_capacity_mah is None:
            battery.current_capacity_mah = int(
                round(battery.max_capacity_mah * percent / 100.0)
            )

    battery.power_source = power_source or (
        "AC Power"
        if battery.external_connected
        else ("Battery Power" if battery.installed else "")
    )

    if not battery.installed and (profiler.get("Cycle Count") or profiler.get("Condition")):
        battery.installed = True
        battery.device_name = battery.device_name or "Built-in Battery"
        if battery.cycle_count is None:
            battery.cycle_count = _int((profiler.get("Cycle Count") or "").split()[0])
        battery.condition = profiler.get("Condition") or battery.condition

    _assess(battery)
    return battery
