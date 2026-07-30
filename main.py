#!/usr/bin/env python3
"""Mac Hardware Info — SSD SMART + battery health viewer for macOS."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mac Hardware Info — SSD SMART + battery health")
    parser.add_argument("--cli", action="store_true", help="Print a text summary instead of opening the GUI")
    parser.add_argument("--json", metavar="PATH", help="Export JSON report to PATH (CLI mode)")
    parser.add_argument("--html", metavar="PATH", help="Export HTML report to PATH (CLI mode)")
    parser.add_argument("--ssd-only", action="store_true", help="Only include solid-state drives")
    parser.add_argument(
        "--menu-bar",
        action="store_true",
        help="Run as menu bar accessory (hide Dock icon; close button hides window)",
    )
    args = parser.parse_args(argv)

    if args.cli or args.json or args.html:
        from ssdinfo.battery import scan_battery
        from ssdinfo.export import export_html, export_json
        from ssdinfo.scanner import scan_drives

        drives = scan_drives(ssd_only=args.ssd_only)
        battery = scan_battery()
        if args.json:
            export_json(drives, args.json, battery=battery)
            print(f"Wrote {args.json}")
        if args.html:
            export_html(drives, args.html, battery=battery)
            print(f"Wrote {args.html}")
        if args.cli or not (args.json or args.html):
            print("== Storage ==")
            for d in drives:
                temp = f"{d.temperature_c}°C" if d.temperature_c is not None else "—"
                used = f"{d.percentage_used}%" if d.percentage_used is not None else "—"
                spare = f"{d.available_spare}%" if d.available_spare is not None else "—"
                written = f"{d.data_written_tb:.2f}TB" if d.data_written_tb is not None else "—"
                print(
                    f"{d.device_node}\t{d.model}\t{d.health.value}\t"
                    f"temp={temp}\tused={used}\tspare={spare}\twritten={written}"
                )
                if d.health_reasons:
                    print(f"  {' · '.join(d.health_reasons)}")
            print("== Battery ==")
            if not battery.installed:
                print(battery.error or "No internal battery")
            else:
                design = f"{battery.design_capacity_mah} mAh" if battery.design_capacity_mah else "—"
                full = f"{battery.max_capacity_mah} mAh" if battery.max_capacity_mah else "—"
                current = f"{battery.current_capacity_mah} mAh" if battery.current_capacity_mah else "—"
                cycles = str(battery.cycle_count) if battery.cycle_count is not None else "—"
                charge = f"{battery.charge_percent}%" if battery.charge_percent is not None else "—"
                max_pct = f"{battery.max_capacity_percent}%" if battery.max_capacity_percent is not None else "—"
                print(
                    f"{battery.device_name}\t{battery.health.value}\t"
                    f"design={design}\tfull_charge={full}\tcurrent={current}\t"
                    f"charge={charge}\tmax_pct={max_pct}\tcycles={cycles}"
                )
                if battery.health_reasons:
                    print(f"  {' · '.join(battery.health_reasons)}")
        return 0

    from ssdinfo.gui import run

    run(menu_bar_mode=True if args.menu_bar else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
