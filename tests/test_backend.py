"""Backend tests. Run with:  python -m unittest discover -s tests -v

The host need not be Arch: tools such as pacman, pkexec, nmcli and wpctl are
replaced by tiny fake executables placed first on PATH.
"""

import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omamako import apps, cli, config, desktop, hotkey, packages, system, themes  # noqa: E402

FAKES = {
    "pacman": r'''
        case "$1" in
          -Ss) if [ "$3" = "firefox" ]; then
                 printf 'extra/firefox 130.0-1 [installed]\n    Fast, Private & Safe Web Browser\nextra/firefox-dev 131-1\n    Dev edition\n'; exit 0
               else exit 1; fi;;
          -Si) [ "$3" = "firefox" -o "$3" = "git" ] && exit 0 || exit 1;;
          -Qi) printf 'Name            : %s\nVersion         : 1.0\n' "$3"; exit 0;;
          -Q)  printf 'git 2.45-1\nbash 5.2-1\n';;
          -Qe) printf 'git 2.45-1\n';;
          -Qu) printf 'bash 5.2-1 -> 5.3-1\n';;
          -S)  echo "resolving: $*"; echo "installing done"; exit 0;;
          -Rns) echo "removing: $*"; exit 0;;
          -Syu) echo "upgrading: $*"; exit 0;;
        esac''',
    "pkexec": 'exec "$@"',
    "paru": r'''
        case "$1" in
          -Ssa) printf 'aur/yay-bin 12.0-1 (+100 5.0)\n    AUR helper\n';;
          -Qua) printf 'foo-git 1-1 -> 2-1\n';;
          *) echo "paru: $*";;
        esac''',
    "wpctl": r'''
        case "$1" in get-volume) echo "Volume: 0.40 [MUTED]";; *) echo "wpctl $*";; esac''',
    "nmcli": r'''
        case "$*" in
          *"radio wifi"*) ;;
          "-t -f WIFI radio") echo enabled;;
          *"connection show"*) echo 'Home\:Net:802-11-wireless:wlan0';;
          *"wifi list"*) printf ' :Cafe:40:WPA2\n*:Home\\:Net:80:WPA2\n :Cafe:30:WPA2\n';;
          *"wifi connect"*) cat >/dev/null; echo connected;;
        esac''',
    "bluetoothctl": r'''
        case "$1" in
          show) printf 'Controller AA\n\tPowered: yes\n';;
          devices) echo "Device 11:22:33:44:55:66 Headphones";;
          info) printf '\tPaired: yes\n\tConnected: no\n';;
          *) echo "bt $*";;
        esac''',
    "brightnessctl": 'echo "intel_backlight,backlight,500,50%,1000"',
}


def make_fakes(d: Path) -> None:
    for name, body in FAKES.items():
        p = d / name
        p.write_text("#!/bin/sh\n" + textwrap.dedent(body) + "\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "bin").mkdir()
        make_fakes(t / "bin")
        env = {
            "HOME": str(t / "home"), "XDG_CONFIG_HOME": str(t / "cfg"),
            "XDG_STATE_HOME": str(t / "state"), "XDG_DATA_HOME": str(t / "data"),
            "XDG_DATA_DIRS": str(t / "share"), "PATH": f"{t/'bin'}:/usr/bin:/bin",
            "XDG_CURRENT_DESKTOP": "Hyprland", "LANG": "C",
        }
        (t / "home").mkdir()
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        for k in ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK", "I3SOCK", "WAYLAND_DISPLAY", "DISPLAY",
                  "XDG_SESSION_TYPE", "TERMINAL"):
            os.environ.pop(k, None)
        self.t = t
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.online = mock.patch.object(system, "online", return_value=True)
        self.online.start()
        self.addCleanup(self.online.stop)

    def desktop(self, name, body, sub="share/applications"):
        p = self.t / sub / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p

    def ctl(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.startswith(("{", "["))]
        return code, lines


