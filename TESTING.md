# TESTING

Host used: **Ubuntu 24.04** sandbox (no Arch, no Wayland compositor, no real polkit agent,
no NetworkManager/PipeWire/BlueZ). Everything below says exactly which environment it ran in.

## Automated (41 tests, all passing)
* `tests/test_backend.py` (26): .desktop parsing/filtering/overrides, search ranking, favorites/recents,
  launching, power command mapping, nmcli/wpctl/bluetoothctl/brightnessctl parsing, pacman/AUR parsing,
  package-name validation, pkexec argv, offline/db-lock refusal, config round-trip, themes, hotkey
  install/remove, `omamako-ctl` JSON output, `cleanup`. System tools are **stub executables** on `PATH`.
* `tests/test_ui.py` (16): drives the real GTK4 window under Xvfb through its key handler.

## Menu-by-menu results

| Menu / option | Result | How verified |
|---|---|---|
| Launcher: search apps, search commands, Enter to launch, recents, favorites (Ctrl+F) | works | GTK under Xvfb, real `.desktop` files, app really spawned |
| All apps / Categories | works | Xvfb |
| Keyboard: ↑↓, Ctrl+N/P, Enter, Esc, Backspace, ← back, ←→ adjust | works | key handler driven in tests (synthetic calls, not X key events) |
| Power: lock, log out, suspend, hibernate, reboot, shut down | works with stubs | confirmation page appears for destructive actions, default is *Cancel*; `systemctl poweroff/suspend` stub invoked only after confirm. **Real power actions were not executed.** |
| Network: status, Wi-Fi toggle, network list, connect, password page | works with stub `nmcli` | list parsing incl. escaped colons; password sent on stdin. **Real `nmcli --ask` stdin behaviour untested.** |
| Audio: volume ±, mute, output switch | works with stub `wpctl`/`pactl` | not tried on PipeWire |
| Display: outputs, brightness | works with stub | `hyprctl`/`swaymsg` JSON field names taken from memory of their docs: **unverified on real compositors** |
| Bluetooth: power, scan, connect/disconnect | works with stub `bluetoothctl` | not tried with hardware |
| Packages: search (repo + AUR), details, install, remove, updates, update system, installed list | works with stub `pacman`/`pkexec`/`paru` | live log streamed, back blocked while running, confirm page first. Real `pacman` binary (Ubuntu build) was used only for empty-database checks. **No real package was installed.** |
| Packages: offline | works | UI shows "Offline", operations refuse with a message, AUR search skipped, no crash |
| Settings: theme (23 palettes), keybindings, startup apps, launcher options, edit config | works | config file verified after each change; "edit config" launches `$EDITOR` in a terminal or `xdg-open` (not exercised) |
| Hotkey: `omamako toggle` over D-Bus, `--daemon`, `quit` | works | installed copy under `dbus-run-session` + Xvfb: shown / hidden / shown / clean exit |
| Hotkey install into Hyprland/Sway/i3 config and removal | works on test files | config left byte-identical after `remove`; not loaded by a real compositor |
| Packaging: wheel build, install to destdir, PKGBUILD `prepare/build/check/package` | works | PKGBUILD functions run in bash with `srcdir/pkgdir`; wheel has 23 themes; installed CLI runs |
| `makepkg` from a clean clone | works | real `makepkg` 6.1.0 (built from source on the Ubuntu host), run as a non-root user with `--nodeps`; `check()` passed, `omamako-0.1.0-1-any.pkg.tar.gz` produced with correct `.PKGINFO` (deps, optdepends, licenses) and `.INSTALL` |
| Install / query / remove the built package | works | real pacman 6.1.0 into a scratch root (`-U -dd --noscriptlet`): 119 files, installed CLI ran, `-Rns` left 0 files. Scriptlets (`.install` hooks) were **not** executed |
| **`makepkg -si` with real dependency resolution** | **NOT RUN** | needs Arch repos (`gtk4`, `python-gobject`, `polkit`, …) and root `pacman -U`; `--nodeps`/`-dd` used instead |
| Installed `.desktop`, systemd units, `/etc/skel` config | files verified present | not loaded by systemd/desktop environment |

## Known issues / limits
* **Unverified on Arch:** dependency resolution during `makepkg -si`, the `.install` scriptlets, real polkit prompt (needs a running polkit agent), real AUR helpers
  (`--sudo pkexec` is an option of paru/yay as I know it), `gtk4-layer-shell` overlay (needs an actual Wayland session;
  if it misbehaves set `launcher.layer_shell = false` or run with `OMAMAKO_NO_LAYER=1`).
* Without layer-shell, Hyprland/Sway/i3 tile the window; add a floating rule (see `INSTALL.md`; Hyprland rule syntax depends on version).
* Wi-Fi connect to a *new secured* network relies on `nmcli --ask` reading the password from stdin.
* AUR operations open a terminal on purpose (PKGBUILD review) and show no in-app log.
* `Hibernate` needs working suspend-to-disk; no check is made.
* Global hotkeys are set up through the compositor; omamako itself never grabs keys (Wayland has no portable way).
* No sandbox, firewall or `PrivateNetwork` is applied anywhere; offline state is only reported.
* Text-only UI (no icons), like Mako's default; single column.
* Not a code merge: neither upstream runs on desktop Linux (see `ANALYSIS.md`).
