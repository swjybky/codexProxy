#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/dist/CodexProxy"
VERSION="${VERSION:-$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$ROOT/web/package.json" | head -n 1)}"
ARCH="${ARCH:-$(dpkg --print-architecture)}"
PACKAGE_NAME="codex-proxy"
STAGE="$ROOT/build/deb/${PACKAGE_NAME}_${VERSION}_${ARCH}"
OUTPUT="$ROOT/dist/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

if [[ "${SKIP_APP_BUILD:-0}" != "1" ]]; then
    "$ROOT/packaging/build_linux.sh"
fi

if [[ ! -x "$APP_DIR/CodexProxy" ]]; then
    echo "Missing Linux application bundle: $APP_DIR" >&2
    exit 1
fi

ICON_SRC="$ROOT/packaging/icons/app-icon.png"
ICON_SIZES=(16 22 24 32 48 64 128 256 512 1024)

rm -rf "$STAGE"
install -d \
    "$STAGE/DEBIAN" \
    "$STAGE/opt/codex-proxy" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/doc/codex-proxy"

cp -a "$APP_DIR/." "$STAGE/opt/codex-proxy/"
ln -s /opt/codex-proxy/CodexProxy "$STAGE/usr/bin/codex-proxy"
install -m 0644 "$ROOT/packaging/codex-proxy.desktop" \
    "$STAGE/usr/share/applications/codex-proxy.desktop"
install -m 0644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/codex-proxy/copyright"

if command -v convert >/dev/null 2>&1; then
    for size in "${ICON_SIZES[@]}"; do
        install -d "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
        convert "$ICON_SRC" -resize "${size}x${size}" \
            "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/codex-proxy.png"
    done
else
    echo "ImageMagick convert is required to build hicolor icons." >&2
    exit 1
fi

install -m 0755 "$ROOT/packaging/deb-postinst.sh" "$STAGE/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/deb-postrm.sh" "$STAGE/DEBIAN/postrm"

INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: devel
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE
Depends: libc6, libdbus-1-3, libegl1, libfontconfig1, libgl1, libglib2.0-0, libnss3, libx11-6, libxcb1, libxkbcommon0
Maintainer: Codex Proxy
Description: Local desktop reverse proxy for Codex Responses API
 Codex Proxy adapts OpenAI Responses API requests to the Codex backend and
 provides a local desktop interface for credentials and proxy settings.
EOF

chmod 0755 "$STAGE/DEBIAN"
chmod 0644 "$STAGE/DEBIAN/control"
dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"

echo "Ubuntu package complete: $OUTPUT"
