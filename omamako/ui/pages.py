"""Every menu of the launcher, built from backend calls. Pages never run
privileged commands themselves: package changes go through backend argv
builders (pkexec) and always pass a confirmation page first."""

from __future__ import annotations

import os
import shlex
import subprocess

from gi.repository import Gtk, Pango

from .. import apps, config, desktop, hotkey, packages, system, themes
from ..util import config_dir, which
from .model import Item, Page, heading

# ------------------------------------------------------------------ helpers


def _launch_argv(argv: list[str]) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _in_terminal(argv: list[str]) -> list[str]:
    term = desktop.find_terminal(config.load()["general"]["terminal"])
    if not term:
        raise RuntimeError("no terminal emulator found")
    return term + argv


def _bar(pct: int, width: int = 14) -> str:
    n = round(max(0, min(100, pct)) / 100 * width)
    return "█" * n + "░" * (width - n) + f" {pct}%"


def _nav_item(nav, label, factory, hint="›") -> Item:
    return Item(label, hint, lambda: nav.push(factory(nav)))


def confirm(nav, title: str, question: str, label: str, action, danger=True) -> Page:
    def build(_q):
        return [Item("Cancel", activate=nav.pop),
                Item(label, activate=action, danger=danger)]
    return Page(title=title, build=build, default_cancel=True)


# --------------------------------------------------------------------- home

def _app_item(nav, e: desktop.DesktopEntry) -> Item:
    def launch():
        try:
            apps.launch(e.id)
        except Exception as ex:
            nav.toast(f"Could not start {e.name}: {ex}", ok=False)
            return
        nav.done()

    def fav():
        on = e.id not in apps.favorites()
        apps.set_favorite(e.id, on)
        nav.toast(f"{'Added' if on else 'Removed'} favorite: {e.name}")
        nav.win.render()

    star = "★ " if e.id in apps.favorites() else ""
    return Item(star + e.name, e.comment or e.generic_name or apps.category_of(e),
                launch, fav=fav, key=e.id)


def command_index(nav) -> list[Item]:
    """Quick commands that also show up when searching from the home screen."""
    def power(a):
        return lambda: _power_go(nav, a)
    return [
        Item("Lock screen", "power", power("lock")),
        Item("Log out", "power", power("logout")),
        Item("Suspend", "power", power("suspend")),
        Item("Reboot", "power", power("reboot")),
        Item("Shut down", "power", power("shutdown")),
        Item("Wi-Fi networks", "network", lambda: nav.push(wifi_page(nav))),
        Item("Volume", "audio", lambda: nav.push(audio_page(nav))),
        Item("Bluetooth", "system", lambda: nav.push(bluetooth_page(nav))),
        Item("Display", "system", lambda: nav.push(display_page(nav))),
        Item("Update system", "packages", lambda: nav.push(update_confirm(nav))),
        Item("Install packages", "packages", lambda: nav.push(pkg_search_page(nav))),
        Item("Themes", "settings", lambda: nav.push(theme_page(nav))),
    ]


def home(nav) -> Page:
    def build(q: str) -> list[Item]:
        q = q.strip()
        if q:
            items = [_app_item(nav, e) for e in apps.search(q, nav.entries, limit=40)]
            ql = q.lower()
            cmds = [c for c in command_index(nav) if ql in c.label.lower()]
            if cmds:
                items += [heading("Commands")] + cmds
            if not items:
                items = [heading(f"No results for “{q}”")]
            return items
        ents = {e.id: e for e in nav.entries}
        items: list[Item] = []
        favs = [ents[i] for i in apps.favorites() if i in ents]
        if favs:
            items += [heading("Favorites")] + [_app_item(nav, e) for e in favs]
        rec = [ents[i] for i in apps.recent_ids() if i in ents and i not in apps.favorites()]
        if rec:
            items += [heading("Recent")] + [_app_item(nav, e) for e in rec]
        items += [heading("Menu"),
                  _nav_item(nav, "All apps", all_apps_page),
                  _nav_item(nav, "Categories", categories_page),
                  _nav_item(nav, "System", system_page),
                  _nav_item(nav, "Packages", packages_page),
                  _nav_item(nav, "Settings", settings_page)]
        return items

    return Page(title="omamako", build=build, entry=True, placeholder="Search apps and commands…")


