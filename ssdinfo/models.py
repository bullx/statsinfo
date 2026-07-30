from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    GOOD = "Good"
    CAUTION = "Caution"
    BAD = "Bad"
    UNKNOWN = "Unknown"


@dataclass
class SmartAttribute:
    id: str
    name: str
    raw: str
    value: str | None = None
    worst: str | None = None
    threshold: str | None = None
    when_failed: str | None = None


@dataclass
class DriveInfo:
    device: str
    device_node: str
    model: str = "Unknown"
    serial: str = ""
    firmware: str = ""
    capacity_bytes: int = 0
    interface: str = ""
    is_ssd: bool = True
    is_internal: bool = True
    smart_available: bool = False
    smart_passed: bool | None = None
    health: HealthStatus = HealthStatus.UNKNOWN
    health_reasons: list[str] = field(default_factory=list)
    # Native identity extras (IOKit)
    vendor: str = ""
    nand_name: str = ""
    nvme_version: str = ""
    nand_status: str = ""
    temperature_c: int | None = None
    power_on_hours: int | None = None
    power_cycles: int | None = None
    percentage_used: int | None = None
    available_spare: int | None = None
    available_spare_threshold: int | None = None
    data_units_written: int | None = None
    data_written_tb: float | None = None
    data_units_read: int | None = None
    data_read_tb: float | None = None
    media_errors: int | None = None
    unsafe_shutdowns: int | None = None
    critical_warning: int | None = None
    host_reads: int | None = None
    host_writes: int | None = None
    controller_busy_time: int | None = None
    num_err_log_entries: int | None = None
    # IOKit I/O counters (since boot)
    bytes_read: int | None = None
    bytes_written: int | None = None
    read_errors: int | None = None
    write_errors: int | None = None
    read_ops: int | None = None
    write_ops: int | None = None
    macos_smart_status: str = ""
    nvme_health_available: bool = False
    attributes: list[SmartAttribute] = field(default_factory=list)
    raw_native: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["health"] = self.health.value
        return data

    @property
    def capacity_human(self) -> str:
        return format_bytes(self.capacity_bytes)

    @property
    def health_remaining_pct(self) -> int | None:
        if self.percentage_used is None:
            return None
        return max(0, 100 - int(self.percentage_used))


@dataclass
class BatteryInfo:
    installed: bool = False
    device_name: str = ""
    manufacturer: str = ""
    serial: str = ""
    health: HealthStatus = HealthStatus.UNKNOWN
    health_reasons: list[str] = field(default_factory=list)
    condition: str = ""
    charge_percent: int | None = None
    design_capacity_mah: int | None = None
    max_capacity_mah: int | None = None
    current_capacity_mah: int | None = None
    max_capacity_percent: int | None = None
    cycle_count: int | None = None
    design_cycle_count: int | None = None
    temperature_c: float | None = None
    voltage_mv: int | None = None
    amperage_ma: int | None = None
    is_charging: bool | None = None
    fully_charged: bool | None = None
    external_connected: bool | None = None
    time_remaining_min: int | None = None
    power_source: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["health"] = self.health.value
        return data

    @property
    def status_label(self) -> str:
        if not self.installed:
            return "No battery"
        if self.is_charging:
            return "Charging"
        if self.fully_charged:
            return "Charged"
        if self.external_connected:
            return "On AC power"
        return "On battery"


def format_bytes(n: int | None) -> str:
    if n is None or n < 0:
        return "—"
    if n == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(n)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit in ("B", "KB"):
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{n} B"


@dataclass
class ThermalSensor:
    key: str
    label: str
    celsius: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FanInfo:
    index: int
    rpm: float | None = None
    min_rpm: float | None = None
    max_rpm: float | None = None
    target_rpm: float | None = None
    mode: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThermalSnapshot:
    apple_silicon: bool = False
    fanless: bool = True
    fan_count: int = 0
    privileged: bool = False
    cpu_c: float | None = None
    gpu_c: float | None = None
    hottest_c: float | None = None
    sensors: list[ThermalSensor] = field(default_factory=list)
    fans: list[FanInfo] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "apple_silicon": self.apple_silicon,
            "fanless": self.fanless,
            "fan_count": self.fan_count,
            "privileged": self.privileged,
            "cpu_c": self.cpu_c,
            "gpu_c": self.gpu_c,
            "hottest_c": self.hottest_c,
            "sensors": [s.to_dict() for s in self.sensors],
            "fans": [f.to_dict() for f in self.fans],
            "error": self.error,
        }


@dataclass
class FanCurvePoint:
    temp_c: float
    duty_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {"temp_c": self.temp_c, "duty_pct": self.duty_pct}


@dataclass
class FanProfile:
    name: str
    points: list[FanCurvePoint] = field(default_factory=list)
    builtin: bool = False
    emergency_c: float = 95.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "builtin": self.builtin,
            "emergency_c": self.emergency_c,
            "points": [p.to_dict() for p in self.points],
        }
