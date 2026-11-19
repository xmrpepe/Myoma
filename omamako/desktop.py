"""Freedesktop .desktop entry parsing (Desktop Entry Specification)."""

from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .util import xdg_data_dirs, xdg_data_home


@dataclass
class DesktopEntry:
    id: str
    path: str
    name: str
    exec: str
    comment: str = ""
    generic_name: str = ""
    icon: str = ""
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    terminal: bool = False
    working_dir: str = ""
    actions: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (name, exec)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "comment": self.comment,
            "generic_name": self.generic_name, "icon": self.icon,
            "categories": self.categories, "terminal": self.terminal,
            "exec": self.exec,
        }


def _unescape(v: str) -> str:
    return (v.replace("\\s", " ").replace("\\n", "\n").replace("\\t", "\t")
             .replace("\\r", "\r").replace("\\\\", "\\"))


def _split_list(v: str) -> list[str]:
    # ';' separated, '\;' is a literal semicolon
    parts = re.split(r"(?<!\\);", v)
    return [_unescape(p.replace("\\;", ";")) for p in parts if p.strip()]


def parse_file(path: str | Path) -> dict[str, dict[str, str]]:
    """Return {group: {key: value}}. Keys keep their [locale] suffix."""
    groups: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return groups
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = groups.setdefault(line[1:-1], {})
            continue
        if cur is None or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cur.setdefault(k.strip(), v.strip())  # first definition wins
    return groups


def _locales() -> list[str]:
    lang = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    lang = lang.split(".")[0].split("@")[0]
    if not lang or lang in ("C", "POSIX"):
        return []
    out = [lang]
    if "_" in lang:
        out.append(lang.split("_")[0])
    return out


def _localized(group: dict[str, str], key: str) -> str:
    for loc in _locales():
        v = group.get(f"{key}[{loc}]")
        if v:
            return _unescape(v)
    return _unescape(group.get(key, ""))


def _current_desktops() -> list[str]:
    return [d for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d]


def load_entry(path: str | Path, desktop_id: str) -> DesktopEntry | None:
    """Parse one file. Returns None for entries that must not be shown
    (Hidden, NoDisplay, wrong Type, OnlyShowIn/NotShowIn, missing TryExec)."""
    g = parse_file(path)
    main = g.get("Desktop Entry")
    if not main:
        return None
    if main.get("Type", "Application") != "Application":
        return None
    if main.get("Hidden", "").lower() == "true" or main.get("NoDisplay", "").lower() == "true":
        return None
    cur = _current_desktops()
    only, notin = _split_list(main.get("OnlyShowIn", "")), _split_list(main.get("NotShowIn", ""))
    if only and not (set(only) & set(cur)):
        return None
    if notin and (set(notin) & set(cur)):
        return None
    try_exec = main.get("TryExec")
    if try_exec and not (shutil.which(try_exec) if "/" not in try_exec else os.access(try_exec, os.X_OK)):
        return None
    name, exe = _localized(main, "Name"), main.get("Exec", "")
    if not name or not exe:
        return None
    actions = {}
    for aid in _split_list(main.get("Actions", "")):
        ag = g.get(f"Desktop Action {aid}")
        if ag and ag.get("Exec") and _localized(ag, "Name"):
            actions[aid] = (_localized(ag, "Name"), ag["Exec"])
    return DesktopEntry(
        id=desktop_id, path=str(path), name=name, exec=exe,
        comment=_localized(main, "Comment"), generic_name=_localized(main, "GenericName"),
        icon=main.get("Icon", ""), categories=_split_list(main.get("Categories", "")),
        keywords=_split_list(_localized(main, "Keywords")),
        terminal=main.get("Terminal", "").lower() == "true",
        working_dir=main.get("Path", ""), actions=actions,
    )


def application_dirs() -> list[Path]:
    return [xdg_data_home() / "applications"] + [d / "applications" for d in xdg_data_dirs()]


def scan() -> list[DesktopEntry]:
    """All visible applications. The first directory that defines an id wins
    (user entries override system ones, as the spec requires)."""
    seen: set[str] = set()
    entries: list[DesktopEntry] = []
    for base in application_dirs():
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.desktop")):
            did = str(p.relative_to(base)).replace("/", "-")
            if did in seen:
                continue
            seen.add(did)  # even if hidden: a hiding override must shadow
            e = load_entry(p, did)
            if e:
                entries.append(e)
    return sorted(entries, key=lambda e: e.name.lower())


def expand_exec(entry: DesktopEntry, exec_line: str | None = None,
                files: list[str] | None = None) -> list[str]:
    """Turn an Exec= value into an argv, handling field codes."""
    files = files or []
    argv: list[str] = []
    for tok in shlex.split(exec_line or entry.exec):
        if tok in ("%f", "%u"):
            argv += files[:1]
        elif tok in ("%F", "%U"):
            argv += files
        elif tok == "%i":
            if entry.icon:
                argv += ["--icon", entry.icon]
        elif tok == "%c":
            argv.append(entry.name)
        elif tok == "%k":
            argv.append(entry.path)
        else:
            tok = tok.replace("%%", "\0")
            tok = re.sub(r"%[fFuUdDnNvm]", "", tok).replace("\0", "%")
            if tok:
                argv.append(tok)
    return argv


def find_terminal(preferred: str = "") -> list[str] | None:
    """argv prefix that runs a command in a terminal, or None."""
    cands = [preferred, os.environ.get("TERMINAL", ""), "xdg-terminal-exec",
             "foot", "kitty", "alacritty", "ghostty", "wezterm", "gnome-terminal", "konsole", "xterm"]
    for c in cands:
        if c and shutil.which(c):
            if c == "xdg-terminal-exec":
                return [c]
            if c == "gnome-terminal":
                return [c, "--"]
            if c in ("wezterm",):
                return [c, "start", "--"]
            return [c, "-e"]
    return None
