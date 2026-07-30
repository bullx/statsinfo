# Project context — Mac Hardware Info

Internal notes for development and publishing. Public docs: [README.md](README.md).

## Product summary

| | |
|---|---|
| **Name** | Mac Hardware Info |
| **Version** | 0.3.1 (`ssdinfo.__version__` / `setup.py`) |
| **Pitch** | Native macOS SSD NVMe health + battery mAh + Apple Silicon fan curves |
| **Platform** | macOS 14+ (Apple Silicon + Intel; fan control Apple Silicon only) |
| **UI** | Python + Tkinter (daylight theme; Storage / Battery / Thermal) |
| **Distribution** | `.app` via py2app + zip (`make release`); optional notarized GitHub Releases |
| **License** | MIT |
| **Icon** | `assets/AppIcon.icns` (option C — Settings Tool) |

No Homebrew. No smartctl. System `python3` for builds (no venv required).  
Original fan-control code only (no copying third-party fan-tool source; public SMC key names OK).

## What’s implemented (to date)

### Storage / NVMe
- [x] Physical disk discovery (`diskutil`)
- [x] IOKit identity (model, serial, firmware, vendor, NAND, NVMe version)
- [x] Native NVMe health helper (`native/nvme_health.c` → `ssdinfo/bin/nvme_health`)
- [x] Full health log fields: temp, spare, % used, data R/W TB, power-on hours, cycles, unsafe shutdowns, media errors, critical warning, host commands
- [x] Health scoring Good / Caution / Bad
- [x] Attribute detail list in UI
- [x] JSON + HTML export

### Battery
- [x] Design / Full Charge / Current capacity in **mAh** (AppleSmartBattery)
- [x] Charge %, max capacity % vs design, cycles, condition
- [x] Temperature (deci-Kelvin → °C, fixed ÷10)
- [x] Amperage signed mA with charging / discharging labels
- [x] Desktop “no battery” detection
- [x] CLI + export include battery block

### Thermal / fans (Apple Silicon)
- [x] `native/smc_thermal.c` → `ssdinfo/bin/smc_thermal` (`status` / `auto` / `set` / `daemon`)
- [x] Unprivileged status JSON (temps + fans); Apple Silicon gate; fanless detect
- [x] Thermal UI: sensor tiles, fan RPM, Auto/Manual pill, curve canvas + point edits
- [x] Profiles: Silent / Balanced / Performance / Full + custom under Application Support
- [x] Privileged double-fork **daemon** started once via `osascript` admin
- [x] State file drives the loop (`active` / `stop` / curve points / `emergency_c`)
- [x] **Apply** → `active=true` (elevate only if daemon not already running)
- [x] **Stop** → `active=false` (restore Auto, daemon stays alive — no second password)
- [x] **Quit** → `stop=true` (restore Auto and exit daemon)
- [x] Safety: min/max clamp, slew (~800 RPM/step), emergency max near critical °C, restore Auto on exit
- [x] Thermal live poll ~1.5s while Thermal tab open or Manual active
- [x] Root-daemon PID detection: treat `kill(0)` EPERM as alive; world-readable `/tmp/smc_thermal_daemon.pid`

### App / packaging
- [x] GUI with Storage / Battery / Thermal segments
- [x] Refresh + Auto Refresh (3s live updates; keeps selected drive)
- [x] Modern Tk UI kit: `Pressable`, `Segment`, `MetricTile`, `StatusPill`, `ProgressBar`
- [x] Hover / press / Tab focus rings; system cursor (no hand pointer)
- [x] Primary metric hierarchy (4 storage tiles; secondary + SMART in Details)
- [x] Battery hero: charge bars + mAh row first; secondary grid below
- [x] Background-thread scan (UI stays responsive) + skeleton loading pulse
- [x] In-place drive list updates; empty state; “Updated just now” status flash
- [x] Animated battery bars; health-pill flash on status change
- [x] Menu bar status item (`NSStatusItem`) in built `.app` via PyObjC
- [x] Menu Bar mode: `NSApplicationActivationPolicyAccessory` (no Dock icon; close hides window)
- [x] Open at Login toggle (Login Items via `System Events` / AppleScript)
- [x] Preferences JSON under Application Support (`menu_bar_mode`, `open_at_login`, `start_hidden`)
- [x] Menu bar assets bundled (`Contents/Resources/assets/AppIcon-128.png`)
- [x] `make helper` builds **both** `nvme_health` and `smc_thermal`
- [x] py2app bundles helpers + PyObjC + icon
- [x] README / LICENSE / `.gitignore`

