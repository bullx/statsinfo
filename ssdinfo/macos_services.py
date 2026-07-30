"""macOS menu bar status item, activation policy, and login-item helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from .app_prefs import load_prefs, save_prefs
from .resources import app_bundle_path, menu_bar_icon_path


def is_login_item_enabled() -> bool:
    bundle = app_bundle_path()
    if bundle is None:
        return load_prefs().get("open_at_login", False)
    name = bundle.stem
    script = f'''
        tell application "System Events"
            return exists login item "{name}"
        end tell
    '''
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip().lower() == "true"
    except (subprocess.CalledProcessError, OSError):
        return load_prefs().get("open_at_login", False)


def set_open_at_login(enabled: bool) -> tuple[bool, str]:
    bundle = app_bundle_path()
    if bundle is None:
        prefs = load_prefs()
        prefs["open_at_login"] = enabled
        save_prefs(prefs)
        return False, "Open at login applies to the built .app (not python3 main.py)."

    name = bundle.stem
    path = str(bundle)
    if enabled:
        script = f'''
            tell application "System Events"
                if not (exists login item "{name}") then
                    make login item at end with properties {{path:"{path}", hidden:false}}
                end if
            end tell
        '''
    else:
        script = f'''
            tell application "System Events"
                if exists login item "{name}") then
                    delete login item "{name}"
                end if
            end tell
        '''
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, detail or "Could not update login items (Automation permission may be required)."

    prefs = load_prefs()
    prefs["open_at_login"] = enabled
    save_prefs(prefs)
    return True, ""


def set_activation_policy_menu_bar_only(menu_bar_only: bool) -> bool:
    try:
        from AppKit import (  # type: ignore[import-untyped]
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSApplicationActivationPolicyRegular,
        )

        ns_app = NSApplication.sharedApplication()
        policy = (
            NSApplicationActivationPolicyAccessory
            if menu_bar_only
            else NSApplicationActivationPolicyRegular
        )
        return bool(ns_app.setActivationPolicy_(policy))
    except ImportError:
        return False


def _load_status_image(NSImage, icon_path: Path) -> object | None:
    image = NSImage.alloc().initByReferencingFile_(str(icon_path))
    if image is None or image.size().width <= 0:
        image = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
    if image is None or image.size().width <= 0:
        return None
    image.setSize_((18.0, 18.0))
    if icon_path.suffix.lower() == ".png":
        image.setTemplate_(True)
    return image


class MenuBarController:
    """NSStatusItem + menu when PyObjC is available."""

    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_hide: Callable[[], None],
        on_refresh: Callable[[], None],
        on_toggle_menu_bar: Callable[[bool], None],
        on_toggle_login: Callable[[bool], None],
        on_quit: Callable[[], None],
        menu_bar_enabled: bool,
        login_enabled: bool,
    ) -> None:
        self._on_open = on_open
        self._on_hide = on_hide
        self._on_refresh = on_refresh
        self._on_toggle_menu_bar = on_toggle_menu_bar
        self._on_toggle_login = on_toggle_login
        self._on_quit = on_quit
        self._menu_bar_item: object | None = None
        self._menu_bar_enabled = menu_bar_enabled
        self._login_enabled = login_enabled
        self._menu_bar_check = None
        self._login_check = None
        self._available = False

        try:
            from AppKit import (  # type: ignore[import-untyped]
                NSMenu,
                NSMenuItem,
                NSStatusBar,
                NSVariableStatusItemLength,
            )
            from Foundation import NSObject  # type: ignore[import-untyped]
        except ImportError:
            return

        self._available = True
        icon_path = menu_bar_icon_path()

        class Delegate(NSObject):
            def open_(self, _sender) -> None:
                on_open()

            def hide_(self, _sender) -> None:
                on_hide()

            def refresh_(self, _sender) -> None:
                on_refresh()

            def toggleMenuBar_(self, sender) -> None:
                on_toggle_menu_bar(bool(sender.state()))

            def toggleLogin_(self, sender) -> None:
                on_toggle_login(bool(sender.state()))

            def quit_(self, _sender) -> None:
                on_quit()

        self._delegate = Delegate.alloc().init()
        status_bar = NSStatusBar.systemStatusBar()
        item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)
        self._menu_bar_item = item

        button = item.button()
        if button is not None:
            from AppKit import NSImage  # type: ignore[import-untyped]

            loaded = _load_status_image(NSImage, icon_path) if icon_path is not None else None
            if loaded is not None:
                button.setImage_(loaded)
            else:
                button.setTitle_("HW")

        menu = NSMenu.alloc().init()
        menu.addItemWithTitle_action_keyEquivalent_("Open Mac Hardware Info", "open:", "")
        menu.addItemWithTitle_action_keyEquivalent_("Hide Window", "hide:", "h")
        menu.addItemWithTitle_action_keyEquivalent_("Refresh", "refresh:", "")
        menu.addItem_(NSMenuItem.separatorItem())

        menu_bar_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Menu Bar Mode", "toggleMenuBar:", ""
        )
        menu_bar_item.setState_(1 if menu_bar_enabled else 0)
        menu.addItem_(menu_bar_item)
        self._menu_bar_check = menu_bar_item

        login_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open at Login", "toggleLogin:", ""
        )
        login_item.setState_(1 if login_enabled else 0)
        menu.addItem_(login_item)
        self._login_check = login_item

        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("Quit", "quit:", "")

        for menu_entry in menu.itemArray():
            if menu_entry is not None:
                menu_entry.setTarget_(self._delegate)

        item.setMenu_(menu)
        self._menu = menu

    @property
    def available(self) -> bool:
        return self._available

    def set_menu_bar_checked(self, enabled: bool) -> None:
        self._menu_bar_enabled = enabled
        if self._available and self._menu_bar_check is not None:
            self._menu_bar_check.setState_(1 if enabled else 0)

    def set_login_checked(self, enabled: bool) -> None:
        self._login_enabled = enabled
        if self._available and self._login_check is not None:
            self._login_check.setState_(1 if enabled else 0)

    def remove(self) -> None:
        if not self._available or self._menu_bar_item is None:
            return
        try:
            from AppKit import NSStatusBar  # type: ignore[import-untyped]

            NSStatusBar.systemStatusBar().removeStatusItem_(self._menu_bar_item)
        except Exception:  # noqa: BLE001
            pass
        self._menu_bar_item = None
