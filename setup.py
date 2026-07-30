"""py2app setup for Mac Hardware Info."""

from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent
BIN = ROOT / "ssdinfo" / "bin"
HELPERS = [p for p in (BIN / "nvme_health", BIN / "smc_thermal") if p.is_file()]

APP = ["main.py"]
ASSETS = ROOT / "assets"
DATA_FILES = []
if HELPERS:
    DATA_FILES.append(("ssdinfo/bin", [str(p) for p in HELPERS]))
MENU_BAR_ICONS = [
    ASSETS / "AppIcon-128.png",
    ASSETS / "icons" / "C-settings-tool.png",
]
DATA_FILES.append(
    ("assets", [str(p) for p in MENU_BAR_ICONS if p.is_file()])
)

OPTIONS = {
    "argv_emulation": False,
    "packages": ["ssdinfo"],
    "includes": [
        "ssdinfo.gui",
        "ssdinfo.gui_theme",
        "ssdinfo.scanner",
        "ssdinfo.battery",
        "ssdinfo.export",
        "ssdinfo.models",
        "ssdinfo.nvme_health",
        "ssdinfo.thermal",
        "ssdinfo.thermal_panel",
        "ssdinfo.fan_control",
        "ssdinfo.profiles",
        "ssdinfo.app_prefs",
        "ssdinfo.macos_services",
        "ssdinfo.resources",
    ],
    "iconfile": str(ROOT / "assets" / "AppIcon.icns"),
    "plist": {
        "CFBundleName": "Mac Hardware Info",
        "CFBundleDisplayName": "Mac Hardware Info",
        "CFBundleIdentifier": "com.karan.machardwareinfo",
        "CFBundleVersion": "0.3.1",
        "CFBundleShortVersionString": "0.3.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "NSHumanReadableCopyright": "Copyright © 2026 Karan Chimedia",
    },
}

setup(
    name="MacHardwareInfo",
    version="0.3.1",
    description="Native SSD + battery + thermal for macOS",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
