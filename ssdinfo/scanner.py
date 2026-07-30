"""Native macOS disk scanner — diskutil + IOKit via ioreg."""

from __future__ import annotations

import plistlib
import subprocess
from typing import Any

from .models import DriveInfo, HealthStatus, SmartAttribute, format_bytes
from .nvme_health import read_nvme_health, units_to_tb


class ScannerError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _run_text(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _ioreg_class(class_name: str) -> list[dict[str, Any]]:
    result = _run(["ioreg", "-a", "-r", "-w", "0", "-c", class_name])
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = plistlib.loads(result.stdout)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def list_physical_disks() -> list[str]:
    result = _run_text(["diskutil", "list", "-plist"])
    if result.returncode != 0:
        raise ScannerError(result.stderr.strip() or "diskutil list failed")
    data = plistlib.loads(result.stdout.encode())
    disks: list[str] = []
    for entry in data.get("AllDisksAndPartitions", []):
        ident = entry.get("DeviceIdentifier")
        content = entry.get("Content") or ""
        if not ident:
            continue
        if "APFS" in content and "GUID" not in content:
            continue
        disks.append(ident)
    return disks


def diskutil_info(identifier: str) -> dict[str, Any]:
    result = _run(["diskutil", "info", "-plist", identifier])
    if result.returncode != 0:
        raise ScannerError((result.stderr or b"").decode("utf-8", errors="replace").strip() or f"diskutil info failed for {identifier}")
    return plistlib.loads(result.stdout)


def _nvme_controller_by_serial() -> dict[str, dict[str, Any]]:
    """Map serial → controller identity fields from Apple NVMe IOKit nodes."""
    out: dict[str, dict[str, Any]] = {}
    for cls in ("AppleNVMeController", "AppleANS3CGv2Controller", "IONVMeBlockStorageDevice"):
        for node in _ioreg_class(cls):
            serial = str(
                node.get("Serial Number")
                or (node.get("Device Characteristics") or {}).get("Serial Number")
                or ""
            ).strip()
            chars = node.get("Controller Characteristics") or {}
            if not isinstance(chars, dict):
                chars = {}
            info = {
                "model": str(node.get("Model Number") or (node.get("Device Characteristics") or {}).get("Product Name") or "").strip(),
                "serial": serial,
                "firmware": str(
                    node.get("Firmware Revision")
                    or chars.get("firmware-version")
                    or (node.get("Device Characteristics") or {}).get("Product Revision Level")
                    or ""
                ).strip(),
                "vendor": str(node.get("Vendor Name") or chars.get("vendor-name") or "").strip(),
                "nvme_version": str(node.get("NVMe Revision Supported") or "").strip(),
                "nand_name": str(chars.get("nand-marketing-name") or "").strip(),
                "nand_status": str(node.get("AppleNANDStatus") or "").strip(),
                "capacity": chars.get("capacity"),
                "smart_capable": bool(node.get("NVMe SMART Capable")) if "NVMe SMART Capable" in node else None,
                "class": cls,
            }
            if serial:
                # Prefer richer controller nodes over block device stubs
                prev = out.get(serial)
                if prev is None or (not prev.get("nand_name") and info.get("nand_name")):
                    out[serial] = info
                elif not prev.get("model") and info.get("model"):
                    out[serial] = {**prev, **{k: v for k, v in info.items() if v}}
            elif info.get("model"):
                out.setdefault(info["model"], info)
    return out


def _block_storage_stats() -> list[dict[str, Any]]:
    stats_list: list[dict[str, Any]] = []
    for drv in _ioreg_class("IOBlockStorageDriver"):
        stats = drv.get("Statistics") or {}
        if not isinstance(stats, dict):
            continue
        stats_list.append(
            {
                "name": drv.get("IORegistryEntryName"),
                "bytes_read": _int(stats.get("Bytes (Read)")),
                "bytes_written": _int(stats.get("Bytes (Write)")),
                "read_errors": _int(stats.get("Errors (Read)")),
                "write_errors": _int(stats.get("Errors (Write)")),
                "read_ops": _int(stats.get("Operations (Read)")),
                "write_ops": _int(stats.get("Operations (Write)")),
                "retries_read": _int(stats.get("Retries (Read)")),
                "retries_write": _int(stats.get("Retries (Write)")),
            }
        )
    return stats_list


def _media_serials() -> dict[str, str]:
    """BSD name → serial when IOKit exposes it on IOMedia."""
    mapping: dict[str, str] = {}
    for media in _ioreg_class("IOMedia"):
        if not media.get("Whole"):
            continue
        bsd = str(media.get("BSD Name") or "")
        serial = str(media.get("Serial Number") or "").strip()
        if bsd and serial:
            mapping[bsd] = serial
    return mapping


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _assess_health(drive: DriveInfo) -> None:
    reasons: list[str] = []
    status = HealthStatus.UNKNOWN
    smart = (drive.macos_smart_status or "").strip().lower()

    if smart in ("verified", "passed"):
        status = HealthStatus.GOOD
        drive.smart_passed = True
        drive.smart_available = True
        reasons.append(f"Disk health: {drive.macos_smart_status}")
    elif smart in ("failing", "failed"):
        status = HealthStatus.BAD
        drive.smart_passed = False
        drive.smart_available = True
        reasons.append(f"Disk health: {drive.macos_smart_status}")
    elif smart in ("not supported", ""):
        drive.smart_passed = None
        drive.smart_available = bool(drive.nvme_health_available)
        if not drive.nvme_health_available:
            reasons.append("Disk health status not available for this device")
    else:
        drive.smart_available = True
        status = HealthStatus.CAUTION
        reasons.append(f"Disk health: {drive.macos_smart_status}")

    if drive.critical_warning is not None and drive.critical_warning != 0:
        status = HealthStatus.BAD
        reasons.append(f"Critical warning: 0x{drive.critical_warning:02x}")

    if drive.nvme_health_available and drive.smart_passed is not False:
        if status == HealthStatus.UNKNOWN:
            status = HealthStatus.GOOD
        drive.smart_available = True
        if drive.smart_passed is None:
            drive.smart_passed = True

    if (
        drive.available_spare is not None
        and drive.available_spare_threshold is not None
        and drive.available_spare <= drive.available_spare_threshold
    ):
        status = HealthStatus.BAD
        reasons.append(
            f"Available spare {drive.available_spare}% ≤ threshold {drive.available_spare_threshold}%"
        )
    elif drive.available_spare is not None and drive.available_spare < 50:
        if status != HealthStatus.BAD:
            status = HealthStatus.CAUTION
        reasons.append(f"Available spare low: {drive.available_spare}%")

    if drive.percentage_used is not None:
        if drive.percentage_used >= 90:
            status = HealthStatus.BAD
            reasons.append(f"Percentage used: {drive.percentage_used}%")
        elif drive.percentage_used >= 70:
            if status != HealthStatus.BAD:
                status = HealthStatus.CAUTION
            reasons.append(f"Percentage used: {drive.percentage_used}%")

    if drive.temperature_c is not None:
        if drive.temperature_c >= 70:
            status = HealthStatus.BAD
            reasons.append(f"Temperature: {drive.temperature_c}°C")
        elif drive.temperature_c >= 60:
            if status != HealthStatus.BAD:
                status = HealthStatus.CAUTION
            reasons.append(f"Temperature elevated: {drive.temperature_c}°C")

    if drive.nand_status and drive.nand_status.lower() not in ("ready", ""):
        if status != HealthStatus.BAD:
            status = HealthStatus.CAUTION
        reasons.append(f"NAND status: {drive.nand_status}")

    read_err = drive.read_errors or 0
    write_err = drive.write_errors or 0
    if read_err or write_err:
        status = HealthStatus.BAD if (read_err + write_err) >= 10 else HealthStatus.CAUTION
        reasons.append(f"I/O errors — read {read_err}, write {write_err}")

    if drive.media_errors is not None and drive.media_errors > 0:
        status = HealthStatus.BAD
        reasons.append(f"Media errors: {drive.media_errors}")

    if status == HealthStatus.GOOD and not any("Critical" in r or "Percentage" in r for r in reasons):
        if drive.nvme_health_available:
            reasons.append("NVMe health log within normal ranges")

    if status == HealthStatus.UNKNOWN and not reasons:
        reasons.append(drive.error or "Insufficient health signals")

    drive.health = status
    drive.health_reasons = reasons


def _apply_nvme_health(drive: DriveInfo, health: dict) -> None:
    drive.nvme_health_available = True
    drive.raw_native["nvme_health"] = health
    if health.get("model"):
        drive.model = str(health["model"])
    if health.get("serial"):
        drive.serial = str(health["serial"])
    if health.get("firmware"):
        drive.firmware = str(health["firmware"])

    drive.critical_warning = _int(health.get("critical_warning"))
    drive.temperature_c = _int(health.get("temperature_c"))
    drive.available_spare = _int(health.get("available_spare"))
    drive.available_spare_threshold = _int(health.get("available_spare_threshold"))
    drive.percentage_used = _int(health.get("percentage_used"))
    drive.data_units_read = _int(health.get("data_units_read"))
    drive.data_units_written = _int(health.get("data_units_written"))
    drive.data_read_tb = units_to_tb(drive.data_units_read)
    drive.data_written_tb = units_to_tb(drive.data_units_written)
    drive.host_reads = _int(health.get("host_reads"))
    drive.host_writes = _int(health.get("host_writes"))
    drive.controller_busy_time = _int(health.get("controller_busy_time"))
    drive.power_cycles = _int(health.get("power_cycles"))
    drive.power_on_hours = _int(health.get("power_on_hours"))
    drive.unsafe_shutdowns = _int(health.get("unsafe_shutdowns"))
    drive.media_errors = _int(health.get("media_errors"))
    drive.num_err_log_entries = _int(health.get("num_err_log_entries"))


def _attr(attrs: list[SmartAttribute], aid: str, name: str, raw: Any) -> None:
    if raw is None or raw == "":
        return
    attrs.append(SmartAttribute(id=aid, name=name, raw=str(raw).strip()))


def build_drive(
    identifier: str,
    controllers: dict[str, dict[str, Any]] | None = None,
    stats_pool: list[dict[str, Any]] | None = None,
    media_serials: dict[str, str] | None = None,
    nvme_health_list: list[dict[str, Any]] | None = None,
) -> DriveInfo:
    info = diskutil_info(identifier)
    node = info.get("DeviceNode") or f"/dev/{identifier}"
    drive = DriveInfo(
        device=identifier,
        device_node=node,
        model=str(info.get("MediaName") or info.get("IORegistryEntryName") or "Unknown"),
        capacity_bytes=int(info.get("TotalSize") or 0),
        interface=str(info.get("BusProtocol") or ""),
        is_ssd=bool(info.get("SolidState")),
        is_internal=bool(info.get("Internal")),
        macos_smart_status=str(info.get("SMARTStatus") or ""),
    )

    controllers = controllers if controllers is not None else _nvme_controller_by_serial()
    media_serials = media_serials if media_serials is not None else _media_serials()
    stats_pool = stats_pool if stats_pool is not None else _block_storage_stats()
    nvme_health_list = nvme_health_list if nvme_health_list is not None else read_nvme_health()

    serial_hint = media_serials.get(identifier, "")
    ctrl = None
    if serial_hint and serial_hint in controllers:
        ctrl = controllers[serial_hint]
    else:
        for candidate in controllers.values():
            if candidate.get("model") and candidate["model"] == drive.model:
                ctrl = candidate
                break
        if ctrl is None and len(controllers) == 1 and drive.is_internal:
            ctrl = next(iter(controllers.values()))

    if ctrl:
        drive.serial = ctrl.get("serial") or drive.serial
        drive.firmware = ctrl.get("firmware") or drive.firmware
        drive.model = ctrl.get("model") or drive.model
        drive.vendor = ctrl.get("vendor") or ""
        drive.nand_name = ctrl.get("nand_name") or ""
        drive.nvme_version = ctrl.get("nvme_version") or ""
        drive.nand_status = ctrl.get("nand_status") or ""
        if ctrl.get("capacity"):
            try:
                drive.capacity_bytes = int(ctrl["capacity"]) or drive.capacity_bytes
            except (TypeError, ValueError):
                pass
        drive.raw_native["controller"] = ctrl

    stats = None
    if len(stats_pool) == 1:
        stats = stats_pool[0]
    elif stats_pool and drive.is_internal:
        stats = stats_pool[0]
    if stats:
        drive.bytes_read = stats.get("bytes_read")
        drive.bytes_written = stats.get("bytes_written")
        drive.read_errors = stats.get("read_errors")
        drive.write_errors = stats.get("write_errors")
        drive.read_ops = stats.get("read_ops")
        drive.write_ops = stats.get("write_ops")
        drive.raw_native["io_stats"] = stats

    # Match NVMe health log by serial / model / sole internal drive
    matched_health = None
    for h in nvme_health_list:
        if drive.serial and h.get("serial") == drive.serial:
            matched_health = h
            break
        if h.get("bsd_name") and h["bsd_name"] == identifier:
            matched_health = h
            break
        if h.get("model") and h["model"] == drive.model:
            matched_health = h
            break
    if matched_health is None and len(nvme_health_list) == 1 and drive.is_internal:
        matched_health = nvme_health_list[0]
    if matched_health:
        _apply_nvme_health(drive, matched_health)

    drive.raw_native["diskutil"] = {
        k: info.get(k)
        for k in (
            "DeviceIdentifier",
            "MediaName",
            "TotalSize",
            "SolidState",
            "Internal",
            "BusProtocol",
            "SMARTStatus",
            "DeviceBlockSize",
        )
    }

    attrs: list[SmartAttribute] = []
    _attr(attrs, "critical_warning", "Critical Warning", None if drive.critical_warning is None else f"0x{drive.critical_warning:02x}")
    _attr(attrs, "temperature", "Temperature (°C)", drive.temperature_c)
    _attr(attrs, "available_spare", "Available Spare (%)", drive.available_spare)
    _attr(attrs, "available_spare_threshold", "Available Spare Threshold (%)", drive.available_spare_threshold)
    _attr(attrs, "percentage_used", "Percentage Used (%)", drive.percentage_used)
    if drive.data_units_read is not None:
        tb = f"{drive.data_read_tb:.2f} TB" if drive.data_read_tb is not None else ""
        _attr(attrs, "data_units_read", "Data Units Read", f"{drive.data_units_read:,} [{tb}]" if tb else f"{drive.data_units_read:,}")
    if drive.data_units_written is not None:
        tb = f"{drive.data_written_tb:.2f} TB" if drive.data_written_tb is not None else ""
        _attr(
            attrs,
            "data_units_written",
            "Data Units Written",
            f"{drive.data_units_written:,} [{tb}]" if tb else f"{drive.data_units_written:,}",
        )
    _attr(attrs, "host_reads", "Host Read Commands", None if drive.host_reads is None else f"{drive.host_reads:,}")
    _attr(attrs, "host_writes", "Host Write Commands", None if drive.host_writes is None else f"{drive.host_writes:,}")
    _attr(attrs, "controller_busy_time", "Controller Busy Time", drive.controller_busy_time)
    _attr(attrs, "power_cycles", "Power Cycles", drive.power_cycles)
    _attr(attrs, "power_on_hours", "Power-On Hours", drive.power_on_hours)
    _attr(attrs, "unsafe_shutdowns", "Unsafe Shutdowns", drive.unsafe_shutdowns)
    _attr(attrs, "media_errors", "Media and Data Integrity Errors", drive.media_errors)
    _attr(attrs, "num_err_log_entries", "Error Information Log Entries", drive.num_err_log_entries)
    _attr(attrs, "smart_status", "Health Status", drive.macos_smart_status)
    _attr(attrs, "model", "Model", drive.model)
    _attr(attrs, "serial", "Serial Number", drive.serial)
    _attr(attrs, "firmware", "Firmware", drive.firmware)
    _attr(attrs, "vendor", "Vendor", drive.vendor)
    _attr(attrs, "nand", "NAND", drive.nand_name)
    _attr(attrs, "nand_status", "NAND Status", drive.nand_status)
    _attr(attrs, "nvme", "NVMe Version", drive.nvme_version)
    _attr(attrs, "interface", "Interface", drive.interface)
    _attr(attrs, "capacity", "Capacity", format_bytes(drive.capacity_bytes))
    drive.attributes = attrs

    _assess_health(drive)
    return drive


def scan_drives(ssd_only: bool = False) -> list[DriveInfo]:
    controllers = _nvme_controller_by_serial()
    stats_pool = _block_storage_stats()
    media_serials = _media_serials()
    nvme_health_list = read_nvme_health()
    drives: list[DriveInfo] = []
    for ident in list_physical_disks():
        try:
            drive = build_drive(ident, controllers, stats_pool, media_serials, nvme_health_list)
        except Exception as exc:  # noqa: BLE001
            drive = DriveInfo(device=ident, device_node=f"/dev/{ident}", error=str(exc))
            _assess_health(drive)
        if ssd_only and not drive.is_ssd:
            continue
        drives.append(drive)
    return drives