### Not done yet
- [x] Real `CFBundleIdentifier` (`com.karan.machardwareinfo`)
- [x] Universal binary helpers (arm64 + x86_64 via `make helper`)
- [ ] Developer ID codesign + notarization (no signing identity on this Mac yet)
- [ ] SMAppService permanently installed privileged helper (needs Team ID / signing)
- [ ] License / activation system (discussed, not coded)
- [ ] Intel fan control; per-app / AC-vs-battery auto profile switching
- [ ] Live stats in menu bar title (battery % / temp) without opening window

## Data sources

| Source | Data |
|---|---|
| `ssdinfo/bin/nvme_health` | NVMe SMART log via `IONVMeSMARTInterface.SMARTReadData` |
| `ssdinfo/bin/smc_thermal` | AppleSMC temps + fan RPM; privileged set / auto / curve daemon |
| `diskutil` | Device list, size, SSD flag, protocol, verified/failing |
| `ioreg` (NVMe / ANS / IOBlockStorageDriver) | Vendor, NAND, NVMe version, since-boot I/O stats |
| `ioreg` `AppleSmartBattery` | DesignCapacity, AppleRawMaxCapacity, AppleRawCurrentCapacity, CycleCount, Temperature, InstantAmperage, … |
| `pmset -g batt` | Charge %, power source |
| `system_profiler SPPowerDataType` | Condition, Maximum Capacity % |

### Battery field map

| UI label | IOKit key |
|---|---|
| Design Capacity (mAh) | `DesignCapacity` |
| Full Charge Capacity (mAh) | `AppleRawMaxCapacity` (fallback `NominalChargeCapacity`) |
| Current Charge (mAh) | `AppleRawCurrentCapacity` |
| Max Capacity % | `MaxCapacity` (0–100) and/or full÷design |
| Charge % | `pmset` / `CurrentCapacity` when percent |
| Temperature | `Temperature` as deci-Kelvin → `value/10 - 273.15` |
| Amperage | `InstantAmperage` signed; − = discharging, + = charging |

### Menu bar & preferences

| Path | Role |
|---|---|
| `~/Library/Application Support/Mac Hardware Info/preferences.json` | `menu_bar_mode`, `open_at_login`, `start_hidden` |
| `Contents/Resources/assets/AppIcon-128.png` | Menu bar template icon (bundled) |

| Pref | Meaning |
|---|---|
| `menu_bar_mode: true` | Accessory app — no Dock icon; close button hides window |
| `open_at_login: true` | Registered in macOS Login Items |
| `start_hidden: true` | When **both** menu bar + login item: launch without showing window |

Manual `.app` launch always shows the window. Background-only startup applies when launched via Login Item with both toggles on.

Menu bar menu: **Open**, **Hide Window** (⌘H), **Refresh**, toggles, **Quit**.

### Fan control state

| Path | Role |
|---|---|
| `~/Library/Application Support/Mac Hardware Info/fan_profiles.json` | Custom saved curves |
| `~/Library/Application Support/Mac Hardware Info/fan_control_state.json` | Daemon instructions |
| `/tmp/smc_thermal_daemon.pid` | World-readable daemon PID (root-owned process) |
| `/tmp/smc_thermal_daemon.log` | Daemon events (`daemon_start`, `paused_auto`, `daemon_exit`, …) |

State JSON semantics:

| Field | Meaning |
|---|---|
| `active: true` | Apply curve (manual) |
| `active: false` | Restore Auto; **daemon stays alive** (Stop) |
| `stop: true` | Restore Auto and **exit daemon** (app quit) |
| `points` / `emergency_c` | Curve + emergency threshold |

