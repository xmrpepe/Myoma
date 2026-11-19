# Maintainer: omamako contributors
pkgname=omamako
pkgver=0.1.0
pkgrel=1
pkgdesc='Minimal keyboard-driven launcher and system/package menu for Arch Linux (GTK4)'
arch=('any')
url='https://github.com/xmrpepe/Myoma'
license=('GPL-3.0-or-later' 'MIT')   # MIT: Omarchy theme palettes from Omalauncher
depends=('python' 'gtk4' 'python-gobject' 'polkit' 'pacman')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
optdepends=(
  'gtk4-layer-shell: draw as an overlay on Wayland (no window rules needed)'
  'networkmanager: Wi-Fi and network menu'
  'wireplumber: volume control (wpctl)'
  'libpulse: audio output switching (pactl)'
  'bluez-utils: Bluetooth menu (bluetoothctl)'
  'brightnessctl: display brightness'
  'pacman-contrib: checkupdates (safe update check)'
  'paru: AUR support'
  'yay: AUR support (alternative to paru)'
  'hyprpolkitagent: polkit agent for Hyprland'
  'polkit-gnome: polkit agent for other desktops'
  'xdg-utils: open the config file'
)
install=omamako.install
# Build from the checkout this PKGBUILD lives in (no tarball needed).
source=()
sha256sums=()

prepare() {
  rm -rf "$srcdir/$pkgname"
  mkdir -p "$srcdir/$pkgname"
  tar -C "$startdir" --exclude=./src --exclude=./pkg --exclude=./.git \
      --exclude='*.pkg.tar.*' --exclude=__pycache__ -cf - . | tar -C "$srcdir/$pkgname" -xf -
}

build() {
  cd "$srcdir/$pkgname"
  python -m build --wheel --no-isolation
}

check() {
  cd "$srcdir/$pkgname"
  # Backend tests only: they need no display and no Arch tools (they use fakes).
  python -m unittest discover -s tests -p 'test_backend.py'
}

package() {
  cd "$srcdir/$pkgname"
  python -m installer --destdir="$pkgdir" dist/*.whl

  install -Dm644 packaging/dev.omamako.Launcher.desktop \
    "$pkgdir/usr/share/applications/dev.omamako.Launcher.desktop"
  install -Dm644 packaging/dev.omamako.Launcher.svg \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/dev.omamako.Launcher.svg"
  install -Dm644 packaging/omamako.service \
    "$pkgdir/usr/lib/systemd/user/omamako.service"
  install -Dm644 packaging/omamako-startup.service \
    "$pkgdir/usr/lib/systemd/user/omamako-startup.service"
  # Default config: copied to new users' homes; existing users get it on first run.
  install -Dm644 packaging/config.toml "$pkgdir/etc/skel/.config/omamako/config.toml"
  install -Dm644 packaging/config.toml "$pkgdir/usr/share/omamako/config.toml"

  install -Dm644 README.md INSTALL.md TESTING.md ANALYSIS.md -t "$pkgdir/usr/share/doc/$pkgname/"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 LICENSE.omalauncher-MIT "$pkgdir/usr/share/licenses/$pkgname/LICENSE.omalauncher-MIT"
  install -Dm644 THIRD_PARTY.md "$pkgdir/usr/share/licenses/$pkgname/THIRD_PARTY.md"
}
