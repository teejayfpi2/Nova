#!/usr/bin/env bash
# Build the Nova desktop (Electron) installers for the current machine.
#
#   ./scripts/build_desktop.sh              # installers for this OS
#   ./scripts/build_desktop.sh --linux      # AppImage + deb
#   ./scripts/build_desktop.sh --win        # NSIS installer + portable exe
#   ./scripts/build_desktop.sh --mac        # dmg + zip
#
# Output lands in desktop/dist/. Cross-compiling is not supported: Windows and
# macOS installers must be built on their own OS (or use the CI workflow).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/desktop"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required. Install Node.js 18+ first." >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "==> installing dependencies"
  npm install
fi

case "${1:-}" in
  --win) PLATFORM="--win" ;;
  --mac) PLATFORM="--mac" ;;
  --linux) PLATFORM="--linux" ;;
  "") PLATFORM="--linux" ;;
  *)
    echo "unknown option: $1 (use --linux, --win or --mac)" >&2
    exit 1
    ;;
esac

echo "==> building Nova desktop installers ($PLATFORM)"
npx electron-builder "$PLATFORM" --publish never

echo
echo "Installers are in: $ROOT/desktop/dist/"
ls -1 dist/*.AppImage dist/*.deb dist/*.exe dist/*.dmg 2>/dev/null || true
