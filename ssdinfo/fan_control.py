"""Privileged fan curve daemon control (Apple Silicon)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

from .models import FanProfile
from .profiles import STATE_PATH, request_pause, request_stop, write_control_state
from .thermal import helper_path, scan_thermal

PID_PATH = Path("/tmp/smc_thermal_daemon.pid")
LOG_PATH = Path("/tmp/smc_thermal_daemon.log")


def _as_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pid_running(pid: int) -> bool:
    """True if pid exists. Root daemons raise EPERM for kill(0) from user — that still means alive."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        # ESRCH = gone; EPERM = alive but not signalable by this user
        if getattr(exc, "errno", None) == 3:  # ESRCH
            return False
        if getattr(exc, "errno", None) == 1:  # EPERM
            return True
        return False


def _daemon_pid_from_file() -> int | None:
    if PID_PATH.is_file():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            if _pid_running(pid):
                return pid
        except (OSError, ValueError):
            pass
    try:
        out = subprocess.run(
            ["pgrep", "-x", "smc_thermal"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (out.stdout or "").splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if _pid_running(pid):
                return pid
    except OSError:
        pass
    return None


def _pid_from_log() -> int | None:
    if not LOG_PATH.is_file():
        return None
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Prefer the last daemon_start event
    import re

    matches = re.findall(r'"daemon_start","pid":(\d+)', text)
    if not matches:
        matches = re.findall(r'"pid":(\d+)', text)
    for raw in reversed(matches):
        try:
            pid = int(raw)
        except ValueError:
            continue
        if _pid_running(pid):
            return pid
    return None


class FanController:
    def __init__(self) -> None:
        self._active = False
        self._profile_name: str | None = None
        self._daemon_pid: int | None = _daemon_pid_from_file()

    @property
    def active(self) -> bool:
        self._refresh_daemon_pid()
        return self._active

    @property
    def profile_name(self) -> str | None:
        return self._profile_name

    def _refresh_daemon_pid(self) -> None:
        pid = self._daemon_pid
        if pid is not None and not _pid_running(pid):
            pid = None
        if pid is None:
            pid = _daemon_pid_from_file()
        self._daemon_pid = pid
        if pid is None and self._active:
            self._active = False
            self._profile_name = None

    def _daemon_alive(self) -> bool:
        self._refresh_daemon_pid()
        return self._daemon_pid is not None

    def _clear_stop_flag(self) -> None:
        if not STATE_PATH.is_file():
            return
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            data["stop"] = False
            STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def _start_daemon(self) -> tuple[bool, str]:
        helper = helper_path()
        if helper is None:
            return False, "smc_thermal helper missing — run: make helper"

        self._clear_stop_flag()

        cmd = (
            f"{shlex.quote(str(helper))} daemon --state {shlex.quote(str(STATE_PATH))} "
            f"--log {shlex.quote(str(LOG_PATH))}"
        )
        script = f"do shell script {_as_quote(cmd)} with administrator privileges"
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "authorization failed").strip()
            return False, err

        pid: int | None = None
        for line in (result.stdout or "").strip().splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)

        # Root daemon: kill(0) may EPERM; pid file may appear slightly after osascript returns.
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if pid is not None and _pid_running(pid):
                break
            found = _daemon_pid_from_file() or _pid_from_log()
            if found is not None:
                pid = found
                break
            time.sleep(0.15)
        else:
            if pid is None or not _pid_running(pid):
                pid = _daemon_pid_from_file() or _pid_from_log()

        if pid is None or not _pid_running(pid):
            detail = "no process"
            if LOG_PATH.is_file():
                try:
                    tail = LOG_PATH.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    if tail:
                        detail = tail[-1]
                except OSError:
                    pass
            return False, f"Fan daemon failed to start ({detail})"

        self._daemon_pid = pid
        try:
            PID_PATH.write_text(str(pid), encoding="utf-8")
        except OSError:
            pass
        return True, f"daemon pid {pid}"

    def apply(self, profile: FanProfile) -> tuple[bool, str]:
        if helper_path() is None:
            return False, "smc_thermal helper missing — run: make helper"

        write_control_state(profile, active=True, stop=False)

        if not self._daemon_alive():
            ok, msg = self._start_daemon()
            if not ok:
                return False, msg
            write_control_state(profile, active=True, stop=False)

        time.sleep(1.2)
        snap = scan_thermal()
        tgt = snap.fans[0].target_rpm if snap.fans else None
        rpm = snap.fans[0].rpm if snap.fans else None

        self._active = True
        self._profile_name = profile.name
        note = f"Manual: {profile.name}"
        if self._daemon_pid:
            note += f" · pid {self._daemon_pid}"
        if tgt is not None:
            note += f" · target {tgt:.0f}"
        if rpm is not None:
            note += f" · now {rpm:.0f} RPM"
        return True, note

    def stop(self, *, elevate_auto: bool = True) -> tuple[bool, str]:
        # Pause only — daemon stays resident → no second password.
        _ = elevate_auto
        request_pause()
        self._active = False
        self._profile_name = None
        time.sleep(0.8)
        return True, "Returned fans to Auto"

    def shutdown(self) -> None:
        """App quit: restore Auto and exit daemon (no password)."""
        request_stop()
        self._active = False
        self._profile_name = None
        self._daemon_pid = None


_controller: FanController | None = None


def get_controller() -> FanController:
    global _controller
    if _controller is None:
        _controller = FanController()
    return _controller
