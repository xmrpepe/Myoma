# ANALYSIS

Findings from reading the two upstream sources (omalauncher v1.7.0, mako 2026.59)
and the resulting plan ("option B": a new native Arch desktop launcher that
borrows from both projects). Nothing here is assumed: every claim below was
read from the upstream trees.

## 1. The two upstreams

### omalauncher v1.7.0 — MIT, © Simon Schubert and contributors
- **What it is:** an *Android* home screen styled like Omarchy, with an optional
  Arch Linux ARM userland under **proot** (no root), acting as its own Wayland
  compositor (`wayland/`, `cpp/wlbridge.c`). (`docs/ARCHITECTURE.md`)
- **Languages / build:** Kotlin + Jetpack Compose, one C file (JNI), Gradle
  (`build.gradle.kts`, `app/`, `owl/`), fastlane for store metadata.
  The `owl` module is a small widget language compiler.
- **GUI / frontend (not reusable on desktop):** `ui/**` (home, settings, files,
  store, voice), `widgets/render`, `res/**`, `wayland/WindowRenderer`,
  `MainActivity.kt`, art, fastlane, Compose theme (`ui/Theme.kt`).
- **System logic:** `linux/` (proot, rootfs setup, pacman db parsing —
  `PacmanDbTest`, AUR assets under `assets/aur`), `theme/GuestThemeConfig.kt`
  (renders Omarchy theme templates), `upgrade/` (managed files).
  **All of it depends on Android APIs / proot / the app sandbox layout**, so it
  cannot be lifted into a desktop Arch install as code. There is no
  `.desktop` parsing, no systemd, no Hyprland, no polkit.
- **Reusable as data:** `app/src/main/assets/themes/*.toml` — 23 Omarchy colour
  themes with a flat key set (`mode, accent, selection, muted, background,
  foreground, red … bright_magenta`). These are the Omarchy palette files and
  are directly usable. (MIT; credited in README and `THIRD_PARTY.md`.)

### mako 2026.59 — GPL-3.0
- **What it is:** a minimal, privacy-first *Android* launcher in native Kotlin
  (`app/`, shared lib `bohio`, Gradle). Entry: `activities/MainActivity.kt`.
- **Architecture:** `managers/` (AppsProvider, GroupManager, PrefsManager,
  ClockManager, BatteryManager, IconManager…) feed view-based screens
  (`res/layout/view_home.xml`, `list_item_app.xml`, `list_item_group.xml`),
  Settings split per topic (`activities/settings/Settings*Controller.kt`:
  appearance, icons, groups, clock, date, pin).
- **How it renders menus:** a text-first home: clock + date + battery header,
  a vertical list of app labels, collapsible **groups** with headers, an
  optional search field, no icons by default, per-app rename/hide. Data comes
  from Android `LauncherApps` through `AppsProvider`; actions are intents.
  Prefs are a keyed store (`apps:search`, `groups:collapsible`,
  `clock:format`, `date:format`, `apps:font_size`, `apps:multi_column` …).
- **Reusable:** the *design language and information architecture* (not code):
  minimal text list, clock/date header, groups, search, settings pages, and
  its preference vocabulary. Android Views code cannot run on Wayland/X11.
- **License consequence:** GPL-3.0 material is mirrored in the UX, so the
  combined work is distributed under **GPL-3.0-or-later**; the MIT notice of
  omalauncher is kept alongside (MIT is GPL-compatible).

## 2. Why a literal merge is impossible
Both are Android apps. Stripping omalauncher's GUI would delete essentially
the whole program, and mako has no desktop renderer. The user chose
**option B: a new native Arch launcher**, with mako's look/IA and omalauncher's
Omarchy themes and Arch-focus (pacman + AUR) as inputs.

## 3. Integration plan (what gets built)

```
 omamako (GTK4 frontend, python-gobject)         <- UI only, mako-style
        │  spawns, reads JSON / NDJSON on stdout
        ▼
 omamako-ctl (CLI)  ──►  omamako_core (stdlib-only Python library)
                           apps · history · system · packages
                           network · themes · config · hotkey
                           │
        pacman / paru|yay / pkexec / systemctl / loginctl / nmcli /
        wpctl|pactl / bluetoothctl / hyprctl|swaymsg|xrandr
```

**Boundary: a CLI with machine-readable output** (`omamako-ctl <group> <verb>
--json`, long operations stream NDJSON lines). Reasons: no daemon to keep
alive or secure; every backend feature is scriptable and unit-testable without
a display; the GUI needs no Arch knowledge and can be swapped; privileged work
goes through `pkexec` (polkit), never through a long-running root service.
The library is importable for the frontend's cheap calls (app list, search).

| Area | Mechanism |
|---|---|
| Apps | parse `.desktop` (XDG data dirs, `Hidden/NoDisplay/OnlyShowIn/TryExec`, Exec field codes), launch via `Gio.AppInfo` / detached `Popen` |
| Favorites / recents | JSON in `$XDG_STATE_HOME/omamako` |
| Power | `loginctl`/`systemctl` (poweroff, reboot, suspend), lock via `loginctl lock-session` or first of hyprlock/swaylock/xdg-screensaver, logout via `hyprctl dispatch exit` / `swaymsg exit` / `loginctl terminate-session` |
| Network | `nmcli` (state, wifi list/connect, radio), offline detection |
| Audio | `wpctl` (PipeWire), fall back to `pactl` |
| Display | `hyprctl`, `wlr-randr`, `xrandr`; brightness via `brightnessctl` |
| Bluetooth | `bluetoothctl` |
| Packages | `pacman -Ss/-Qi/-Qu`; `checkupdates` if present; install/remove/upgrade via `pkexec pacman`; AUR via `paru`/`yay` (`--sudo pkexec`) |
| Themes | Omarchy TOML palettes → CSS + terminal-friendly vars |
| Settings | `~/.config/omamako/config.toml` (+ startup apps, keybinding snippets) |
| Hotkey | Wayland compositors own global keys, so the app is single-instance (D-Bus `Gio.Application`) with a `toggle` action; `omamako-ctl hotkey install` writes a Hyprland/Sway/i3 snippet using the configured key |

Network: no sandboxing is applied (no seccomp, no network namespaces, systemd
unit has no `PrivateNetwork`/`IPAddressDeny`); offline state is detected and
shown, never fatal.

## 4. Verification limits (honest)
The build host is Ubuntu 24.04 without pacman/makepkg. Backend logic is
tested with fake `pacman`/`nmcli`/… executables on `PATH`; the GTK frontend is
rendered under Xvfb. `makepkg -si` itself and real polkit prompts **cannot be
exercised here** and will be listed as unverified in `TESTING.md`.
