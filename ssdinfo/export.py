from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .models import BatteryInfo, DriveInfo


def export_json(
    drives: list[DriveInfo],
    path: str | Path,
    include_raw: bool = False,
    battery: BatteryInfo | None = None,
) -> Path:
    out = Path(path)
    payload: dict[str, Any] = {
        "app": "Mac Hardware Info",
        "version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "drive_count": len(drives),
        "drives": [],
        "battery": battery.to_dict() if battery else None,
    }
    for drive in drives:
        item = drive.to_dict()
        if not include_raw:
            item.pop("raw_native", None)
        payload["drives"].append(item)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def export_html(
    drives: list[DriveInfo],
    path: str | Path,
    battery: BatteryInfo | None = None,
) -> Path:
    out = Path(path)
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    sections = []
    if battery is not None:
        sections.append(battery_section(battery))
    sections.extend(drive_section(d) for d in drives)
    body = "\n".join(sections) if sections else "<p>No data found.</p>"
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Mac Hardware Info Report</title>
<style>
  :root {{
    --bg: #f2f4f8;
    --panel: #ffffff;
    --text: #1c2430;
    --muted: #6b7785;
    --good: #1f8a4c;
    --caution: #c47d00;
    --bad: #d70015;
    --unknown: #8a94a6;
    --line: #e3e8ef;
    --accent: #0071e3;
    --soft: #f7f9fc;
  }}
  body {{
    margin: 0;
    font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: linear-gradient(180deg, #eef3f9 0%, var(--bg) 40%, #e9eef5 100%);
    color: var(--text);
    line-height: 1.45;
  }}
  main {{ max-width: 920px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
  h1 {{ margin: 0 0 0.25rem; font-size: 1.75rem; letter-spacing: -0.02em; }}
  .meta {{ color: var(--muted); margin-bottom: 1.75rem; }}
  .drive {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 1.25rem 1.35rem 1.4rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 8px 24px rgba(28, 36, 48, 0.04);
  }}
  .row {{ display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: baseline; }}
  .model {{ font-size: 1.2rem; font-weight: 650; }}
  .badge {{
    display: inline-block;
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #fff;
  }}
  .Good {{ background: var(--good); }}
  .Caution {{ background: var(--caution); }}
  .Bad {{ background: var(--bad); }}
  .Unknown {{ background: var(--unknown); }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.75rem;
    margin: 1rem 0;
  }}
  .stat {{
    background: var(--soft);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 0.7rem 0.8rem;
  }}
  .stat .label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .stat .value {{ font-size: 1.05rem; font-weight: 600; margin-top: 0.2rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 0.45rem 0.4rem; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }}
  .reasons {{ color: var(--muted); font-size: 0.9rem; margin: 0.5rem 0 0; }}
  footer {{ color: var(--muted); font-size: 0.8rem; margin-top: 1.5rem; }}
</style>
</head>
<body>
<main>
  <h1>Mac Hardware Info Report</h1>
  <p class="meta">Exported {html.escape(now)} · {len(drives)} drive(s) · Mac Hardware Info {html.escape(__version__)}</p>
  {body}
  <footer>SMART and battery values are health indicators, not failure predictions. Keep backups.</footer>
</main>
</body>
</html>
"""
    out.write_text(doc, encoding="utf-8")
    return out


def _stats_html(stats: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div class="stat"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div></div>'
        for label, value in stats
    )


def battery_section(battery: BatteryInfo) -> str:
    health = html.escape(battery.health.value if battery.installed else "Unknown")
    stats = [
        ("Design Capacity", f"{battery.design_capacity_mah} mAh" if battery.design_capacity_mah else "—"),
        ("Full Charge Capacity", f"{battery.max_capacity_mah} mAh" if battery.max_capacity_mah else "—"),
        ("Current Charge", f"{battery.current_capacity_mah} mAh" if battery.current_capacity_mah else "—"),
        ("Charge %", f"{battery.charge_percent}%" if battery.charge_percent is not None else "—"),
        ("Max Capacity %", f"{battery.max_capacity_percent}%" if battery.max_capacity_percent is not None else "—"),
        ("Charge Cycles", str(battery.cycle_count) if battery.cycle_count is not None else "—"),
        ("Design Cycles", str(battery.design_cycle_count) if battery.design_cycle_count is not None else "—"),
        ("Temperature", f"{battery.temperature_c}°C" if battery.temperature_c is not None else "—"),
        ("Voltage", f"{battery.voltage_mv} mV" if battery.voltage_mv else "—"),
        (
            "Amperage",
            (
                "—"
                if battery.amperage_ma is None
                else (
                    f"+{battery.amperage_ma} mA (charging)"
                    if battery.amperage_ma > 0
                    else (
                        f"{battery.amperage_ma} mA (discharging)"
                        if battery.amperage_ma < 0
                        else "0 mA"
                    )
                )
            ),
        ),
        ("Condition", battery.condition or ("Not installed" if not battery.installed else "—")),
        ("Power Source", battery.power_source or "—"),
        ("Serial", battery.serial or "—"),
        ("Manufacturer", battery.manufacturer or "—"),
    ]
    reasons = ""
    if battery.health_reasons:
        reasons = '<p class="reasons">' + html.escape(" · ".join(battery.health_reasons)) + "</p>"
    title = html.escape(battery.device_name or "Battery")
    sub = html.escape(f"{battery.status_label} · {battery.power_source or '—'}")
    return f"""
<section class="drive">
  <div class="row">
    <div class="model">{title}</div>
    <span class="badge {health}">{health}</span>
    <span class="meta">{sub}</span>
  </div>
  {reasons}
  <div class="grid">{_stats_html(stats)}</div>
</section>
"""


def drive_section(drive: DriveInfo) -> str:
    health = html.escape(drive.health.value)
    stats = [
        ("Temperature", f"{drive.temperature_c}°C" if drive.temperature_c is not None else "—"),
        ("Available Spare", f"{drive.available_spare}%" if drive.available_spare is not None else "—"),
        (
            "Available Spare Threshold",
            f"{drive.available_spare_threshold}%" if drive.available_spare_threshold is not None else "—",
        ),
        ("Percentage Used", f"{drive.percentage_used}%" if drive.percentage_used is not None else "—"),
        ("Data Read", f"{drive.data_read_tb:.2f} TB" if drive.data_read_tb is not None else "—"),
        ("Data Written", f"{drive.data_written_tb:.2f} TB" if drive.data_written_tb is not None else "—"),
        ("Power-On Hours", str(drive.power_on_hours) if drive.power_on_hours is not None else "—"),
        ("Power Cycles", str(drive.power_cycles) if drive.power_cycles is not None else "—"),
        ("Unsafe Shutdowns", str(drive.unsafe_shutdowns) if drive.unsafe_shutdowns is not None else "—"),
        ("Media Errors", str(drive.media_errors) if drive.media_errors is not None else "—"),
        (
            "Critical Warning",
            f"0x{drive.critical_warning:02x}" if drive.critical_warning is not None else "—",
        ),
        ("Capacity", drive.capacity_human),
        ("Host Reads", f"{drive.host_reads:,}" if drive.host_reads is not None else "—"),
        ("Host Writes", f"{drive.host_writes:,}" if drive.host_writes is not None else "—"),
        ("Serial", drive.serial or "—"),
        ("Firmware", drive.firmware or "—"),
    ]
    reasons = ""
    if drive.health_reasons:
        reasons = (
            '<p class="reasons">'
            + html.escape(" · ".join(drive.health_reasons))
            + "</p>"
        )
    rows = []
    for attr in drive.attributes:
        rows.append(
            "<tr>"
            f"<td>{html.escape(attr.id)}</td>"
            f"<td>{html.escape(attr.name)}</td>"
            f"<td>{html.escape(attr.raw)}</td>"
            f"<td>{html.escape(attr.value or '—')}</td>"
            "</tr>"
        )
    table = ""
    if rows:
        table = (
            "<table><thead><tr><th>ID</th><th>Attribute</th><th>Raw</th><th>Value</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    err = f'<p class="reasons">{html.escape(drive.error)}</p>' if drive.error else ""
    location = "Internal" if drive.is_internal else "External"
    kind = "SSD" if drive.is_ssd else "Disk"
    return f"""
<section class="drive">
  <div class="row">
    <div class="model">{html.escape(drive.model)}</div>
    <span class="badge {health}">{health}</span>
    <span class="meta">{html.escape(drive.device_node)} · {kind} · {location}</span>
  </div>
  {err}
  {reasons}
  <div class="grid">{_stats_html(stats)}</div>
  {table}
</section>
"""
