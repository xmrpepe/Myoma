"""Toolkit-free description of menus: a Page is a titled list of Items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Item:
    label: str
    hint: str = ""
    activate: Callable[[], None] | None = None   # Enter
    left: Callable[[], None] | None = None       # Left arrow (e.g. volume down)
    right: Callable[[], None] | None = None      # Right arrow
    fav: Callable[[], None] | None = None        # Ctrl+F
    heading: bool = False
    danger: bool = False
    key: str = ""                                # stable id, used for selection restore

    @property
    def selectable(self) -> bool:
        return not self.heading


def heading(text: str) -> Item:
    return Item(text, heading=True)


@dataclass
class Page:
    title: str
    # sync builder: query text -> items.  Used when `load` is None.
    build: Callable[[str], list[Item]] | None = None
    # slow loader, run in a worker thread: () -> items.  Query filters labels locally.
    load: Callable[[], list[Item]] | None = None
    entry: bool = False                 # show a text entry
    placeholder: str = ""
    password: bool = False
    submit: Callable[[str], None] | None = None   # Enter inside the entry
    filter_local: bool = False          # filter loaded items by the query
    custom: object | None = None        # a Gtk widget to show instead of the list
    blocks_back: bool = False           # True while a task is running
    default_cancel: bool = False        # confirm pages start on item 0
    # runtime state, owned by the navigator
    query: str = ""
    items: list[Item] = field(default_factory=list)
    loaded: bool = False
    sel: int = 0
    last_submitted: str = ""
