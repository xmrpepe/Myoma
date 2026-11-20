"""Package backend: pacman for the repos, paru/yay for the AUR.

Privilege model
  * Reads (-Ss, -Qi, -Qu, checkupdates) run as the user.
  * Writes to the system go through `pkexec pacman ...` (polkit). The password
    is typed into the desktop's polkit agent, never into this program.
  * AUR builds run as the user inside a terminal (not non-interactively), so
    PKGBUILDs can be reviewed by the helper before anything is built. The
    helper is told to use pkexec for its own privilege escalation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from . import config
from .util import Result, run, stream, which

NAME_RE = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]*$")
DB_LOCK = Path("/var/lib/pacman/db.lck")


def validate(names: list[str]) -> list[str]:
    """Package names become argv entries after `--`; still reject anything that
    is not a valid pacman package name so nothing odd reaches a root process."""
    if not names:
        raise ValueError("no package given")
    for n in names:
        if not NAME_RE.match(n):
            raise ValueError(f"invalid package name: {n!r}")
    return names


def aur_helper() -> str | None:
    want = config.load()["general"]["aur_helper"]
    if want == "none":
        return None
    for h in ([want] if want != "auto" else ["paru", "yay"]):
        if which(h):
            return h
    return None


def _priv() -> list[str]:
    """argv prefix that elevates through polkit (or sudo -A with an askpass)."""
    if which("pkexec"):
        return ["pkexec"]
    if which("sudo") and os.environ.get("SUDO_ASKPASS"):
        return ["sudo", "-A"]
    raise RuntimeError("no way to elevate: install polkit (pkexec) or set SUDO_ASKPASS")


def status() -> dict:
    return {
        "pacman": bool(which("pacman")),
        "aur_helper": aur_helper(),
        "checkupdates": bool(which("checkupdates")),
        "pkexec": bool(which("pkexec")),
        "locked": DB_LOCK.exists(),
    }


# --------------------------------------------------------------------- reads

def parse_search(text: str) -> list[dict]:
    """Parse `pacman -Ss` / `paru -Ssa` output: a header line
    `repo/name version [group] [installed]` followed by an indented description."""
    out: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            if out:
                out[-1]["description"] = (out[-1]["description"] + " " + line.strip()).strip()
            continue
        m = re.match(r"^(\S+)/(\S+)\s+(\S+)(.*)$", line)
        if not m:
            continue
        rest = m[4]
        out.append({
            "repo": m[1], "name": m[2], "version": m[3], "description": "",
            "installed": "[installed" in rest or "[Installed" in rest,
        })
    return out


def search(query: str, aur: bool = True) -> dict:
    query = query.strip()
    if not query:
        return {"results": [], "errors": []}
    errors, results = [], []
    r = run(["pacman", "-Ss", "--", query], timeout=30)
    if r.ok:
        results += parse_search(r.out)
    elif r.code != 1:  # pacman -Ss exits 1 for "no match"
        errors.append(r.err or "pacman search failed")
    h = aur_helper() if aur else None
    if h:
        from .system import online
        if online():
            r = run([h, "-Ssa", "--", query], timeout=45)
            if r.ok:
                results += [x for x in parse_search(r.out) if x["repo"] == "aur"]
            elif r.code != 1:
                errors.append(r.err or f"{h} search failed")
        else:
            errors.append("offline: AUR search skipped")
    return {"results": results, "errors": errors}


def installed() -> list[dict]:
    r = run(["pacman", "-Q"], timeout=30)
    return [{"name": p[0], "version": p[1]} for p in
            (l.split() for l in r.out.splitlines()) if len(p) == 2] if r.ok else []


def explicit() -> list[dict]:
    """Packages the user asked for (not dependencies): the sensible remove list."""
    r = run(["pacman", "-Qe"], timeout=30)
    return [{"name": p[0], "version": p[1]} for p in
            (l.split() for l in r.out.splitlines()) if len(p) == 2] if r.ok else []


def info(name: str) -> dict:
    validate([name])
    r = run(["pacman", "-Qi", "--", name])
    if not r.ok:
        r = run(["pacman", "-Si", "--", name])
    d = {}
    for line in r.out.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            d[k.strip()] = v.strip()
    return d


def updates() -> dict:
    """Pending updates. Prefers `checkupdates` (fresh db copy, no root)."""
    errors = []
    if which("checkupdates"):
        r = run(["checkupdates"], timeout=90)
        # exit 2 means "no updates"
        ok = r.ok or r.code == 2
        if not ok:
            errors.append(r.err or "checkupdates failed")
    else:
        r = run(["pacman", "-Qu"], timeout=30)
        ok = r.ok or r.code == 1
    repo = []
    if ok:
        for line in r.out.splitlines():
            m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)", line)
            if m:
                repo.append({"name": m[1], "old": m[2], "new": m[3], "source": "repo"})
    aur = []
    h = aur_helper()
    if h:
        r = run([h, "-Qua"], timeout=60)
        for line in r.out.splitlines() if r.ok else []:
            m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)", line)
            if m:
                aur.append({"name": m[1], "old": m[2], "new": m[3], "source": "aur"})
    return {"repo": repo, "aur": aur, "errors": errors}


def is_repo_package(name: str) -> bool:
    validate([name])
    return run(["pacman", "-Si", "--", name]).ok


# -------------------------------------------------------------------- writes

def _need_online() -> None:
    from .system import online
    if not online():
        raise ConnectionError("offline: cannot reach the package servers")


def _need_unlocked() -> None:
    if DB_LOCK.exists():
        raise RuntimeError(f"pacman database is locked ({DB_LOCK}); is another pacman running?")


def install_cmd(names: list[str]) -> list[str]:
    # -S (not -Sy): a bare refresh followed by an install risks a partial upgrade.
    return _priv() + ["pacman", "-S", "--needed", "--noconfirm", "--"] + validate(names)


def remove_cmd(names: list[str]) -> list[str]:
    return _priv() + ["pacman", "-Rns", "--noconfirm", "--"] + validate(names)


def update_cmd() -> list[str]:
    return _priv() + ["pacman", "-Syu", "--noconfirm"]


def aur_cmd(verb: str, names: list[str] | None = None) -> list[str]:
    h = aur_helper()
    if not h:
        raise RuntimeError("no AUR helper (paru or yay) installed")
    sudo = ["--sudo", "pkexec"] if which("pkexec") else []
    if verb == "install":
        return [h, "-S", "--needed"] + sudo + ["--"] + validate(names or [])
    if verb == "update":
        return [h, "-Syu"] + sudo
    raise KeyError(verb)


def run_stream(argv: list[str]) -> Iterator[tuple[str, str | int]]:
    return stream(argv, env={"LC_ALL": "C"})


def install(names: list[str], source: str = "auto") -> list[str]:
    """Return the argv to run. source: repo | aur | auto (repo first)."""
    _need_online()
    _need_unlocked()
    validate(names)
    if source == "auto":
        source = "repo" if all(is_repo_package(n) for n in names) else "aur"
    return install_cmd(names) if source == "repo" else aur_cmd("install", names)


def remove(names: list[str]) -> list[str]:
    _need_unlocked()
    return remove_cmd(names)


def update(include_aur: bool = False) -> list[str]:
    _need_online()
    _need_unlocked()
    return aur_cmd("update") if include_aur else update_cmd()


def needs_terminal(argv: list[str]) -> bool:
    """AUR helper commands are interactive (PKGBUILD review) and need a tty."""
    h = aur_helper()
    return bool(h) and bool(argv) and os.path.basename(argv[0]) == h
