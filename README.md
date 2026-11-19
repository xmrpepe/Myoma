# omamako

A minimal, keyboard-driven launcher and system menu for **Arch Linux**
(Wayland: Hyprland/Sway, or X11), written in Python + GTK4.

It is a *new* desktop application built from two Android projects, because
neither upstream can run on a desktop as-is (see `ANALYSIS.md`):

* **[Mako](https://github.com/rama-io/mako)** (rama-io, GPL-3.0) — the UI model: a quiet, text-first
  launcher with clock, search, groups, favorites and recents.
* **[Omalauncher](https://github.com/SimonSchubert/omalauncher)** (Simon Schubert, MIT) — the Omarchy
  look (23 colour themes) and the Arch/pacman focus.

Thank you to both projects. Licences: see `LICENSE` (GPL-3.0), `LICENSE.omalauncher-MIT`, `THIRD_PARTY.md`.

## What it does

| Menu | Contents |
|---|---|
| **Launcher** | search apps *and* commands; favorites (`Ctrl+F`), recents, all apps, categories |
| **System** | power (lock, log out, suspend, hibernate, reboot, shut down — destructive ones ask first), network (Wi-Fi list/connect), audio (volume, mute, output), display (outputs, brightness), Bluetooth |
| **Packages** | search repos + AUR, install, remove, update, list updates, installed list; password prompts via polkit (`pkexec`) |
| **Settings** | 23 themes, hotkey/keybindings, startup apps, launcher options, edit config |

Keys: `↑↓`/`Ctrl+N/P` move · `Enter` open · `Esc`/`Backspace`/`←` back · `←→` adjust sliders ·
`Ctrl+F` favorite. Offline is detected and shown; nothing is sandboxed or firewalled.

## Install

```sh
git clone https://github.com/xmrpepe/Myoma && cd Myoma
makepkg -si
```
Then see [INSTALL.md](INSTALL.md) for hotkey/Wayland/X11 setup. Uninstall: `omamako-ctl cleanup [--purge]; sudo pacman -Rns omamako`.

## Backend CLI

`omamako-ctl` exposes everything as JSON, e.g. `omamako-ctl apps search fire`,
`omamako-ctl pkg updates`, `omamako-ctl power reboot --dry-run`, `omamako-ctl doctor`.

## Tests

```sh
python -m unittest discover -s tests -p test_backend.py            # no display needed
xvfb-run python -m unittest discover -s tests -p test_ui.py        # drives the GTK window
```
See [TESTING.md](TESTING.md) for what has and has not been verified.

## License
GPL-3.0-or-later. Bundled palettes MIT (Omalauncher). See `THIRD_PARTY.md`.