def all_apps_page(nav) -> Page:
    return Page(title="Apps", entry=True, placeholder="Filter…",
                build=lambda q: [_app_item(nav, e) for e in apps.search(q, nav.entries)] or [heading("No apps found")])


def categories_page(nav) -> Page:
    cats = apps.categories(nav.entries)

    def cat(name, ents):
        return Page(title=name, entry=True, placeholder="Filter…",
                    build=lambda q: [_app_item(nav, e) for e in apps.search(q, ents)])
    return Page(title="Categories",
                build=lambda _q: [Item(n, str(len(es)), (lambda n=n, es=es: nav.push(cat(n, es))))
                                  for n, es in cats.items()])


# ------------------------------------------------------------------- system

def system_page(nav) -> Page:
    return Page(title="System", build=lambda _q: [
        _nav_item(nav, "Power", power_page), _nav_item(nav, "Network", network_page),
        _nav_item(nav, "Audio", audio_page), _nav_item(nav, "Display", display_page),
        _nav_item(nav, "Bluetooth", bluetooth_page)])


POWER = [("lock", "Lock screen", False), ("logout", "Log out", True), ("suspend", "Suspend", False),
         ("hibernate", "Hibernate", True), ("reboot", "Reboot", True), ("shutdown", "Shut down", True)]


def _do_power(nav, action: str) -> None:
    def cb(res, err):
        if err or not res.ok:
            nav.toast(f"{action} failed: {err or res.err}", ok=False)
        else:
            nav.done()
    nav.bg(lambda: system.power(action), cb)


NO_CONFIRM = ("lock", "suspend")


def _power_go(nav, action: str) -> None:
    """Run harmless actions at once; destructive ones go through a confirm page."""
    if action in NO_CONFIRM:
        _do_power(nav, action)
        return
    label = dict((a, l) for a, l, _ in POWER)[action]
    nav.push(confirm(nav, label, f"{label}?", label, lambda: _do_power(nav, action)))


def power_page(nav) -> Page:
    return Page(title="Power", build=lambda _q: [
        Item(l, activate=(lambda a=a: _power_go(nav, a)), danger=a in ("reboot", "shutdown"))
        for a, l, _c in POWER])


def network_page(nav) -> Page:
    def load():
        st = system.network_status()
        items = [heading("Online" if st["online"] else "Offline — no internet connection")]
        if not st["manager"]:
            items.append(Item("NetworkManager (nmcli) not installed", heading=True))
            return items
        items.append(Item("Wi-Fi", "on" if st["wifi"] else "off",
                          lambda: nav.bg(lambda: system.wifi_power(not st["wifi"]),
                                         lambda r, e: (nav.toast("Wi-Fi " + ("off" if st["wifi"] else "on")), nav.reload()))))
        items.append(_nav_item(nav, "Wi-Fi networks", wifi_page))
        for c in st["connections"]:
            items.append(Item(c["name"], f'{c["type"].replace("802-11-", "")} · {c["device"]}'))
        ed = system.network_editor()
        if ed:
            items.append(Item("Open network editor", "", lambda: _launch_argv(
                _in_terminal(ed) if ed[0] == "nmtui" else ed)))
        return items
    return Page(title="Network", load=load)


def wifi_page(nav) -> Page:
    def password_page(ssid):
        def submit(pw):
            nav.toast(f"Connecting to {ssid}…")
            def cb(r, e):
                if e or not r.ok:
                    nav.toast(f"Could not connect: {e or r.err or r.out.strip()}", ok=False)
                else:
                    nav.toast(f"Connected to {ssid}"); nav.pop()
            nav.bg(lambda: system.wifi_connect(ssid, pw), cb)
        return Page(title=ssid, entry=True, password=True, placeholder="Wi-Fi password",
                    submit=submit, build=lambda _q: [heading("Type the password and press Enter")])

    def connect(n):
        def cb(r, e):
            if not e and r.ok:
                nav.toast(f"Connected to {n['ssid']}"); nav.reload(); return
            if n["security"] not in ("", "--"):
                nav.push(password_page(n["ssid"]))
            else:
                nav.toast(f"Could not connect: {e or r.err}", ok=False)
        nav.toast(f"Connecting to {n['ssid']}…")
        nav.bg(lambda: system.wifi_connect(n["ssid"]), cb)

    def load():
        nets = system.wifi_list(rescan=True)
        if not nets:
            return [heading("No networks found (Wi-Fi off, or nmcli missing)")]
        return [Item(("● " if n["active"] else "") + n["ssid"],
                     f'{n["signal"]}%  {n["security"] or "open"}', (lambda n=n: connect(n))) for n in nets]
    return Page(title="Wi-Fi", load=load, entry=True, filter_local=True, placeholder="Filter…")