class TestDesktop(Base):
    def test_parse_filter_and_override(self):
        self.desktop("firefox.desktop", "[Desktop Entry]\nType=Application\nName=Firefox\nName[de]=Feuerfuchs\n"
                     "Exec=firefox %u\nCategories=Network;WebBrowser;\nKeywords=web;browser;\n"
                     "Actions=priv;\n[Desktop Action priv]\nName=Private\nExec=firefox --private-window\n")
        self.desktop("hidden.desktop", "[Desktop Entry]\nType=Application\nName=H\nExec=h\nNoDisplay=true\n")
        self.desktop("other-de.desktop", "[Desktop Entry]\nType=Application\nName=KDE only\nExec=k\nOnlyShowIn=KDE;\n")
        self.desktop("badtry.desktop", "[Desktop Entry]\nType=Application\nName=T\nExec=t\nTryExec=/nonexistent/x\n")
        # user override hides the system entry
        self.desktop("git.desktop", "[Desktop Entry]\nType=Application\nName=Git\nExec=git gui\n")
        self.desktop("git.desktop", "[Desktop Entry]\nType=Application\nName=Git\nExec=git gui\nHidden=true\n",
                     sub="data/applications")
        ids = {e.id: e for e in desktop.scan()}
        self.assertEqual(set(ids), {"firefox.desktop"})
        ff = ids["firefox.desktop"]
        self.assertEqual(ff.categories, ["Network", "WebBrowser"])
        self.assertEqual(ff.keywords, ["web", "browser"])
        self.assertEqual(ff.actions["priv"][0], "Private")
        self.assertEqual(apps.category_of(ff), "Internet")

    def test_locale_name(self):
        self.desktop("a.desktop", "[Desktop Entry]\nType=Application\nName=Firefox\nName[de]=Feuerfuchs\nExec=ff\n")
        with mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8"}):
            self.assertEqual(desktop.scan()[0].name, "Feuerfuchs")

    def test_exec_field_codes(self):
        e = desktop.DesktopEntry("a", "/p", "App", 'app --x "a b" %U %i %c 100%% %f', icon="ico")
        self.assertEqual(desktop.expand_exec(e, files=["/f1", "/f2"]),
                         ["app", "--x", "a b", "/f1", "/f2", "--icon", "ico", "App", "100%", "/f1"])


class TestApps(Base):
    def setUp(self):
        super().setUp()
        for n, nm, extra in [("ff", "Firefox", "Keywords=web;\n"), ("fm", "File Manager", ""),
                             ("ft", "Footnote", "Comment=notes\n")]:
            self.desktop(f"{n}.desktop", f"[Desktop Entry]\nType=Application\nName={nm}\nExec=true\n{extra}")

    def test_search_ranking(self):
        names = [e.name for e in apps.search("f")]
        self.assertEqual(set(names), {"Firefox", "File Manager", "Footnote"})
        self.assertEqual([e.name for e in apps.search("web")], ["Firefox"])
        self.assertEqual(apps.search("zzzz"), [])
        self.assertEqual(apps.search("firefox")[0].name, "Firefox")

    def test_favorites_and_recents(self):
        apps.set_favorite("ff.desktop", True)
        self.assertEqual(apps.favorites(), ["ff.desktop"])
        apps.set_favorite("ff.desktop", False)
        self.assertEqual(apps.favorites(), [])
        apps.record_launch("fm.desktop"); apps.record_launch("ft.desktop"); apps.record_launch("fm.desktop")
        self.assertEqual(apps.recent_ids(), ["fm.desktop", "ft.desktop"])
        self.assertEqual(apps.recents()[0]["count"], 2)

    def test_launch_records_and_unknown(self):
        out = self.t / "ran"
        self.desktop("run.desktop", f"[Desktop Entry]\nType=Application\nName=Run\nExec=sh -c 'echo hi > {out}'\n")
        apps.launch("run")
        for _ in range(50):
            if out.exists():
                break
            import time; time.sleep(0.05)
        self.assertEqual(out.read_text().strip(), "hi")
        self.assertIn("run.desktop", apps.recent_ids())
        with self.assertRaises(KeyError):
            apps.launch("nope")


