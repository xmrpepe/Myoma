"""Omarchy colour themes (flat TOML palettes) -> GTK CSS."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .util import config_dir

REQUIRED = ("background", "foreground", "accent")


def bundled_dir() -> Path:
    return Path(__file__).parent / "data" / "themes"


def user_dir() -> Path:
    return config_dir() / "themes"


def _load(path: Path) -> dict | None:
    try:
        with open(path, "rb") as f:
            t = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not all(isinstance(t.get(k), str) for k in REQUIRED):
        return None
    return t


def available() -> dict[str, Path]:
    out = {p.stem: p for p in sorted(bundled_dir().glob("*.toml"))}
    if user_dir().is_dir():
        out.update({p.stem: p for p in sorted(user_dir().glob("*.toml"))})
    return out


def load(name: str) -> dict:
    """Palette for `name`; falls back to tokyo-night, then to a hard default."""
    av = available()
    for n in (name, "tokyo-night"):
        if n in av and (t := _load(av[n])):
            return t
    return {"mode": "dark", "background": "#1a1b26", "foreground": "#a9b1d6",
            "accent": "#7aa2f7", "selection": "#33467c", "muted": "#444b6a"}


def css(theme: dict, font_size: int = 16) -> str:
    bg, fg, ac = theme["background"], theme["foreground"], theme["accent"]
    sel = theme.get("selection", ac)
    muted = theme.get("muted", fg)
    dim = theme.get("dark_foreground", muted)
    red, green = theme.get("red", "#f7768e"), theme.get("green", "#9ece6a")
    return f"""
window.omamako, window.omamako .root {{ background-color: {bg}; color: {fg}; }}
.omamako {{ font-size: {font_size}px; }}
.omamako label {{ color: {fg}; }}
.omamako .dim, .omamako .hint {{ color: {dim}; }}
.omamako .clock {{ font-size: {font_size * 3}px; font-weight: 300; }}
.omamako .date {{ color: {dim}; }}
.omamako .heading {{ color: {ac}; font-weight: bold; margin-top: 10px; }}
.omamako entry, .omamako entry text {{ background: {theme.get('lighter_background', bg)};
    color: {fg}; border: none; box-shadow: none; border-radius: 6px; min-height: 36px; }}
.omamako entry:focus-within {{ outline: 1px solid {ac}; }}
.omamako list, .omamako listview, .omamako scrolledwindow {{ background: transparent; }}
.omamako row, .omamako listview > row {{ padding: 6px 10px; border-radius: 6px; background: transparent; }}
.omamako row:selected, .omamako row:hover, .omamako listview > row:selected {{
    background-color: {sel}; color: {fg}; }}
.omamako row:selected label {{ color: {ac}; }}
.omamako button {{ background: {theme.get('lighter_background', sel)}; color: {fg};
    border: none; box-shadow: none; border-radius: 6px; padding: 6px 12px; }}
.omamako button:hover {{ background: {sel}; }}
.omamako .danger {{ color: {red}; }}
.omamako .ok {{ color: {green}; }}
.omamako .offline {{ background: {red}; color: {bg}; padding: 4px 10px; border-radius: 6px; }}
.omamako progressbar trough {{ background: {sel}; min-height: 6px; }}
.omamako progressbar progress {{ background: {ac}; min-height: 6px; }}
.omamako scale trough {{ background: {sel}; }}
.omamako scale highlight {{ background: {ac}; }}
"""