def audio_page(nav) -> Page:
    def adj(delta):
        def f():
            cur = system.audio_status()["volume"]
            nav.bg(lambda: system.set_volume(cur + delta), lambda r, e: nav.reload())
        return f

    def load():
        st = system.audio_status()
        if st["backend"] is None:
            return [heading("No audio server found (install pipewire + wireplumber)")]
        items = [Item("Volume", _bar(st["volume"]) + ("  muted" if st["muted"] else ""),
                      left=adj(-5), right=adj(5)),
                 Item("Mute", "on" if st["muted"] else "off",
                      lambda: nav.bg(system.toggle_mute, lambda r, e: nav.reload()))]
        sinks = system.audio_sinks()
        if sinks:
            items.append(heading("Output"))
            items += [Item(("● " if s["default"] else "") + s["description"],
                           activate=(lambda s=s: nav.bg(lambda: system.set_default_sink(s["name"]),
                                                        lambda r, e: nav.reload()))) for s in sinks]
        return items
    return Page(title="Audio", load=load)


def display_page(nav) -> Page:
    def bright(delta):
        def f():
            b = system.brightness()
            if b:
                nav.bg(lambda: system.set_brightness(b["percent"] + delta), lambda r, e: nav.reload())
        return f

    def load():
        items = []
        for d in system.displays():
            rr = f' @{d["refresh"]}Hz' if d.get("refresh") else ""
            items.append(Item(d["name"], f'{d["width"]}×{d["height"]}{rr} ×{d["scale"]}'))
        if not items:
            items.append(heading("No displays detected (needs hyprctl, swaymsg or xrandr)"))
        b = system.brightness()
        if b:
            items.append(Item("Brightness", _bar(b["percent"]), left=bright(-10), right=bright(10)))
        tool = system.display_tool()
        if tool:
            items.append(Item("Open display settings", tool[0], lambda: _launch_argv(tool)))
        return items
    return Page(title="Display", load=load)


def bluetooth_page(nav) -> Page:
    def toggle_dev(d):
        act = "disconnect" if d["connected"] else "connect"
        nav.toast(f"{act.capitalize()}ing {d['name']}…")
        def cb(r, e):
            nav.toast(f"{d['name']}: {act} " + ("ok" if not e and r.ok else f"failed — {e or r.err or r.out.strip()}"),
                      ok=not e and r.ok)
            nav.reload()
        nav.bg(lambda: system.bluetooth_device(act, d["mac"]), cb)

    def load():
        st = system.bluetooth_status()
        if not st["available"]:
            return [heading("Bluetooth unavailable (install bluez + bluez-utils, start bluetooth.service)")]
        items = [Item("Bluetooth", "on" if st["powered"] else "off",
                      lambda: nav.bg(lambda: system.bluetooth_power(not st["powered"]),
                                     lambda r, e: nav.reload()))]
        if st["powered"]:
            items.append(Item("Scan for devices (6 s)", "", lambda: (
                nav.toast("Scanning…"),
                nav.bg(system.bluetooth_scan, lambda r, e: (nav.toast("Scan finished"), nav.reload())))))
            items.append(heading("Devices"))
            items += [Item(d["name"], "connected" if d["connected"] else ("paired" if d["paired"] else ""),
                           (lambda d=d: toggle_dev(d))) for d in st["devices"]]
        return items
    return Page(title="Bluetooth", load=load)


# ----------------------------------------------------------------- packages