class TestSystem(Base):
    def test_power_commands(self):
        r = system.power("shutdown", dry_run=True)
        self.assertEqual(r.argv, ["systemctl", "poweroff"])
        self.assertEqual(system.power("reboot", True).argv, ["systemctl", "reboot"])
        self.assertEqual(system.power("suspend", True).argv, ["systemctl", "suspend"])
        with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "x"}):
            self.assertEqual(system.power_commands()["logout"][0], "loginctl")  # no hyprctl on PATH: falls back
            (self.t / "bin" / "hyprctl").write_text("#!/bin/sh\n"); (self.t / "bin" / "hyprctl").chmod(0o755)
            self.assertEqual(system.power_commands()["logout"], ["hyprctl", "dispatch", "exit"])
        with self.assertRaises(KeyError):
            system.power("explode")

    def test_network_parsing(self):
        st = system.network_status()
        self.assertTrue(st["wifi"])
        self.assertEqual(st["connections"][0]["name"], "Home:Net")
        nets = system.wifi_list()
        self.assertEqual([n["ssid"] for n in nets], ["Home:Net", "Cafe"])
        self.assertTrue(nets[0]["active"])
        self.assertTrue(system.wifi_connect("Cafe", "secret").ok)

    def test_offline_is_clean(self):
        self.online.stop()
        with mock.patch.object(system.socket, "create_connection", side_effect=OSError):
            self.assertFalse(system.online())
            res = packages.search("firefox")
        self.online.start()
        self.assertTrue(res["results"])  # repo results still work offline
        self.assertIn("offline: AUR search skipped", res["errors"])

    def test_audio_bluetooth_display(self):
        self.assertEqual(system.audio_status(), {"backend": "wpctl", "volume": 40, "muted": True})
        self.assertTrue(system.set_volume(500).ok)
        bt = system.bluetooth_status()
        self.assertTrue(bt["powered"])
        self.assertEqual(bt["devices"][0], {"mac": "11:22:33:44:55:66", "name": "Headphones",
                                            "connected": False, "paired": True})
        with self.assertRaises(ValueError):
            system.bluetooth_device("connect", "--bad")
        self.assertEqual(system.brightness(), {"device": "intel_backlight", "percent": 50})

    def test_missing_tool_never_raises(self):
        os.environ["PATH"] = "/nonexistent"
        self.assertEqual(system.audio_status()["backend"], None)
        self.assertFalse(system.bluetooth_status()["available"])
        self.assertEqual(system.wifi_list(), [])
        self.assertEqual(system.displays(), [])


class TestPackages(Base):
    def test_search_and_parse(self):
        res = packages.search("firefox")["results"]
        self.assertEqual([(r["repo"], r["name"], r["installed"]) for r in res],
                         [("extra", "firefox", True), ("extra", "firefox-dev", False), ("aur", "yay-bin", False)])
        self.assertEqual(res[0]["description"], "Fast, Private & Safe Web Browser")

    def test_aur_search_with_helper(self):
        res = packages.search("nomatch-repo", aur=True)
        self.assertEqual([r["name"] for r in res["results"]], ["yay-bin"])  # repo: none, aur: one

    def test_lists_and_updates(self):
        self.assertEqual(packages.installed()[0], {"name": "git", "version": "2.45-1"})
        self.assertEqual(packages.explicit(), [{"name": "git", "version": "2.45-1"}])
        up = packages.updates()
        self.assertEqual(up["repo"], [{"name": "bash", "old": "5.2-1", "new": "5.3-1", "source": "repo"}])
        self.assertEqual(up["aur"][0]["name"], "foo-git")

    def test_name_validation(self):
        for bad in ["--noconfirm", "a b", "x;rm", "", "../x", "-S"]:
            with self.assertRaises(ValueError, msg=bad):
                packages.validate([bad])
        packages.validate(["gtk4", "python-gobject", "libc++", "a.b_c@1"])

    def test_install_remove_update_streams_through_pkexec(self):
        argv = packages.install(["git"])
        self.assertEqual(argv[:3], ["pkexec", "pacman", "-S"])
        self.assertNotIn("-y", argv)  # no partial-upgrade refresh
        lines = list(packages.run_stream(argv))
        self.assertEqual(lines[-1], ("done", 0))
        self.assertIn(("line", "installing done"), lines)
        self.assertEqual(list(packages.run_stream(packages.remove(["git"])))[-1], ("done", 0))
        self.assertEqual(packages.update()[:3], ["pkexec", "pacman", "-Syu"])

    def test_aur_goes_via_helper_and_terminal(self):
        argv = packages.install(["yay-bin"])  # not in repos per fake pacman
        self.assertEqual(argv[0], "paru")
        self.assertIn("pkexec", argv)
        self.assertTrue(packages.needs_terminal(argv))
        self.assertFalse(packages.needs_terminal(packages.install(["git"])))

    def test_offline_and_lock_refuse(self):
        self.online.stop()
        with mock.patch.object(system.socket, "create_connection", side_effect=OSError):
            with self.assertRaises(ConnectionError):
                packages.install(["git"])
        self.online.start()
        with mock.patch.object(packages, "DB_LOCK", self.t / "lock"):
            (self.t / "lock").write_text("")
            with self.assertRaises(RuntimeError):
                packages.install(["git"])

    def test_no_elevation_available(self):
        os.environ["PATH"] = "/nonexistent"
        with self.assertRaises(RuntimeError):
            packages.update_cmd()


