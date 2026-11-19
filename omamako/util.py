"""Small shared helpers: running commands, XDG paths, JSON state files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence


@dataclass
class Result:
    ok: bool
    code: int
    out: str = ""
    err: str = ""
    argv: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "code": self.code, "out": self.out, "err": self.err}


def which(name: str) -> str | None:
    return shutil.which(name)


def run(argv: Sequence[str], timeout: float = 15, input: str | None = None,
        env: dict | None = None) -> Result:
    """Run a command without a shell. Never raises: a missing binary or a
    timeout is reported as a failed Result."""
    argv = [str(a) for a in argv]
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, input=input,
            env={**os.environ, **(env or {})}, stdin=None if input else subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return Result(False, 127, "", f"{argv[0]}: command not found", argv)
    except subprocess.TimeoutExpired:
        return Result(False, 124, "", f"{argv[0]}: timed out after {timeout}s", argv)
    except OSError as e:  # e.g. permission denied
        return Result(False, 126, "", f"{argv[0]}: {e}", argv)
    return Result(p.returncode == 0, p.returncode, p.stdout, p.stderr.strip(), argv)


def stream(argv: Sequence[str], env: dict | None = None) -> Iterator[tuple[str, str | int]]:
    """Run a long command, yielding ("line", text) for each output line
    (stdout and stderr merged) and finally ("done", exit_code)."""
    argv = [str(a) for a in argv]
    try:
        p = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})}, bufsize=1,
        )
    except FileNotFoundError:
        yield ("line", f"{argv[0]}: command not found")
        yield ("done", 127)
        return
    assert p.stdout is not None
    try:
        for line in p.stdout:
            yield ("line", line.rstrip("\n"))
    finally:
        p.stdout.close()
    yield ("done", p.wait())


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def xdg_data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(p) for p in raw.split(":") if p]


def config_dir() -> Path:
    return xdg_config_home() / "omamako"


def state_dir() -> Path:
    return xdg_state_home() / "omamako"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, indent=2))