def run_task(nav, title: str, argv: list[str]) -> None:
    """Show a live log of a package command. Back is blocked until it ends."""
    buf = Gtk.TextBuffer()
    tv = Gtk.TextView(buffer=buf, editable=False, cursor_visible=False, monospace=True)
    tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); tv.set_hexpand(True)
    sc = Gtk.ScrolledWindow(); sc.set_child(tv); sc.set_hexpand(True); sc.set_vexpand(True)
    page = Page(title=title, custom=sc, blocks_back=True)
    nav.push(page)

    def append(text):
        buf.insert(buf.get_end_iter(), text + "\n")
        tv.scroll_to_mark(buf.create_mark(None, buf.get_end_iter(), False), 0, False, 0, 0)

    if packages.needs_terminal(argv):
        try:
            _launch_argv(_in_terminal(["sh", "-c", '"$@"; echo; printf "Finished. Press Enter to close. "; read _', "omamako"] + argv))
            append("AUR operations run in a terminal so the PKGBUILD can be reviewed.\nOpened a terminal window.")
        except Exception as e:
            append(f"Cannot start: {e}")
        page.blocks_back = False
        nav.win._hints(page)
        return

    append("$ " + " ".join(shlex.quote(a) for a in argv))

    # stream line-by-line to the UI thread
    import threading
    from gi.repository import GLib

    def thread():
        code = 1
        for kind, val in packages.run_stream(argv):
            if kind == "line":
                GLib.idle_add(lambda v=val: (append(v), False)[1])
            else:
                code = int(val)

        def finish():
            page.blocks_back = False
            append(f"\n— finished with exit code {code} —")
            nav.toast("Done" if code == 0 else f"Failed (exit {code})", ok=code == 0)
            nav.win._hints(page)
            nav.win.nav.refresh_apps()
            return False
        GLib.idle_add(finish)
    threading.Thread(target=thread, daemon=True).start()


def packages_page(nav) -> Page:
    def load():
        st = packages.status()
        items = []
        if not st["pacman"]:
            return [heading("pacman not found: this is not an Arch system")]
        if not system.online():
            items.append(heading("Offline — searching AUR, updating and installing need internet"))
        if st["locked"]:
            items.append(heading("pacman database is locked (another pacman running?)"))
        items += [_nav_item(nav, "Search & install", pkg_search_page),
                  _nav_item(nav, "Updates", updates_page),
                  Item("Update system", "pacman -Syu", lambda: nav.push(update_confirm(nav))),
                  _nav_item(nav, "Installed (explicit)", installed_page)]
        if st["aur_helper"]:
            items.append(Item("Update AUR packages", st["aur_helper"] + " (terminal)",
                              lambda: _guarded(nav, lambda: run_task(nav, "AUR update", packages.update(include_aur=True)))))
        else:
            items.append(heading("No AUR helper (install paru or yay for AUR support)"))
        if not st["pkexec"]:
            items.append(heading("polkit (pkexec) missing: cannot install/remove/update"))
        return items
    return Page(title="Packages", load=load)


def _guarded(nav, fn) -> None:
    """Run fn, turning backend refusals (offline, locked db, no pkexec) into a toast."""
    try:
        fn()
    except (ConnectionError, RuntimeError, ValueError) as e:
        nav.toast(str(e), ok=False)


def update_confirm(nav) -> Page:
    def go():
        try:
            argv = packages.update()
        except (ConnectionError, RuntimeError) as e:
            nav.toast(str(e), ok=False); nav.pop(); return
        nav.pop()
        run_task(nav, "Update system", argv)
    return confirm(nav, "Update system", "Run a full system upgrade?", "Run pacman -Syu (asks polkit)", go, danger=False)