class TestConfigThemesHotkey(Base):
    def test_config_roundtrip(self):
        self.assertTrue(config.ensure_default())
        self.assertFalse(config.ensure_default())
        config.set_value("general.theme", "nord")
        config.set_value("launcher.font_size", "20")
        config.set_value("launcher.show_clock", "false")
        config.set_value("startup.apps", "a.desktop, b.desktop")
        c = config.load()
        self.assertEqual(c["general"]["theme"], "nord")
        self.assertEqual(c["launcher"]["font_size"], 20)
        self.assertIs(c["launcher"]["show_clock"], False)
        self.assertEqual(c["startup"]["apps"], ["a.desktop", "b.desktop"])
        with self.assertRaises(KeyError):
            config.set_value("nope.x", "1")
        with self.assertRaises(ValueError):
            config.set_value("launcher.font_size", "big")

    def test_config_with_quotes_and_corruption(self):
        config.set_value("general.terminal", 'we"ird\\path')
        self.assertEqual(config.load()["general"]["terminal"], 'we"ird\\path')
        config.config_path().write_text("[[[ not toml")
        self.assertEqual(config.load()["general"]["theme"], "tokyo-night")

    def test_all_bundled_themes_valid(self):
        names = themes.available()
        self.assertGreaterEqual(len(names), 20)
        for n in names:
            t = themes._load(names[n])
            self.assertIsNotNone(t, n)
            self.assertIn("{", themes.css(t))
        self.assertEqual(themes.load("does-not-exist")["background"], themes.load("tokyo-night")["background"])

    def test_hotkey_install_remove_idempotent(self):
        main = self.t / "home/.config/hypr/hyprland.conf"
        main.parent.mkdir(parents=True)
        main.write_text("monitor=,preferred,auto,1\n")
        self.assertEqual(hotkey.snippet("hyprland"), "bind = SUPER, space, exec, omamako toggle\n")
        config.set_value("hotkey.mod", "SUPER+SHIFT")
        config.set_value("hotkey.key", "d")
        self.assertEqual(hotkey.snippet("sway"), "bindsym Mod4+Shift+d exec omamako toggle\n")
        hotkey.install("hyprland"); hotkey.install("hyprland")
        self.assertEqual(main.read_text().count(hotkey.MARK_BEGIN), 1)
        self.assertTrue(main.read_text().startswith("monitor=,preferred,auto,1"))
        self.assertTrue(hotkey.remove("hyprland")["removed"])
        self.assertEqual(main.read_text(), "monitor=,preferred,auto,1\n")
        with self.assertRaises(ValueError):
            hotkey.install("x11")


class TestCli(Base):
    def test_json_commands(self):
        self.desktop("a.desktop", "[Desktop Entry]\nType=Application\nName=Alpha\nExec=true\n")
        code, [apps_list] = self.ctl("apps", "list")
        self.assertEqual((code, apps_list[0]["id"]), (0, "a.desktop"))
        code, [res] = self.ctl("apps", "search", "alp")
        self.assertEqual(res[0]["name"], "Alpha")
        code, [fav] = self.ctl("apps", "fav", "a.desktop", "on")
        self.assertEqual(fav, ["a.desktop"])
        code, [f] = self.ctl("apps", "favorites")
        self.assertEqual(f[0]["favorite"], True)
        code, [p] = self.ctl("power", "shutdown", "--dry-run")
        self.assertEqual(p["out"], "systemctl poweroff")
        code, [e] = self.ctl("power", "nope")
        self.assertEqual(code, 1); self.assertIn("error", e)
        code, [n] = self.ctl("network", "status"); self.assertTrue(n["online"])
        code, [t] = self.ctl("theme", "set", "nord"); self.assertEqual(t["theme"], "nord")
        code, [e] = self.ctl("theme", "set", "bogus"); self.assertEqual(code, 1)
        code, [d] = self.ctl("doctor"); self.assertTrue(d["tools"]["pacman"])

    def test_pkg_install_ndjson(self):
        code, lines = self.ctl("pkg", "install", "git")
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], {"type": "done", "code": 0})
        code, [c] = self.ctl("pkg", "install", "git", "--dry-run")
        self.assertEqual(c["argv"][:2], ["pkexec", "pacman"])
        code, [e] = self.ctl("pkg", "install", "bad;name")
        self.assertEqual(code, 1)
        self.assertIn("invalid package name", e["error"])


if __name__ == "__main__":
    unittest.main()
