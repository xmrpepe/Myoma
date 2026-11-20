"""App catalogue: search, categories, favorites, recents, launching."""

from __future__ import annotations

import os
import subprocess
import time

from . import config, desktop
from .util import read_json, state_dir, write_json

CATEGORY_MAP = [  # (display name, desktop-spec category) in display order
    ("Internet", "Network"), ("Development", "Development"), ("Office", "Office"),
    ("Media", "AudioVideo"), ("Media", "Audio"), ("Media", "Video"),
    ("Graphics", "Graphics"), ("Games", "Game"), ("Education", "Education"),
    ("Science", "Science"), ("Settings", "Settings"), ("System", "System"),
    ("Utilities", "Utility"),
]


def category_of(entry: desktop.DesktopEntry) -> str:
    for label, cat in CATEGORY_MAP:
        if cat in entry.categories:
            return label
    return "Other"


def categories(entries: list[desktop.DesktopEntry]) -> dict[str, list[desktop.DesktopEntry]]:
    out: dict[str, list[desktop.DesktopEntry]] = {}
    for e in entries:
        out.setdefault(category_of(e), []).append(e)
    order = [c for c, _ in CATEGORY_MAP] + ["Other"]
    return {k: out[k] for k in dict.fromkeys(order) if k in out}


# ---- favorites / recents -------------------------------------------------

def _fav_path():
    return state_dir() / "favorites.json"


def _rec_path():
    return state_dir() / "recents.json"


def favorites() -> list[str]:
    v = read_json(_fav_path(), [])
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def set_favorite(app_id: str, on: bool) -> list[str]:
    favs = [f for f in favorites() if f != app_id]
    if on:
        favs.append(app_id)
    write_json(_fav_path(), favs)
    return favs


def recents() -> list[dict]:
    v = read_json(_rec_path(), [])
    return [r for r in v if isinstance(r, dict) and "id" in r] if isinstance(v, list) else []


def record_launch(app_id: str) -> None:
    items = recents()
    cur = next((r for r in items if r["id"] == app_id), None)
    if cur:
        items.remove(cur)
    else:
        cur = {"id": app_id, "count": 0}
    cur["count"] = int(cur.get("count", 0)) + 1
    cur["ts"] = int(time.time())
    items.insert(0, cur)
    write_json(_rec_path(), items[:100])


def recent_ids(limit: int | None = None) -> list[str]:
    limit = limit if limit is not None else config.load()["launcher"]["max_recents"]
    return [r["id"] for r in recents()][:limit]


# ---- search --------------------------------------------------------------

def _subsequence(q: str, s: str) -> bool:
    it = iter(s)
    return all(c in it for c in q)


def score(entry: desktop.DesktopEntry, query: str) -> int:
    """0 = no match. Higher is better."""
    q = query.lower().strip()
    if not q:
        return 1
    name = entry.name.lower()
    if name == q:
        return 100
    if name.startswith(q):
        return 90
    if any(w.startswith(q) for w in name.replace("-", " ").split()):
        return 80
    if q in name:
        return 70
    if any(q in k.lower() for k in entry.keywords) or q in entry.generic_name.lower():
        return 50
    if q in entry.comment.lower() or q in entry.id.lower():
        return 40
    if len(q) >= 3 and _subsequence(q, name):
        return 20
    return 0


def search(query: str, entries: list[desktop.DesktopEntry] | None = None,
           limit: int | None = None) -> list[desktop.DesktopEntry]:
    entries = desktop.scan() if entries is None else entries
    rank = {a: i for i, a in enumerate(recent_ids(100))}
    favs = set(favorites())
    scored = []
    for e in entries:
        s = score(e, query)
        if s:
            bonus = (5 if e.id in favs else 0) + (3 if e.id in rank else 0)
            scored.append((-(s + bonus), rank.get(e.id, 1000), e.name.lower(), e))
    scored.sort(key=lambda t: t[:3])
    out = [t[3] for t in scored]
    return out[:limit] if limit else out


def by_id(app_id: str, entries: list[desktop.DesktopEntry] | None = None):
    for e in (desktop.scan() if entries is None else entries):
        if e.id == app_id or e.id == app_id + ".desktop":
            return e
    return None


# ---- launching -----------------------------------------------------------

def launch_argv(entry: desktop.DesktopEntry, action: str | None = None,
                files: list[str] | None = None) -> list[str]:
    exec_line = entry.actions[action][1] if action else entry.exec
    argv = desktop.expand_exec(entry, exec_line, files)
    if entry.terminal:
        term = desktop.find_terminal(config.load()["general"]["terminal"])
        if not term:
            raise RuntimeError("this app needs a terminal and none was found")
        argv = term + argv
    return argv


def launch(app_id: str, action: str | None = None, files: list[str] | None = None) -> list[str]:
    entry = by_id(app_id)
    if entry is None:
        raise KeyError(f"no such application: {app_id}")
    if action and action not in entry.actions:
        raise KeyError(f"{app_id} has no action {action!r}")
    argv = launch_argv(entry, action, files)
    subprocess.Popen(
        argv, cwd=entry.working_dir if entry.working_dir and os.path.isdir(entry.working_dir) else None,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    record_launch(entry.id)
    return argv


def run_startup() -> list[str]:
    """Launch the apps listed under [startup] apps. Returns ids launched."""
    done = []
    for app_id in config.load()["startup"]["apps"]:
        try:
            launch(app_id)
            done.append(app_id)
        except (KeyError, RuntimeError, OSError):
            continue
    return done