def pkg_detail(nav, name: str, repo: str, installed: bool, version: str = "", desc: str = "") -> Page:
    def go_install():
        try:
            argv = packages.install([name], "aur" if repo == "aur" else "repo")
        except (ConnectionError, RuntimeError, ValueError) as e:
            nav.toast(str(e), ok=False); nav.pop(); return
        nav.pop(); run_task(nav, f"Install {name}", argv)

    def go_remove():
        try:
            argv = packages.remove([name])
        except (RuntimeError, ValueError) as e:
            nav.toast(str(e), ok=False); nav.pop(); return
        nav.pop(); run_task(nav, f"Remove {name}", argv)

    def build(_q):
        items = [heading(f"{repo}/{name} {version}"), Item(desc or "", heading=True)]
        if installed:
            items.append(Item("Remove (pacman -Rns)", activate=lambda: nav.push(
                confirm(nav, f"Remove {name}", "", f"Remove {name} and unneeded dependencies", go_remove)), danger=True))
        if repo == "aur" or not installed:
            items.append(Item("Install" if not installed else "Reinstall",
                              "AUR · opens terminal" if repo == "aur" else "pacman -S",
                              lambda: nav.push(confirm(nav, f"Install {name}", "", f"Install {name}", go_install, danger=False))))
        return items
    return Page(title=name, build=build)


def pkg_search_page(nav) -> Page:
    page = Page(title="Search", entry=True, placeholder="Search packages, press Enter…")
    state = {"items": [heading("Type a name and press Enter. Searches repos and the AUR.")]}

    def submit(q):
        if not q.strip():
            return
        state["items"] = [heading("Searching…")]; nav.win.render()
        def cb(res, err):
            if err:
                state["items"] = [heading(f"Search failed: {err}")]
            else:
                items = [Item(("✓ " if r["installed"] else "") + f'{r["name"]}', f'{r["repo"]} {r["version"]}',
                              (lambda r=r: nav.push(pkg_detail(nav, r["name"], r["repo"], r["installed"], r["version"], r["description"]))))
                         for r in res["results"][:200]]
                notes = [heading(e) for e in res["errors"]]
                state["items"] = notes + (items or [heading("No packages found")])
            if nav.page is page:
                page.sel = 0 if not res or not res["errors"] else len(res["errors"])
                nav.win.render()
        nav.bg(lambda: packages.search(q), cb)

    page.submit = submit
    page.build = lambda _q: state["items"]
    return page


def updates_page(nav) -> Page:
    def load():
        up = packages.updates()
        items = [heading(e) for e in up["errors"]]
        total = len(up["repo"]) + len(up["aur"])
        if not total and not items:
            return [heading("System is up to date")]
        if up["repo"]:
            items.append(Item(f"Update system ({len(up['repo'])} packages)", "", lambda: nav.push(update_confirm(nav))))
        items += [heading("Repositories")] + [Item(u["name"], f'{u["old"]} → {u["new"]}') for u in up["repo"]] if up["repo"] else []
        if up["aur"]:
            items += [heading("AUR")] + [Item(u["name"], f'{u["old"]} → {u["new"]}') for u in up["aur"]]
        return items
    return Page(title="Updates", load=load)


def installed_page(nav) -> Page:
    def load():
        return [Item(p["name"], p["version"],
                     (lambda p=p: nav.push(pkg_detail(nav, p["name"], "local", True, p["version"]))))
                for p in packages.explicit()] or [heading("Nothing installed?")]
    return Page(title="Installed", load=load, entry=True, filter_local=True, placeholder="Filter…")


# ----------------------------------------------------------------- settings

def settings_page(nav) -> Page:
    return Page(title="Settings", build=lambda _q: [
        _nav_item(nav, "Theme", theme_page), _nav_item(nav, "Keybindings", keys_page),
        _nav_item(nav, "Startup apps", startup_page), _nav_item(nav, "Launcher", launcher_page),
        Item("Edit config file", str(config.config_path()), lambda: _edit_config(nav)),
        _nav_item(nav, "About", about_page)])


def _edit_config(nav) -> None:
    config.ensure_default()
    path = str(config.config_path())
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    try:
        if ed:
            _launch_argv(_in_terminal(shlex.split(ed) + [path]))
        elif which("xdg-open"):
            _launch_argv(["xdg-open", path])
        else:
            raise RuntimeError("set $EDITOR or install xdg-utils")
        nav.done()
    except Exception as e:
        nav.toast(str(e), ok=False)


def theme_page(nav) -> Page:
    def build(q):
        cur = config.load()["general"]["theme"]
        def pick(n):
            def f():
                config.set_value("general.theme", n)
                nav.apply_theme(); nav.toast(f"Theme: {n}"); nav.win.render()
            return f
        names = [n for n in themes.available() if q.lower() in n.lower()]
        return [Item(("● " if n == cur else "") + n, themes.load(n).get("mode", ""), pick(n)) for n in names]
    return Page(title="Theme", build=build, entry=True, placeholder="Filter…")


