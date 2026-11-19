"""Configuration in ~/.config/omamako/config.toml (read with tomllib)."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from .util import config_dir, write_atomic

DEFAULTS: dict[str, Any] = {
    "general": {
        "theme": "tokyo-night",
        "terminal": "",          # empty = auto-detect
        "aur_helper": "auto",    # auto | paru | yay | none
    },
    "launcher": {
        "font_size": 16,
        "max_recents": 8,
        "show_clock": True,
        "clock_format": "%H:%M",
        "date_format": "%A, %d %B",
    },
    "hotkey": {
        "mod": "SUPER",
        "key": "space",
    },
    "startup": {
        "apps": [],              # desktop ids, e.g. ["firefox.desktop"]
    },
}


def config_path() -> Path:
    return config_dir() / "config.toml"


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(config_path(), "rb") as f:
            _merge(cfg, tomllib.load(f))
    except FileNotFoundError:
        pass
    except tomllib.TOMLDecodeError:
        # A broken user file must not take the launcher down: use defaults.
        pass
    return cfg


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def dumps(cfg: dict) -> str:
    out = []
    for section, table in cfg.items():
        out.append(f"[{section}]")
        for k, v in table.items():
            out.append(f"{k} = {_fmt(v)}")
        out.append("")
    return "\n".join(out)


def save(cfg: dict) -> None:
    write_atomic(config_path(), dumps(cfg))


def ensure_default() -> bool:
    """Write the default config if none exists. Returns True if written."""
    if config_path().exists():
        return False
    save(copy.deepcopy(DEFAULTS))
    return True


def _coerce(old: Any, raw: str) -> Any:
    if isinstance(old, bool):
        if raw.lower() in ("1", "true", "yes", "on"):
            return True
        if raw.lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"expected a boolean, got {raw!r}")
    if isinstance(old, int):
        return int(raw)
    if isinstance(old, float):
        return float(raw)
    if isinstance(old, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def get(dotted: str) -> Any:
    section, _, key = dotted.partition(".")
    cfg = load()
    if section not in cfg or key not in cfg[section]:
        raise KeyError(dotted)
    return cfg[section][key]


def set_value(dotted: str, raw: str) -> Any:
    section, _, key = dotted.partition(".")
    cfg = load()
    if section not in DEFAULTS or key not in DEFAULTS[section]:
        raise KeyError(f"unknown setting {dotted!r}")
    cfg[section][key] = _coerce(DEFAULTS[section][key], raw)
    save(cfg)
    return cfg[section][key]
