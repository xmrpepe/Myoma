"""Drives the real GTK window (needs a display: xvfb-run python3 -m unittest).
Set OMAMAKO_SHOTS=/some/dir to save a screenshot of each menu."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib
    HAVE_GTK = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
except (ImportError, ValueError):
    HAVE_GTK = False

from test_backend import make_fakes  # noqa: E402


@unittest.skipUnless(HAVE_GTK, "no GTK4 / display")
class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = cls.t = Path(cls.tmp.name)
        (t / "bin").mkdir()
        make_fakes(t / "bin")
        for n in ("systemctl", "loginctl"):
            (t / "bin" / n).write_text(f'#!/bin/sh\necho "$0 $@" >> {t}/power.log\n')
            (t / "bin" / n).chmod(0o755)
        (t / "home").mkdir()
        cls.env = mock.patch.dict(os.environ, {
            "HOME": str(t / "home"), "XDG_CONFIG_HOME": str(t / "cfg"), "XDG_STATE_HOME": str(t / "state"),
            "XDG_DATA_HOME": str(t / "data"), "XDG_DATA_DIRS": str(t / "share"),
            "PATH": f"{t/'bin'}:" + os.environ["PATH"], "XDG_CURRENT_DESKTOP": "Hyprland",
            "OMAMAKO_NO_LAYER": "1", "LANG": "C"})
        cls.env.start()
        for k in ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK", "I3SOCK", "WAYLAND_DISPLAY", "TERMINAL"):
            os.environ.pop(k, None)
        apps = t / "share/applications"
        apps.mkdir(parents=True)
        for n, name, cat in [("firefox", "Firefox", "Network;"), ("foot", "Foot Terminal", "System;"),
                             ("gimp", "GIMP", "Graphics;")]:
            (apps / f"{n}.desktop").write_text(
                f"[Desktop Entry]\nType=Application\nName={name}\nExec=sh -c 'echo {n} >> {t}/launched'\n"
                f"Categories={cat}\nComment=The {name} app\n")
        from omamako import system
        cls.online = mock.patch.object(system, "online", return_value=True)
        cls.online.start()
        from omamako.ui import app as appmod
        cls.appmod = appmod
        cls.app = appmod.OmamakoApp()
        cls.app.register(None)
        cls.app.daemon = True  # keep the process alive between checks
        cls.win = cls.app._window()
        cls.win.open_fresh()
        cls.shots = os.environ.get("OMAMAKO_SHOTS")
        if cls.shots:
            Path(cls.shots).mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.online.stop(); cls.env.stop(); cls.tmp.cleanup()

    # -- helpers
    def pump(self, secs=0.3):
        ctx = GLib.MainContext.default()
        end = time.time() + secs
        while time.time() < end:
            while ctx.pending():
                ctx.iteration(False)
            time.sleep(0.01)

    def wait(self, cond, secs=5):
        end = time.time() + secs
        while time.time() < end:
            self.pump(0.05)
            if cond():
                return True
        return False

    def key(self, keyval, state=0):
        handled = self.win._on_key(None, keyval, 0, state)
        # Like GTK: a Return the capture handler lets through reaches the focused entry.
        if not handled and keyval == Gdk.KEY_Return and self.win.nav.page.entry:
            self.win._on_entry_activate(self.win.entry)
        self.pump(0.1)

    def labels(self):
        return [it.label for _r, it in self.win._rows]

    def go(self, label):
        """Select the row with this label and press Enter."""
        for i, (_r, it) in enumerate(self.win._rows):
            if it.label.lstrip("●✓★☐☑ ") == label or it.label == label:
                self.win._select(i)
                self.key(Gdk.KEY_Return)
                self.pump(0.2)
                return
        self.fail(f"no row {label!r} in {self.labels()}")

    def home(self):
        self.win.nav.home(); self.win.entry.set_text(""); self.pump(0.2)

    def loaded(self):
        return self.wait(lambda: self.win.nav.page.loaded or self.win.nav.page.load is None)

    def shot(self, name):
        if not self.shots:
            return
        self.pump(0.4)
        subprocess.run(["import", "-window", "root", f"{self.shots}/{name}.png"], check=False)

    def type(self, text):
        self.win.entry.set_text(text); self.pump(0.2)

    # -- tests (numbered to run in a sensible order)
    def test_01_home_and_search(self):
        self.home()
        self.assertEqual(self.win.nav.page.title, "omamako")
        for m in ("All apps", "Categories", "System", "Packages", "Settings"):
            self.assertIn(m, self.labels())
        self.shot("01-home")
        self.type("fire")
        self.assertEqual(self.labels()[0], "Firefox")
        self.shot("02-search")
        self.type("shut")
        self.assertIn("Shut down", self.labels())  # commands are searchable
        self.type("zzzzqq")
        self.assertTrue(self.win._rows[0][1].heading)

    def test_02_keyboard_navigation_and_launch(self):
        self.home(); self.type("g")
        first = self.win._selected().label
        self.key(Gdk.KEY_Down)
        self.assertNotEqual(self.win._selected().label, first)
        self.key(Gdk.KEY_Up)
        self.assertEqual(self.win._selected().label, first)
        self.key(Gdk.KEY_n, Gdk.ModifierType.CONTROL_MASK)
        self.key(Gdk.KEY_p, Gdk.ModifierType.CONTROL_MASK)
        self.type("firefox")
        self.win._on_entry_activate(self.win.entry)  # Enter in the search box
        self.assertTrue(self.wait(lambda: (self.t / "launched").exists()))
        self.assertIn("firefox", (self.t / "launched").read_text())
        self.assertFalse(self.win.is_visible())  # dismissed after launch (daemon mode hides)
        self.win.open_fresh()
        self.assertIn("Recent", self.labels())  # shows up as recent now

    def test_03_favorites(self):
        self.home(); self.type("gimp")
        self.key(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        self.assertIn("gimp.desktop", __import__("omamako.apps", fromlist=["x"]).favorites())
        self.type("")
        self.assertIn("Favorites", self.labels())
        self.assertIn("★ GIMP", self.labels())
        self.shot("03-favorites")

    def test_04_escape_and_back(self):
        self.home(); self.go("System")
        self.assertEqual(self.win.nav.page.title, "System")
        self.key(Gdk.KEY_Escape)
        self.assertEqual(self.win.nav.page.title, "omamako")
        self.go("System"); self.key(Gdk.KEY_BackSpace)
        self.assertEqual(self.win.nav.page.title, "omamako")
        self.go("System"); self.key(Gdk.KEY_Left)
        self.assertEqual(self.win.nav.page.title, "omamako")
        self.key(Gdk.KEY_Escape)
        self.assertFalse(self.win.is_visible())
        self.win.open_fresh()

    def test_05_categories_and_all_apps(self):
        self.home(); self.go("Categories")
        self.assertEqual(set(self.labels()), {"Internet", "System", "Graphics"})
        self.shot("04-categories")
        self.go("Internet"); self.assertEqual(self.labels(), ["Firefox"])
        self.home(); self.go("All apps"); self.assertEqual(len(self.labels()), 3)

    def test_06_power_requires_confirmation(self):
        log = self.t / "power.log"
        log.unlink(missing_ok=True)
        self.home(); self.go("System"); self.go("Power")
        self.shot("05-power")
        self.go("Shut down")
        self.assertEqual(self.win.nav.page.title, "Shut down")
        self.assertEqual(self.labels()[0], "Cancel")
        self.assertEqual(self.win._selected().label, "Cancel")  # safe default
        self.shot("06-confirm")
        self.assertFalse(log.exists())
        self.key(Gdk.KEY_Return)                                # Enter on Cancel: nothing happens
        self.assertFalse(log.exists())
        self.assertEqual(self.win.nav.page.title, "Power")
        self.go("Shut down"); self.go("Shut down")              # confirm
        self.assertTrue(self.wait(log.exists))
        self.assertIn("poweroff", log.read_text())
        self.win.open_fresh(); log.unlink()
        self.go("System"); self.go("Power"); self.go("Suspend")  # harmless: immediate
        self.assertTrue(self.wait(log.exists))
        self.assertIn("suspend", log.read_text())
        self.win.open_fresh()

    def test_07_system_submenus_load(self):
        for sub, expect in [("Network", "Wi-Fi"), ("Audio", "Volume"), ("Bluetooth", "Bluetooth"),
                            ("Display", "Brightness")]:
            self.home(); self.go("System"); self.go(sub)
            self.assertTrue(self.loaded(), sub)
            self.pump(0.3)
            self.assertIn(expect, self.labels(), (sub, self.labels()))
            self.assertFalse(any(l.startswith("Error") for l in self.labels()), self.labels())
            self.shot(f"07-{sub.lower()}")

    def test_08_audio_adjust_with_arrows(self):
        self.home(); self.go("System"); self.go("Audio"); self.loaded(); self.pump(0.3)
        vol = next(i for i, (_r, it) in enumerate(self.win._rows) if it.label == "Volume")
        self.win._select(vol)
        self.assertIn("40%", self.win._selected().hint)
        self.key(Gdk.KEY_Right)  # fake wpctl accepts the call; value stays (fake has no state)
        self.key(Gdk.KEY_Left)
        self.pump(0.5)

    def test_09_wifi_list_and_password_page(self):
        self.home(); self.go("System"); self.go("Network"); self.loaded(); self.pump(0.2)
        self.go("Wi-Fi networks"); self.loaded(); self.pump(0.3)
        self.assertTrue(any("Home:Net" in l for l in self.labels()), self.labels())
        self.shot("08-wifi")

    def test_10_packages_search_install(self):
        self.home(); self.go("Packages"); self.loaded(); self.pump(0.3)
        for m in ("Search & install", "Updates", "Update system", "Installed (explicit)"):
            self.assertIn(m, self.labels())
        self.shot("09-packages")
        self.go("Search & install")
        self.type("firefox")
        self.win._on_entry_activate(self.win.entry)
        self.assertTrue(self.wait(lambda: "firefox-dev" in self.labels()))
        self.shot("10-pkg-search")
        self.go("firefox-dev")
        self.assertEqual(self.win.nav.page.title, "firefox-dev")
        self.go("Install")
        self.assertEqual(self.labels()[0], "Cancel")                   # confirmation first
        self.go("Install firefox-dev")
        self.assertEqual(self.win.nav.page.title, "Install firefox-dev")
        self.assertTrue(self.wait(lambda: not self.win.nav.page.blocks_back))
        text = self._log()
        self.assertIn("pkexec pacman -S --needed --noconfirm -- firefox-dev", text)
        self.assertIn("installing done", text)
        self.assertIn("exit code 0", text)
        self.shot("11-pkg-install")
        self.key(Gdk.KEY_Escape)
        self.assertNotEqual(self.win.nav.page.title, "Install firefox-dev")

    def _log(self):
        buf = self.win.nav.page.custom.get_child().get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def test_11_back_blocked_while_task_runs(self):
        from omamako.ui import pages
        self.home()
        pages.run_task(self.win.nav, "slow", ["sh", "-c", "sleep 1; echo end"])
        self.pump(0.2)
        self.assertTrue(self.win.nav.page.blocks_back)
        self.key(Gdk.KEY_Escape)
        self.assertEqual(self.win.nav.page.title, "slow")   # can't leave mid-operation
        self.assertTrue(self.wait(lambda: not self.win.nav.page.blocks_back))
        self.assertIn("end", self._log())

    def test_12_updates_and_installed_and_remove(self):
        self.home(); self.go("Packages"); self.loaded(); self.pump(0.2)
        self.go("Updates"); self.loaded(); self.pump(0.3)
        self.assertTrue(any("bash" == l for l in self.labels()), self.labels())
        self.shot("12-updates")
        self.home(); self.go("Packages"); self.loaded(); self.pump(0.2)
        self.go("Installed (explicit)"); self.loaded(); self.pump(0.3)
        self.go("git")
        self.go("Remove (pacman -Rns)")
        self.assertEqual(self.labels()[0], "Cancel")
        self.go("Remove git and unneeded dependencies")
        self.assertTrue(self.wait(lambda: not self.win.nav.page.blocks_back))
        self.assertIn("removing:", self._log())

    def test_13_offline_state(self):
        from omamako import system
        with mock.patch.object(system, "online", return_value=False):
            self.home(); self.go("Packages"); self.loaded(); self.pump(0.3)
            self.assertTrue(any(l.startswith("Offline") for l in self.labels()), self.labels())
            self.shot("13-offline")
            self.go("Update system"); self.go("Run pacman -Syu (asks polkit)")
            self.assertIn("offline", self.win.toast_label.get_label())   # refused, UI still alive

    def test_14_settings(self):
        from omamako import config
        self.home(); self.go("Settings")
        self.assertEqual(self.labels(), ["Theme", "Keybindings", "Startup apps", "Launcher", "Edit config file", "About"])
        self.shot("14-settings")
        self.go("Theme"); self.assertGreaterEqual(len(self.labels()), 20)
        self.go("nord")
        self.assertEqual(config.load()["general"]["theme"], "nord")
        self.shot("15-theme-nord")
        self.type("gruv"); self.assertEqual([l.lstrip("● ") for l in self.labels()], ["gruvbox"])
        self.go("gruvbox"); self.assertEqual(config.load()["general"]["theme"], "gruvbox")
        self.home(); self.go("Settings"); self.go("Startup apps"); self.go("Firefox")
        self.assertEqual(config.load()["startup"]["apps"], ["firefox.desktop"])
        self.go("Firefox"); self.assertEqual(config.load()["startup"]["apps"], [])
        self.home(); self.go("Settings"); self.go("Launcher")
        row = next(i for i, (_r, it) in enumerate(self.win._rows) if it.label == "Font size")
        self.win._select(row); self.key(Gdk.KEY_Right)
        self.assertEqual(config.load()["launcher"]["font_size"], 17)
        self.key(Gdk.KEY_Left)
        self.assertEqual(config.load()["launcher"]["font_size"], 16)

    def test_15_keybindings(self):
        from omamako import config
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "test"
        self.addCleanup(os.environ.pop, "HYPRLAND_INSTANCE_SIGNATURE", None)
        self.home(); self.go("Settings"); self.go("Keybindings")
        self.assertTrue(any("bind = SUPER, space" in l for l in self.labels()), self.labels())
        self.shot("16-keybindings")
        self.go("Change hotkey…")
        self.type("ALT+F2"); self.win._on_entry_activate(self.win.entry); self.pump(0.2)
        self.assertEqual((config.load()["hotkey"]["mod"], config.load()["hotkey"]["key"]), ("ALT", "F2"))
        self.assertEqual(self.win.nav.page.title, "Keybindings")

    def test_16_wifi_password_not_visible(self):
        from omamako.ui import pages
        self.home()
        self.win.nav.push(pages.wifi_page(self.win.nav).__class__(title="x"))
        p = pages.Page(title="pw", entry=True, password=True, build=lambda q: [])
        self.win.nav.push(p); self.pump(0.2)
        self.assertFalse(self.win.entry.get_visibility())
        self.win.nav.pop(); self.win.nav.pop(); self.pump(0.1)
        self.assertTrue(self.win.entry.get_visibility() or not self.win.entry.get_visible())


if __name__ == "__main__":
    unittest.main()