def keys_page(nav) -> Page:
    def set_combo(text):
        text = text.strip().replace(",", "+").replace(" ", "")
        if "+" not in text:
            nav.toast("Use MOD+key, e.g. SUPER+space", ok=False); return
        mod, _, key = text.rpartition("+")
        config.set_value("hotkey.mod", mod.upper()); config.set_value("hotkey.key", key)
        nav.toast(f"Hotkey set to {mod.upper()}+{key}. Apply it to your compositor config.")
        nav.pop()

    def edit():
        nav.push(Page(title="Change hotkey", entry=True, placeholder="e.g. SUPER+space or ALT+F2",
                      submit=set_combo, build=lambda _q: [heading("Type MOD+key and press Enter")]))

    def apply_():
        try:
            r = hotkey.install()
            nav.toast(f"Wrote {r['snippet_file']}; reload your {r['compositor']} config")
        except (ValueError, OSError) as e:
            nav.toast(str(e), ok=False)

    def remove():
        try:
            hotkey.remove(); nav.toast("Hotkey binding removed")
        except (ValueError, OSError) as e:
            nav.toast(str(e), ok=False)

    def build(_q):
        s = hotkey.show()
        return [Item("Open launcher", s["combo"], edit), heading(f"Compositor: {s['compositor']}"),
                Item("Change hotkey…", "", edit),
                Item("Install binding into compositor config", "", apply_),
                Item("Remove binding", "", remove),
                heading("Snippet:")] + [Item(l, heading=True) for l in s["snippet"].splitlines()] + [
                heading("Navigation: ↑↓ or Ctrl+N/P · ⏎ open · ⎋/⌫ back · ←→ adjust · Ctrl+F favorite")]
    return Page(title="Keybindings", build=build)


def startup_page(nav) -> Page:
    def build(q):
        on = set(config.load()["startup"]["apps"])
        def toggle(e):
            def f():
                cur = list(config.load()["startup"]["apps"])
                cur = [a for a in cur if a != e.id] if e.id in cur else cur + [e.id]
                config.set_value("startup.apps", ",".join(cur))
                nav.win.render()
            return f
        ents = apps.search(q, nav.entries)
        return [Item(("☑ " if e.id in on else "☐ ") + e.name, e.id, toggle(e)) for e in ents]
    return Page(title="Startup apps", build=build, entry=True, placeholder="Filter…")


def launcher_page(nav) -> Page:
    def step(key, d, lo, hi):
        def f():
            v = max(lo, min(hi, config.get(key) + d))
            config.set_value(key, str(v)); nav.apply_theme(); nav.win.render()
        return f

    def toggle(key):
        def f():
            config.set_value(key, str(not config.get(key)).lower()); nav.apply_theme(); nav.win.render()
        return f

    def build(_q):
        c = config.load()["launcher"]
        return [Item("Font size", f'{c["font_size"]}px', left=step("launcher.font_size", -1, 10, 32),
                     right=step("launcher.font_size", 1, 10, 32)),
                Item("Recent apps shown", str(c["max_recents"]), left=step("launcher.max_recents", -1, 0, 20),
                     right=step("launcher.max_recents", 1, 0, 20)),
                Item("Show clock", "on" if c["show_clock"] else "off", toggle("launcher.show_clock")),
                Item("Use layer-shell (Wayland)", "on" if c["layer_shell"] else "off", toggle("launcher.layer_shell")),
                heading("Clock/date formats and the terminal are in the config file (strftime syntax)")]
    return Page(title="Launcher", build=build)


def about_page(nav) -> Page:
    from .. import __version__
    return Page(title="About", build=lambda _q: [
        heading(f"omamako {__version__}"),
        Item("GPL-3.0-or-later. UX after Mako (rama-io, GPL-3.0).", heading=True),
        Item("Themes from Omalauncher (Simon Schubert, MIT) / Omarchy.", heading=True),
        Item(f"Config: {config.config_path()}", heading=True)])
