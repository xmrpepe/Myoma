"""Global hotkey: wired up through the compositor, not grabbed by the app.

Wayland has no portable global-grab API, so omamako writes a small snippet
for the user's compositor that runs `omamako toggle` and includes it from the
main config between marker comments (so it can be removed cleanly).
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .system import compositor
from .util import config_dir, write_atomic

MARK_BEGIN = "# >>> omamako hotkey (managed)"
MARK_END = "# <<< omamako hotkey"

SWAY_MODS = {"SUPER": "Mod4", "ALT": "Mod1", "CTRL": "Ctrl", "SHIFT": "Shift"}
CMD = "omamako toggle"


def _combo() -> tuple[str, str]:
    h = config.load()["hotkey"]
    return h["mod"], h["key"]


def snippet(comp: str) -> str:
    mod, key = _combo()
    if comp == "hyprland":
        return f"bind = {mod}, {key}, exec, {CMD}\n"
    if comp in ("sway", "i3"):
        m = "+".join(SWAY_MODS.get(p.strip().upper(), p.strip()) for p in mod.replace(",", "+").split("+") if p.strip())
        return f"bindsym {m}+{key} exec {CMD}\n"
    # X11 without i3: generic sxhkd syntax
    return f"{mod.lower()} + {key}\n    {CMD}\n"


def _paths(comp: str) -> tuple[Path, Path, str]:
    """(main config, snippet file, include line)"""
    home = Path.home()
    cfg = config_dir()
    if comp == "hyprland":
        snip = cfg / "hotkey.hypr.conf"
        return home / ".config/hypr/hyprland.conf", snip, f"source = {snip}"
    if comp == "sway":
        snip = cfg / "hotkey.sway.conf"
        return home / ".config/sway/config", snip, f"include {snip}"
    if comp == "i3":
        snip = cfg / "hotkey.i3.conf"
        return home / ".config/i3/config", snip, f"include {snip}"
    raise ValueError(f"automatic setup is not available for {comp!r}; use `omamako-ctl hotkey show`")


def show(comp: str | None = None) -> dict:
    comp = comp or compositor()
    return {"compositor": comp, "combo": "+".join(_combo()), "snippet": snippet(comp)}


def install(comp: str | None = None) -> dict:
    comp = comp or compositor()
    main, snip, include = _paths(comp)
    write_atomic(snip, snippet(comp))
    text = main.read_text() if main.exists() else ""
    if MARK_BEGIN not in text:
        block = f"\n{MARK_BEGIN}\n{include}\n{MARK_END}\n"
        write_atomic(main, text + block)
    return {"compositor": comp, "snippet_file": str(snip), "main_config": str(main)}


def remove(comp: str | None = None) -> dict:
    comp = comp or compositor()
    main, snip, _ = _paths(comp)
    removed = False
    if main.exists():
        lines, out, skip = main.read_text().splitlines(), [], False
        for l in lines:
            if l.strip() == MARK_BEGIN:
                skip, removed = True, True
                continue
            if skip:
                if l.strip() == MARK_END:
                    skip = False
                continue
            out.append(l)
        if removed:
            write_atomic(main, "\n".join(out).rstrip("\n") + "\n")
    snip.unlink(missing_ok=True)
    return {"compositor": comp, "removed": removed}