Do **not** call `request_stop()` before Apply — that exits the daemon and forces another password.

## Architecture

```
main.py
  ├─ GUI  → ssdinfo.gui.App
  │         refresh / auto-refresh (3s)
  │         Thermal live poll (~1.5s on Thermal / while Manual)
  │           → background thread: scan_drives + scan_battery + scan_thermal
  │           → after(0) marshal results back to UI
  │         menu bar: macos_services.MenuBarController (PyObjC NSStatusItem)
  │         Menu Bar mode → setActivationPolicy(Accessory); close → withdraw
  │         Quit (menu or _on_quit) → request_stop (stop=true) → destroy
  │         Apply → write state (active=true) → elevate once if needed
  │         Stop  → request_pause (active=false)
  └─ CLI  → print / --json / --html / --menu-bar

ssdinfo.gui / thermal_panel
  Storage · Battery · Thermal (curve editor + profiles)

ssdinfo.macos_services / app_prefs / resources
  status item, login item, activation policy, preferences, asset paths

ssdinfo.scanner / battery / thermal
  diskutil + ioreg + AppleSmartBattery + AppleSMC helper

ssdinfo.fan_control / profiles
  osascript admin → smc_thermal daemon --state <path>
  daemon polls state file → set_fan_manual / restore_all_auto

native/nvme_health.c · native/smc_thermal.c
  IOKit helpers → JSON stdout
```

## Health scoring

### Drives
- **Good**: disk health Verified / NVMe log OK, spare above threshold, wear/temp normal
- **Caution**: elevated wear/temp, NAND not Ready, some I/O errors
- **Bad**: Failing, critical warning, spare ≤ threshold, media errors, severe wear/temp

### Battery
- **Good**: condition Normal, full charge capacity healthy, cycles OK
- **Caution**: Replace Soon / capacity &lt; 80% / high cycles
- **Bad**: Service / Replace Now / capacity &lt; 60% / hot pack

## Build commands

```bash
make helper      # compile nvme_health.c + smc_thermal.c
make app         # helper + python3 setup.py py2app
make zip         # zip dist/*.app
make release     # app + zip
make clean       # remove helper binaries
make clean-dist  # remove build/ and dist/
```

Force-rebuild helpers if Make says nothing to do:

```bash
make clean && make helper
```

Python for packaging: `PYTHON=python3` (Makefile default). Install once:

```bash
pip3 install -r requirements-build.txt   # py2app + pyobjc-framework-Cocoa (menu bar)
```

## Publishing checklist

1. [x] Set real `CFBundleIdentifier` in `setup.py` (`com.karan.machardwareinfo`)
2. [x] LICENSE copyright (`Copyright (c) 2026 Karan`)
3. [x] Universal helpers (`-arch arm64 -arch x86_64`)
4. [x] `make release` (ad-hoc signed `.app` + zip)
5. [ ] Developer ID codesign + notarize — Gatekeeper-clean downloads
6. [ ] GitHub Release with `MacHardwareInfo-0.3.1-macos.zip`
7. [ ] Smoke-test: MacBook battery mAh + desktop “no battery”
8. [ ] Smoke-test: NVMe health on Apple Silicon internal SSD
9. [ ] Smoke-test Thermal: Apply (password once) → Manual + rising target/RPM; Stop → Auto no password; quit → Auto
10. [ ] Confirm Dock icon (Settings Tool) appears on fresh build
11. [ ] Smoke-test menu bar: status icon visible; Open / Hide / Quit; Login Item startup

## Safety

Storage / battery paths are read-only: `diskutil`, `ioreg`, `pmset`, `system_profiler`, IOKit SMARTReadData.  
No erase, repair, partition, or write paths to disks.

**Thermal exception:** `smc_thermal` may write AppleSMC fan keys when the user explicitly enables **Apply Manual** (admin password once to start the daemon). Safety clamps: SMC min/max RPM, slew limiting, emergency full speed near critical temp, restore **Auto** on Stop / quit / daemon exit. Apple Silicon only; fanless Macs are monitor-only. Incorrect curves can increase noise or heat — use carefully.
