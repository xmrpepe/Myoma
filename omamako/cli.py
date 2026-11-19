"""omamako-ctl: the backend's interface. Every command prints JSON on stdout
(long-running package operations print one JSON object per line) and exits
non-zero with {"error": ...} on failure."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import __version__, apps, config, desktop, hotkey, packages, system, themes
from .util import which


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _entry(e: desktop.DesktopEntry) -> dict:
    d = e.to_dict()
    d["category"] = apps.category_of(e)
    d["favorite"] = e.id in apps.favorites()
    d["actions"] = {k: v[0] for k, v in e.actions.items()}
    return d


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omamako-ctl", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="group", required=True)

    a = sub.add_parser("apps").add_subparsers(dest="verb", required=True)
    a.add_parser("list")
    s = a.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int)
    a.add_parser("categories")
    a.add_parser("favorites")
    a.add_parser("recents")
    l = a.add_parser("launch"); l.add_argument("id"); l.add_argument("--action")
    f = a.add_parser("fav"); f.add_argument("id"); f.add_argument("state", choices=["on", "off"])
    a.add_parser("startup-run")

    p_ = sub.add_parser("power"); p_.add_argument("action"); p_.add_argument("--dry-run", action="store_true")

    n = sub.add_parser("network").add_subparsers(dest="verb", required=True)
    n.add_parser("status"); n.add_parser("online")
    w = n.add_parser("wifi"); w.add_argument("--rescan", action="store_true")
    c = n.add_parser("connect"); c.add_argument("ssid"); c.add_argument("--password-stdin", action="store_true")
    wp = n.add_parser("wifi-power"); wp.add_argument("state", choices=["on", "off"])
    u = n.add_parser("up"); u.add_argument("name")

    au = sub.add_parser("audio").add_subparsers(dest="verb", required=True)
    au.add_parser("status"); au.add_parser("sinks"); au.add_parser("mute")
    v = au.add_parser("volume"); v.add_argument("percent", type=int)
    sk = au.add_parser("sink"); sk.add_argument("name")

    d = sub.add_parser("display").add_subparsers(dest="verb", required=True)
    d.add_parser("list")
    b = d.add_parser("brightness"); b.add_argument("percent", type=int, nargs="?")

    bt = sub.add_parser("bluetooth").add_subparsers(dest="verb", required=True)
    bt.add_parser("status")
    bp = bt.add_parser("power"); bp.add_argument("state", choices=["on", "off"])
    bt.add_parser("scan")
    bd = bt.add_parser("device"); bd.add_argument("action"); bd.add_argument("mac")

    pk = sub.add_parser("pkg").add_subparsers(dest="verb", required=True)
    pk.add_parser("status"); pk.add_parser("installed"); pk.add_parser("explicit")
    s = pk.add_parser("search"); s.add_argument("query"); s.add_argument("--no-aur", action="store_true")
    i = pk.add_parser("info"); i.add_argument("name")
    pk.add_parser("updates")
    for verb in ("install", "remove"):
        x = pk.add_parser(verb); x.add_argument("names", nargs="+")
        x.add_argument("--dry-run", action="store_true")
        if verb == "install":
            x.add_argument("--source", choices=["auto", "repo", "aur"], default="auto")
    x = pk.add_parser("update"); x.add_argument("--aur", action="store_true"); x.add_argument("--dry-run", action="store_true")

    t = sub.add_parser("theme").add_subparsers(dest="verb", required=True)
    t.add_parser("list"); t.add_parser("get"); t.add_parser("css")
    ts = t.add_parser("set"); ts.add_argument("name")

    cf = sub.add_parser("config").add_subparsers(dest="verb", required=True)
    cf.add_parser("show"); cf.add_parser("init"); cf.add_parser("path")
    g = cf.add_parser("get"); g.add_argument("key")
    st = cf.add_parser("set"); st.add_argument("key"); st.add_argument("value")

    h = sub.add_parser("hotkey").add_subparsers(dest="verb", required=True)
    for verb in ("show", "install", "remove"):
        x = h.add_parser(verb); x.add_argument("--compositor")

    cl = sub.add_parser("cleanup", help="remove per-user changes before uninstalling the package")
    cl.add_argument("--purge", action="store_true", help="also delete ~/.config/omamako and saved state")

    sub.add_parser("doctor")
    return p


def _run_pkg(argv: list[str], dry: bool) -> int:
    if dry:
        out({"type": "command", "argv": argv, "terminal": packages.needs_terminal(argv)})
        return 0
    if packages.needs_terminal(argv):
        term = desktop.find_terminal(config.load()["general"]["terminal"])
        if not term:
            raise RuntimeError("AUR operations need a terminal emulator; none found")
        wrapped = term + ["sh", "-c", '"$@"; echo; printf "Finished. Press Enter to close. "; read _', "omamako"] + argv
        subprocess.Popen(wrapped, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        out({"type": "terminal", "argv": argv})
        return 0
    code = 0
    for kind, val in packages.run_stream(argv):
        if kind == "line":
            out({"type": "line", "text": val})
        else:
            code = int(val)
            out({"type": "done", "code": code})
    return code


def _result(r) -> int:
    out(r.to_dict())
    return 0 if r.ok else 1


def dispatch(a: argparse.Namespace) -> int:
    g, v = a.group, getattr(a, "verb", None)
    if g == "apps":
        if v == "list":
            out([_entry(e) for e in desktop.scan()])
        elif v == "search":
            out([_entry(e) for e in apps.search(a.query, limit=a.limit)])
        elif v == "categories":
            out({k: [_entry(e) for e in es] for k, es in apps.categories(desktop.scan()).items()})
        elif v == "favorites":
            ents = desktop.scan()
            out([_entry(e) for i in apps.favorites() if (e := apps.by_id(i, ents))])
        elif v == "recents":
            ents = desktop.scan()
            out([_entry(e) for i in apps.recent_ids() if (e := apps.by_id(i, ents))])
        elif v == "launch":
            out({"launched": apps.launch(a.id, a.action)})
        elif v == "fav":
            out(apps.set_favorite(a.id, a.state == "on"))
        elif v == "startup-run":
            out({"launched": apps.run_startup()})
    elif g == "power":
        return _result(system.power(a.action, a.dry_run))
    elif g == "network":
        if v == "status":
            out(system.network_status())
        elif v == "online":
            o = system.online(); out({"online": o}); return 0 if o else 1
        elif v == "wifi":
            out(system.wifi_list(a.rescan))
        elif v == "connect":
            pw = sys.stdin.readline().rstrip("\n") if a.password_stdin else None
            return _result(system.wifi_connect(a.ssid, pw))
        elif v == "wifi-power":
            return _result(system.wifi_power(a.state == "on"))
        elif v == "up":
            return _result(system.connection_up(a.name))
    elif g == "audio":
        if v == "status":
            out(system.audio_status())
        elif v == "volume":
            return _result(system.set_volume(a.percent))
        elif v == "mute":
            return _result(system.toggle_mute())
        elif v == "sinks":
            out(system.audio_sinks())
        elif v == "sink":
            return _result(system.set_default_sink(a.name))
    elif g == "display":
        if v == "list":
            out({"displays": system.displays(), "brightness": system.brightness(),
                 "compositor": system.compositor()})
        elif v == "brightness":
            if a.percent is None:
                out(system.brightness())
            else:
                return _result(system.set_brightness(a.percent))
    elif g == "bluetooth":
        if v == "status":
            out(system.bluetooth_status())
        elif v == "power":
            return _result(system.bluetooth_power(a.state == "on"))
        elif v == "scan":
            return _result(system.bluetooth_scan())
        elif v == "device":
            return _result(system.bluetooth_device(a.action, a.mac))
    elif g == "pkg":
        if v == "status":
            out(packages.status())
        elif v == "installed":
            out(packages.installed())
        elif v == "explicit":
            out(packages.explicit())
        elif v == "search":
            out(packages.search(a.query, aur=not a.no_aur))
        elif v == "info":
            out(packages.info(a.name))
        elif v == "updates":
            out(packages.updates())
        elif v == "install":
            return _run_pkg(packages.install(a.names, a.source), a.dry_run)
        elif v == "remove":
            return _run_pkg(packages.remove(a.names), a.dry_run)
        elif v == "update":
            return _run_pkg(packages.update(a.aur), a.dry_run)
    elif g == "theme":
        cur = config.load()["general"]["theme"]
        if v == "list":
            out({"current": cur, "themes": sorted(themes.available())})
        elif v == "get":
            out({"name": cur, "palette": themes.load(cur)})
        elif v == "css":
            print(themes.css(themes.load(cur), config.load()["launcher"]["font_size"]))
        elif v == "set":
            if a.name not in themes.available():
                raise KeyError(f"unknown theme {a.name!r}")
            out({"theme": config.set_value("general.theme", a.name)})
    elif g == "config":
        if v == "show":
            out(config.load())
        elif v == "init":
            out({"written": config.ensure_default(), "path": str(config.config_path())})
        elif v == "path":
            out({"path": str(config.config_path())})
        elif v == "get":
            out({a.key: config.get(a.key)})
        elif v == "set":
            out({a.key: config.set_value(a.key, a.value)})
    elif g == "hotkey":
        out(getattr(hotkey, v)(a.compositor))
    elif g == "cleanup":
        import shutil
        from .util import config_dir, state_dir
        removed = []
        for comp in ("hyprland", "sway", "i3"):
            try:
                if hotkey.remove(comp)["removed"]:
                    removed.append(f"hotkey binding ({comp})")
            except (ValueError, OSError):
                pass
        if a.purge:
            for d in (config_dir(), state_dir()):
                if d.exists():
                    shutil.rmtree(d)
                    removed.append(str(d))
        out({"removed": removed, "hint": "now run: sudo pacman -Rns omamako"})
    elif g == "doctor":
        tools = ["pacman", "paru", "yay", "pkexec", "checkupdates", "nmcli", "wpctl", "pactl",
                 "bluetoothctl", "brightnessctl", "hyprctl", "swaymsg", "xrandr", "systemctl", "loginctl"]
        out({"compositor": system.compositor(), "tools": {t: bool(which(t)) for t in tools},
             "online": system.online()})
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except (KeyError, ValueError, RuntimeError, ConnectionError, OSError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        out({"error": str(msg)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
