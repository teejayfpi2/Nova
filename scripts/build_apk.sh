#!/usr/bin/env bash
# Build the Nova Android APK.
#
# Installs a self-contained JDK + Android SDK into $NOVA_ANDROID_HOME (default
# /tmp/android-build) the first time, then builds the app. Nothing system-wide is
# touched, so this works without root.
#
#   ./scripts/build_apk.sh            # debug APK (installable right away)
#   ./scripts/build_apk.sh release    # unsigned release APK
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${NOVA_ANDROID_HOME:-/tmp/android-build}"
JDK_DIR="$BUILD_DIR/jdk-21.0.5+11"
SDK_DIR="$BUILD_DIR/sdk"
GRADLE_DIR="$BUILD_DIR/gradle-8.7"

JDK_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.5%2B11/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
GRADLE_URL="https://services.gradle.org/distributions/gradle-8.7-bin.zip"

extract() {  # extract <zip-or-tar> <dest>
  python3 - "$1" "$2" <<'PY'
import sys, zipfile, tarfile, pathlib
src, dest = sys.argv[1], pathlib.Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
if src.endswith(".zip"):
    zipfile.ZipFile(src).extractall(dest)
else:
    tarfile.open(src).extractall(dest)
PY
}

mkdir -p "$BUILD_DIR"

if [ ! -x "$JDK_DIR/bin/java" ]; then
  echo "==> downloading JDK 21"
  curl -fsSL -o "$BUILD_DIR/jdk.tar.gz" "$JDK_URL"
  extract "$BUILD_DIR/jdk.tar.gz" "$BUILD_DIR"
fi

if [ ! -x "$SDK_DIR/cmdline-tools/latest/bin/sdkmanager" ]; then
  echo "==> downloading Android command-line tools"
  curl -fsSL -o "$BUILD_DIR/cmdline.zip" "$CMDLINE_URL"
  extract "$BUILD_DIR/cmdline.zip" "$SDK_DIR/cmdline-tools"
  mv "$SDK_DIR/cmdline-tools/cmdline-tools" "$SDK_DIR/cmdline-tools/latest"
  chmod +x "$SDK_DIR"/cmdline-tools/latest/bin/*
fi

if [ ! -x "$GRADLE_DIR/bin/gradle" ]; then
  echo "==> downloading Gradle 8.7"
  curl -fsSL -o "$BUILD_DIR/gradle.zip" "$GRADLE_URL"
  extract "$BUILD_DIR/gradle.zip" "$BUILD_DIR"
  chmod +x "$GRADLE_DIR/bin/gradle"
fi

export JAVA_HOME="$JDK_DIR"
export ANDROID_HOME="$SDK_DIR"
export ANDROID_SDK_ROOT="$SDK_DIR"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

echo "==> accepting SDK licenses and installing platforms (first run only)"
yes 2>/dev/null | sdkmanager --licenses >/dev/null 2>&1 || true
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" >/dev/null

echo "sdk.dir=$SDK_DIR" > "$ROOT/android/local.properties"

TASK="assembleDebug"
[ "${1:-}" = "release" ] && TASK="assembleRelease"

echo "==> building ($TASK)"
cd "$ROOT/android"
"$GRADLE_DIR/bin/gradle" "$TASK" --no-daemon

APK=$(find "$ROOT/android/app/build/outputs/apk" -name "*.apk" | head -1)
echo
echo "APK ready: $APK"
echo "Install it with:  adb install -r \"$APK\""
echo "Or copy it to the phone and tap it (allow install from unknown sources)."
