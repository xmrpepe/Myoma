"""GTK4 front end. All Arch/system knowledge lives in the backend modules;
this file only draws Pages and routes keys."""

from __future__ import annotations

import datetime
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import __version__, config, desktop, system, themes  # noqa: E402
from .model import Item, Page  # noqa: E402

APP_ID = "dev.omamako.Launcher"
LAYER = None  # Gtk4LayerShell module, if used


def _try_layer_shell():
    """gtk4-layer-shell is optional. Python needs it loaded before libwayland;
    main() arranges that with LD_PRELOAD. Returns the module or None."""
    global LAYER
    if os.environ.get("OMAMAKO_NO_LAYER") or not os.environ.get("WAYLAND_DISPLAY"):
        return None
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as L
        if L.is_supported():
            LAYER = L
    except (ValueError, ImportError):
        LAYER = None
    return LAYER


class Navigator:
    """Owns the window contents and the page stack."""

    def __init__(self, window: "LauncherWindow"):
        self.win = window
        self.stack: list[Page] = []
        self.entries: list[desktop.DesktopEntry] = []

    # ---- public API used by pages ------------------------------------
    @property
    def page(self) -> Page:
        return self.stack[-1]

    def push(self, page: Page) -> None:
        if self.stack and self.page.blocks_back and self.page is not page:
            return
        self.stack.append(page)
        self.win.set_toast("")
        self.win.render(first=True)

    def pop(self) -> bool:
        if len(self.stack) <= 1 or self.page.blocks_back:
            return False
        self.stack.pop()
        self.win.render()
        return True

    def replace(self, page: Page) -> None:
        self.stack[-1] = page
        self.win.render(first=True)

    def home(self) -> None:
        del self.stack[1:]
        self.win.set_toast("")
        self.win.render(first=True)

    def reload(self) -> None:
        self.page.loaded = False
        self.win.render()

    def toast(self, msg: str, ok: bool = True) -> None:
        self.win.set_toast(msg, ok)

    def bg(self, fn, cb=None) -> None:
        """Run fn() in a worker thread; deliver its result to cb on the UI thread."""
        def work():
            try:
                res, err = fn(), None
            except Exception as e:  # surface instead of dying silently
                res, err = None, e
            if cb:
                GLib.idle_add(lambda: (cb(res, err), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def done(self) -> None:
        """Called after launching something: get out of the way."""
        self.win.dismiss()

    def refresh_apps(self) -> None:
        self.entries = desktop.scan()

    def apply_theme(self) -> None:
        self.win.apply_theme()


class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "OmamakoApp"):
        super().__init__(application=app)
        self.app = app
        self.set_title("omamako")
        self.set_decorated(False)
        self.set_default_size(640, 720)
        self.set_resizable(False)
        self.add_css_class("omamako")
        self.nav = Navigator(self)
        self._provider = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.add_css_class("root")
        for m in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{m}")(18)
        self.set_child(root)

        self.header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.clock = Gtk.Label(xalign=0); self.clock.add_css_class("clock")
        self.date = Gtk.Label(xalign=0); self.date.add_css_class("date")
        self.offline = Gtk.Label(label="offline — updates and package operations unavailable", xalign=0)
        self.offline.add_css_class("offline")
        self.offline.set_visible(False)
        self.header.append(self.clock); self.header.append(self.date)
        root.append(self.header)
        root.append(self.offline)

        self.crumb = Gtk.Label(xalign=0); self.crumb.add_css_class("heading")
        root.append(self.crumb)

        self.entry = Gtk.Entry(); self.entry.set_hexpand(True)
        self.entry.connect("changed", self._on_changed)
        self.entry.connect("activate", self._on_entry_activate)
        root.append(self.entry)

        self.view = Gtk.Stack(); self.view.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", lambda _l, row: self._activate_row(row))
        sc = Gtk.ScrolledWindow(); sc.set_child(self.listbox); sc.set_vexpand(True)
        self.scroller = sc
        self.view.add_named(sc, "list")
        self.custom_holder = Gtk.Box()
        self.view.add_named(self.custom_holder, "custom")
        root.append(self.view)

        self.toast_label = Gtk.Label(xalign=0, wrap=True)
        root.append(self.toast_label)
        self.hints = Gtk.Label(xalign=0); self.hints.add_css_class("hint")
        root.append(self.hints)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.connect("close-request", self._on_close)
        GLib.timeout_add_seconds(1, self._tick)
        GLib.timeout_add_seconds(20, self._poll_online)
        self.apply_theme()
        self._tick()

        if _try_layer_shell():
            L = LAYER
            L.init_for_window(self)
            L.set_layer(self, L.Layer.OVERLAY)
            L.set_keyboard_mode(self, L.KeyboardMode.EXCLUSIVE)
            L.set_namespace(self, "omamako")

    # ---- theme / clock ----------------------------------------------
    def apply_theme(self) -> None:
        cfg = config.load()
        css = themes.css(themes.load(cfg["general"]["theme"]), cfg["launcher"]["font_size"])
        display = Gdk.Display.get_default()
        if self._provider:
            Gtk.StyleContext.remove_provider_for_display(display, self._provider)
        self._provider = Gtk.CssProvider()
        if hasattr(self._provider, "load_from_string"):
            self._provider.load_from_string(css)
        else:
            self._provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(display, self._provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.header.set_visible(cfg["launcher"]["show_clock"])

    def _tick(self) -> bool:
        cfg = config.load()["launcher"]
        now = datetime.datetime.now()
        try:
            self.clock.set_label(now.strftime(cfg["clock_format"]))
            self.date.set_label(now.strftime(cfg["date_format"]))
        except ValueError:
            pass
        return True

    def _poll_online(self) -> bool:
        if self.is_visible():
            self.nav.bg(system.online, lambda ok, err: self.offline.set_visible(not ok))
        return True

    def set_toast(self, msg: str, ok: bool = True) -> None:
        self.toast_label.set_label(msg)
        for c in ("ok", "danger"):
            self.toast_label.remove_css_class(c)
        self.toast_label.add_css_class("ok" if ok else "danger")

    # ---- showing / hiding -------------------------------------------
    def open_fresh(self) -> None:
        from . import pages
        self.nav.refresh_apps()
        self.nav.stack = [pages.home(self.nav)]
        self.entry.set_text("")
        self.set_toast("")
        self.render(first=True)
        self.present()
        self._poll_online()

    def dismiss(self) -> None:
        if self.app.daemon:
            self.set_visible(False)
        else:
            self.app.quit()

    def _on_close(self, *_a) -> bool:
        if self.app.daemon:
            self.set_visible(False)
            return True
        return False

    # ---- rendering --------------------------------------------------
    def render(self, first: bool = False) -> None:
        nav, page = self.nav, self.nav.page
        if first:
            self.entry.handler_block_by_func(self._on_changed)
            self.entry.set_text(page.query)
            self.entry.handler_unblock_by_func(self._on_changed)
        titles = [p.title for p in nav.stack[1:]]
        self.crumb.set_label(" › ".join(titles))
        self.crumb.set_visible(bool(titles))
        self.header.set_visible(len(nav.stack) == 1 and config.load()["launcher"]["show_clock"])
        self.entry.set_visible(page.entry)
        self.entry.set_placeholder_text(page.placeholder)
        self.entry.set_visibility(not page.password)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD if page.password else Gtk.InputPurpose.FREE_FORM)

        if page.custom is not None:
            child = self.custom_holder.get_first_child()
            if child is not page.custom:
                if child:
                    self.custom_holder.remove(child)
                self.custom_holder.append(page.custom)
            self.view.set_visible_child_name("custom")
            self._hints(page)
            return
        self.view.set_visible_child_name("list")

        if page.load and not page.loaded:
            self._fill([Item("Loading…", heading=True)], page)
            self._load(page)
        else:
            self._fill(self._items_for(page), page)
        self._hints(page)
        if page.entry:
            self.entry.grab_focus()

    def _items_for(self, page: Page) -> list[Item]:
        if page.load:
            items = page.items
            if page.filter_local and page.query:
                q = page.query.lower()
                items = [i for i in items if i.heading or q in i.label.lower() or q in i.hint.lower()]
            return items
        return page.build(page.query) if page.build else []

    def _load(self, page: Page) -> None:
        def cb(res, err):
            if err is not None:
                page.items = [Item(f"Error: {err}", heading=True)]
            else:
                page.items = res
            page.loaded = True
            if self.nav.stack and self.nav.page is page:
                self._fill(self._items_for(page), page)
        self.nav.bg(page.load, cb)

    def _fill(self, items: list[Item], page: Page) -> None:
        self.listbox.remove_all()
        self._rows: list[tuple[Gtk.ListBoxRow, Item]] = []
        for it in items:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12)
            lab = Gtk.Label(label=it.label, xalign=0, hexpand=True)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(lab)
            if it.hint:
                h = Gtk.Label(label=it.hint, xalign=1); h.add_css_class("dim")
                h.set_ellipsize(Pango.EllipsizeMode.END); h.set_max_width_chars(34)
                box.append(h)
            if it.heading:
                lab.add_css_class("heading")
                row.set_selectable(False); row.set_activatable(False)
            if it.danger:
                lab.add_css_class("danger")
            row.set_child(box)
            self.listbox.append(row)
            self._rows.append((row, it))
        sel = [i for i, (_r, it) in enumerate(self._rows) if it.selectable]
        if sel:
            idx = 0 if page.default_cancel else min(page.sel, len(self._rows) - 1)
            if not self._rows[idx][1].selectable:
                idx = sel[0]
            self._select(idx)

    def _hints(self, page: Page) -> None:
        h = "↑↓ select · ⏎ open · ⎋ back"
        if page.custom is not None:
            self.hints.set_label("running… back is disabled until it finishes" if page.blocks_back
                                 else "⎋ back")
            return
        if page.custom is None and any(it.left or it.right for it in page.items):
            h += " · ←→ adjust"
        if self.nav.stack and len(self.nav.stack) == 1:
            h = "↑↓ select · ⏎ open · ^F favorite · ⎋ close"
        self.hints.set_label(h)

    # ---- selection / input ------------------------------------------
    def _select(self, idx: int) -> None:
        row = self._rows[idx][0]
        self.listbox.select_row(row)
        self.nav.page.sel = idx
        adj = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: self._scroll_to(row, adj) or False)

    def _scroll_to(self, row, adj) -> None:
        ok, rect = row.compute_bounds(self.listbox)
        if ok:
            top, bot = rect.get_y(), rect.get_y() + rect.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif bot > adj.get_value() + adj.get_page_size():
                adj.set_value(bot - adj.get_page_size())

    def _selected(self) -> Item | None:
        row = self.listbox.get_selected_row()
        for r, it in getattr(self, "_rows", []):
            if r is row:
                return it
        return None

    def _move(self, delta: int) -> None:
        rows = getattr(self, "_rows", [])
        row = self.listbox.get_selected_row()
        cur = next((i for i, (r, _it) in enumerate(rows) if r is row), -1)
        i = cur
        while True:
            i += delta
            if i < 0 or i >= len(rows):
                return
            if rows[i][1].selectable:
                self._select(i)
                return

    def _activate_row(self, row) -> None:
        for r, it in self._rows:
            if r is row and it.activate:
                it.activate()
                return

    def _on_changed(self, entry) -> None:
        page = self.nav.page
        page.query = entry.get_text()
        page.sel = 0
        if page.custom is None:
            self._fill(self._items_for(page), page)

    def _on_entry_activate(self, entry) -> None:
        page = self.nav.page
        text = entry.get_text()
        sel = self._selected()
        if page.submit and (text != page.last_submitted or sel is None or not sel.activate):
            page.last_submitted = text
            page.submit(text)
        elif sel and sel.activate:
            sel.activate()

    def _on_key(self, _ctl, keyval, _code, state) -> bool:
        page = self.nav.page
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        entry_text = self.entry.get_text() if page.entry else ""
        if keyval == Gdk.KEY_Escape:
            if entry_text and not page.password:
                self.entry.set_text("")
            elif not self.nav.pop() and len(self.nav.stack) == 1:
                self.dismiss()
            return True
        if page.custom is not None:
            return False
        if keyval in (Gdk.KEY_Down,) or (ctrl and keyval == Gdk.KEY_n):
            self._move(1); return True
        if keyval in (Gdk.KEY_Up,) or (ctrl and keyval == Gdk.KEY_p):
            self._move(-1); return True
        if keyval == Gdk.KEY_Page_Down:
            self._move(8); return True
        if keyval == Gdk.KEY_Page_Up:
            self._move(-8); return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not page.entry:
            sel = self._selected()
            if sel and sel.activate:
                sel.activate()
            return True
        if ctrl and keyval == Gdk.KEY_f:
            sel = self._selected()
            if sel and sel.fav:
                sel.fav()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and not entry_text:
            sel = self._selected()
            cb = sel and (sel.left if keyval == Gdk.KEY_Left else sel.right)
            if cb:
                cb(); return True
            if keyval == Gdk.KEY_Left and not page.entry:
                self.nav.pop(); return True
        if keyval == Gdk.KEY_BackSpace and not entry_text and not page.entry:
            self.nav.pop(); return True
        if keyval == Gdk.KEY_BackSpace and not entry_text and page.entry and len(self.nav.stack) > 1:
            self.nav.pop(); return True
        return False


class OmamakoApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.daemon = False
        self.win: LauncherWindow | None = None

    def _window(self) -> LauncherWindow:
        if self.win is None:
            self.win = LauncherWindow(self)
        return self.win

    def do_command_line(self, cmd) -> int:
        args = cmd.get_arguments()[1:]
        if "--version" in args:
            print(f"omamako {__version__}")
            return 0
        if "quit" in args:
            self.quit()
            return 0
        if "--daemon" in args:
            if not self.daemon:
                self.daemon = True
                self.hold()
                self._window()  # build now so the first toggle is instant
            return 0
        w = self._window()
        if "toggle" in args and w.is_visible():
            w.set_visible(False)
            if not self.daemon:
                self.quit()
            return 0
        w.open_fresh()
        return 0


def _maybe_preload_layer_shell() -> None:
    """Re-exec once with gtk4-layer-shell preloaded (needed before libwayland)."""
    if (os.environ.get("OMAMAKO_NO_LAYER") or not os.environ.get("WAYLAND_DISPLAY")
            or "layer-shell" in os.environ.get("LD_PRELOAD", "")
            or not config.load()["launcher"]["layer_shell"]):
        return
    for p in ("/usr/lib/libgtk4-layer-shell.so", "/usr/lib64/libgtk4-layer-shell.so",
              "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so"):
        if os.path.exists(p):
            env = dict(os.environ, LD_PRELOAD=(os.environ.get("LD_PRELOAD", "") + " " + p).strip())
            os.execve(sys.executable, [sys.executable, "-m", "omamako.ui.app", *sys.argv[1:]], env)


def main() -> int:
    config.ensure_default()
    _maybe_preload_layer_shell()
    return OmamakoApp().run(sys.argv[:1] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
