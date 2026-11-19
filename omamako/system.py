"""System menu backend: power, network, audio, display, bluetooth.

Every function shells out to the standard tool for the job and degrades to a
clear error/empty result if that tool is missing. Nothing here needs root.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess

from .util import Result, run, which

# ---------------------------------------------------------------- compositor

def compositor() -> str:
    env = os.environ
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if env.get("SWAYSOCK"):
        return "sway"
    if env.get("I3SOCK"):
        return "i3"
    if env.get("XDG_SESSION_TYPE") == "x11" or (env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY")):
        return "x11"
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "unknown"


# --------------------------------------------------------------------- power

LOCKERS = ["hyprlock", "swaylock", "i3lock", "xsecurelock", "slock"]


def _lock_cmd() -> list[str]:
    for l in LOCKERS:
        if which(l):
            return [l]
    return ["loginctl", "lock-session"]


def _logout_cmd() -> list[str]:
    c = compositor()
    if c == "hyprland" and which("hyprctl"):
        return ["hyprctl", "dispatch", "exit"]
    if c == "sway" and which("swaymsg"):
        return ["swaymsg", "exit"]
    if c == "i3" and which("i3-msg"):
        return ["i3-msg", "exit"]
    return ["loginctl", "terminate-user", os.environ.get("USER", "")]


def power_commands() -> dict[str, list[str]]:
    return {
        "lock": _lock_cmd(),
        "logout": _logout_cmd(),
        "suspend": ["systemctl", "suspend"],
        "hibernate": ["systemctl", "hibernate"],
        "reboot": ["systemctl", "reboot"],
        "shutdown": ["systemctl", "poweroff"],
    }


def power(action: str, dry_run: bool = False) -> Result:
    cmds = power_commands()
    if action not in cmds:
        raise KeyError(f"unknown power action {action!r}; choose from {', '.join(cmds)}")
    argv = cmds[action]
    if dry_run:
        return Result(True, 0, " ".join(argv), "", argv)
    return run(argv, timeout=20)


# ------------------------------------------------------------------- network

def online(timeout: float = 2.0) -> bool:
    """True if a TCP connection to a well-known HTTPS endpoint succeeds."""
    for host in ("archlinux.org", "1.1.1.1"):
        try:
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _nm_split(line: str) -> list[str]:
    """Split nmcli -t output: ':' separates fields, '\\:' is a literal colon."""
    out, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if c == ":":
            out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    out.append(cur)
    return out


def network_status() -> dict:
    st = {"online": online(), "manager": bool(which("nmcli")),
          "wifi": None, "connections": []}
    if not st["manager"]:
        return st
    r = run(["nmcli", "-t", "-f", "WIFI", "radio"])
    if r.ok:
        st["wifi"] = r.out.strip() == "enabled"
    r = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    if r.ok:
        for line in r.out.splitlines():
            f = _nm_split(line)
            if len(f) >= 3:
                st["connections"].append({"name": f[0], "type": f[1], "device": f[2]})
    return st


def wifi_list(rescan: bool = False) -> list[dict]:
    argv = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
    if rescan:
        argv += ["--rescan", "yes"]
    r = run(argv, timeout=25)
    nets, seen = [], set()
    if not r.ok:
        return nets
    for line in r.out.splitlines():
        f = _nm_split(line)
        if len(f) < 4 or not f[1] or f[1] in seen:
            continue
        seen.add(f[1])
        nets.append({"ssid": f[1], "signal": int(f[2] or 0), "security": f[3],
                     "active": f[0] == "*"})
    return sorted(nets, key=lambda n: (not n["active"], -n["signal"]))


def wifi_connect(ssid: str, password: str | None = None) -> Result:
    """Connect to a network. The password goes in on stdin (nmcli --ask),
    never on the command line where `ps` could show it."""
    if password:
        return run(["nmcli", "--ask", "device", "wifi", "connect", ssid],
                   timeout=60, input=password + "\n")
    return run(["nmcli", "device", "wifi", "connect", ssid], timeout=60)


def wifi_power(on: bool) -> Result:
    return run(["nmcli", "radio", "wifi", "on" if on else "off"])


def connection_up(name: str) -> Result:
    return run(["nmcli", "connection", "up", "id", name], timeout=60)


def network_editor() -> list[str] | None:
    for c in ("nm-connection-editor", "nmtui"):
        if which(c):
            return [c]
    return None


# --------------------------------------------------------------------- audio

SINK = "@DEFAULT_AUDIO_SINK@"


def audio_status() -> dict:
    r = run(["wpctl", "get-volume", SINK])
    if r.ok:
        m = re.search(r"Volume:\s*([\d.]+)", r.out)
        if m:
            return {"backend": "wpctl", "volume": round(float(m.group(1)) * 100),
                    "muted": "[MUTED]" in r.out}
    r = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    if r.ok:
        m = re.search(r"(\d+)%", r.out)
        mute = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        return {"backend": "pactl", "volume": int(m.group(1)) if m else 0,
                "muted": "yes" in mute.out}
    return {"backend": None, "volume": 0, "muted": False}


def set_volume(percent: int) -> Result:
    percent = max(0, min(150, int(percent)))
    if which("wpctl"):
        return run(["wpctl", "set-volume", SINK, f"{percent}%"])
    return run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])


def toggle_mute() -> Result:
    if which("wpctl"):
        return run(["wpctl", "set-mute", SINK, "toggle"])
    return run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])


def audio_sinks() -> list[dict]:
    r = run(["pactl", "--format=json", "list", "sinks"])
    if r.ok:
        try:
            default = run(["pactl", "get-default-sink"]).out.strip()
            return [{"name": s["name"], "description": s.get("description", s["name"]),
                     "default": s["name"] == default} for s in json.loads(r.out)]
        except (ValueError, KeyError, TypeError):
            pass
    r = run(["pactl", "list", "short", "sinks"])
    return [{"name": l.split("\t")[1], "description": l.split("\t")[1], "default": False}
            for l in r.out.splitlines() if "\t" in l] if r.ok else []


def set_default_sink(name: str) -> Result:
    return run(["pactl", "set-default-sink", name])


# ------------------------------------------------------------------- display

def displays() -> list[dict]:
    c = compositor()
    if c == "hyprland" and which("hyprctl"):
        r = run(["hyprctl", "monitors", "-j"])
        if r.ok:
            try:
                return [{"name": m["name"], "width": m["width"], "height": m["height"],
                         "refresh": round(m.get("refreshRate", 0), 2), "scale": m.get("scale", 1)}
                        for m in json.loads(r.out)]
            except (ValueError, KeyError):
                pass
    if c in ("sway",) and which("swaymsg"):
        r = run(["swaymsg", "-t", "get_outputs", "-r"])
        if r.ok:
            try:
                return [{"name": o["name"], "width": o["current_mode"]["width"],
                         "height": o["current_mode"]["height"],
                         "refresh": round(o["current_mode"]["refresh"] / 1000, 2),
                         "scale": o.get("scale", 1)} for o in json.loads(r.out) if o.get("active")]
            except (ValueError, KeyError):
                pass
    if which("xrandr"):
        r = run(["xrandr", "--query"])
        outs = []
        for m in re.finditer(r"^(\S+) connected(?: primary)? (\d+)x(\d+)", r.out, re.M):
            outs.append({"name": m[1], "width": int(m[2]), "height": int(m[3]),
                         "refresh": None, "scale": 1})
        return outs
    return []


def brightness() -> dict | None:
    r = run(["brightnessctl", "-m"])
    if not r.ok or not r.out.strip():
        return None
    f = r.out.strip().splitlines()[0].split(",")
    try:
        return {"device": f[0], "percent": int(f[3].rstrip("%"))}
    except (IndexError, ValueError):
        return None


def set_brightness(percent: int) -> Result:
    return run(["brightnessctl", "set", f"{max(1, min(100, int(percent)))}%"])


def display_tool() -> list[str] | None:
    for c in ("nwg-displays", "wdisplays", "arandr", "lxrandr"):
        if which(c):
            return [c]
    return None


# ----------------------------------------------------------------- bluetooth

_MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def bluetooth_status() -> dict:
    if not which("bluetoothctl"):
        return {"available": False, "powered": False, "devices": []}
    r = run(["bluetoothctl", "show"])
    if not r.ok or "Powered:" not in r.out:
        return {"available": False, "powered": False, "devices": []}
    powered = re.search(r"Powered:\s*(\w+)", r.out).group(1) == "yes"
    devices = []
    for line in run(["bluetoothctl", "devices"]).out.splitlines():
        m = re.match(r"Device\s+(\S+)\s+(.*)", line)
        if not m:
            continue
        info = run(["bluetoothctl", "info", m[1]]).out
        devices.append({
            "mac": m[1], "name": m[2],
            "connected": bool(re.search(r"Connected:\s*yes", info)),
            "paired": bool(re.search(r"Paired:\s*yes", info)),
        })
    return {"available": True, "powered": powered, "devices": devices}


def bluetooth_power(on: bool) -> Result:
    return run(["bluetoothctl", "power", "on" if on else "off"])


def bluetooth_scan(seconds: int = 6) -> Result:
    return run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 10)


def bluetooth_device(action: str, mac: str) -> Result:
    if action not in ("connect", "disconnect", "pair", "trust", "remove"):
        raise KeyError(action)
    if not _MAC.match(mac):
        raise ValueError(f"not a Bluetooth address: {mac!r}")
    return run(["bluetoothctl", action, mac], timeout=30)


def bluetooth_manager() -> list[str] | None:
    for c in ("blueman-manager", "overskride", "bluetui"):
        if which(c):
            return [c]
    return None
