# Installing omamako

```sh
makepkg -si          # in this directory; pulls dependencies via pacman
omamako-ctl doctor   # shows which optional tools were found
```
Config lives in `~/.config/omamako/config.toml` (created on first run, also seeded
from `/etc/skel`). State (favorites, recents): `~/.local/state/omamako/`.

## Optional helpers (all degrade gracefully when missing)
`networkmanager` (Wi-Fi), `wireplumber`/`libpulse` (audio), `bluez-utils` (Bluetooth),
`brightnessctl`, `pacman-contrib` (`checkupdates`), `paru` or `yay` (AUR),
`gtk4-layer-shell` (overlay on Wayland), a terminal (`foot`, `kitty`, …) for AUR builds.

## Polkit agent (needed for install/remove/update)
Package changes run `pkexec pacman …`. A polkit **agent** must be running in your session or no
password dialog appears: `hyprpolkitagent` (Hyprland) or `polkit-gnome`
(`/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1`), started from your compositor config.

AUR operations are not run silently: they open a terminal so the helper can show the PKGBUILD for review.

## Hotkey
Wayland compositors own global shortcuts, so omamako gives you a command instead of grabbing keys:
`omamako toggle` (opens, or hides if already open). Default key `SUPER+space`; change it in
*Settings › Keybindings* or `omamako-ctl config set hotkey.key d`.

```sh
omamako-ctl hotkey show        # prints the snippet for your compositor
omamako-ctl hotkey install     # Hyprland/Sway/i3: writes ~/.config/omamako/hotkey.*.conf
                               # and adds one marked include line to your main config
omamako-ctl hotkey remove
```

### Hyprland
```
bind = SUPER, space, exec, omamako toggle
exec-once = omamako --daemon          # resident = instant open (or: systemctl --user enable --now omamako.service)
```
With `gtk4-layer-shell` installed (and `launcher.layer_shell = true`, the default) omamako draws as an
overlay and needs no window rules. Without it, it is a normal window, so make it float
(window-rule syntax differs between Hyprland versions — see the Hyprland wiki for yours), matching class
`dev.omamako.Launcher`.

### Sway
```
bindsym Mod4+space exec omamako toggle
for_window [app_id="dev.omamako.Launcher"] floating enable, border none, move position center
exec omamako --daemon
```
(`hotkey install` writes the first two lines.)

### X11 (i3, bspwm, …)
```
# i3
bindsym Mod4+space exec omamako toggle
exec --no-startup-id omamako --daemon
# sxhkd
super + space
    omamako toggle
```
Find the window class for floating rules with `xprop WM_CLASS` while it is open.
Layer-shell is Wayland-only and is ignored on X11.

## systemd user units
```sh
systemctl --user enable --now omamako.service           # resident launcher
systemctl --user enable --now omamako-startup.service   # launches [startup] apps at login
```
`omamako.service` needs `graphical-session.target` (uwsm, or your session must start it). If your
compositor does not, use `exec-once`/`exec` above instead. The units apply **no** sandboxing, so network
access is never restricted.

## Uninstall
```sh
omamako-ctl cleanup --purge                      # hotkey include, config, favorites (omit --purge to keep config)
systemctl --user disable --now omamako.service omamako-startup.service
sudo pacman -Rns omamako
```
