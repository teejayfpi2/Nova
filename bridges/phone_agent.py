#!/usr/bin/env python3
"""Nova phone agent (Android, via Termux).

Run this *on the phone* (Termux) or point it at a phone reachable over ADB. It
polls the Nova server for commands and executes them locally, so no inbound
ports are needed - the phone can be on mobile data behind a carrier NAT.

Quick start (Termux):
    pkg install python termux-api
    pip install requests
    export NOVA_SERVER=https://your-server:8000
    export NOVA_TOKEN=optional-shared-secret
    python phone_agent.py

Capabilities, and what they need:
    type_text / press_key  -> `termux-api` package (Termux:API app installed)
    send_message           -> termux-sms-send for SMS; WhatsApp via intent
    read_messages          -> termux-sms-list / termux-notification-list
    open_app / open_url    -> termux-open / am start
    screenshot             -> termux-camera-photo (camera) or screencap
    click                  -> termux-touch? not available; use ADB mode instead

For real UI automation (taps at coordinates, reading the screen) run in ADB mode
on a computer with `adb` connected to the phone:
    python phone_agent.py --adb
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

SERVER = os.environ.get("NOVA_SERVER", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("NOVA_TOKEN", "")
DEVICE_NAME = os.environ.get("NOVA_DEVICE_NAME", "phone")
POLL_INTERVAL = float(os.environ.get("NOVA_POLL_INTERVAL", "1.0"))


def api(path: str, payload: dict | None = None) -> dict:
    url = f"{SERVER}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return f"{cmd[0]} timed out"
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.strip() or "ok"


class TermuxBackend:
    """Uses the Termux:API command line tools."""

    def type_text(self, text: str) -> str:
        if has("termux-clipboard-set") and has("termux-keyboard"):
            run(["termux-clipboard-set", text])
            return "Copied to clipboard; paste with a long-press."
        if has("am"):
            # best effort: broadcast text into the focused field is not permitted
            # without an IME, so fall back to the clipboard.
            run(["termux-clipboard-set", text])
            return "Copied to clipboard (install Termux:API for direct typing)."
        return "Cannot type: install termux-api."

    def press_key(self, keys: str) -> str:
        return run(["input", "keyevent", keys.upper()])

    def click(self, x: int, y: int) -> str:
        return run(["input", "tap", str(x), str(y)])

    def screenshot(self, path: str = "/sdcard/nova-shot.png") -> str:
        if has("termux-camera-photo"):
            return run(["termux-camera-photo", "-c", "0", path]) + f" -> {path}"
        if has("screencap"):
            return run(["screencap", "-p", path]) + f" -> {path}"
        return "No screenshot tool."

    def open_app(self, name: str) -> str:
        pkg = APP_PACKAGES.get(name.lower(), name)
        return run(["am", "start", "-n", f"{pkg}/.MainActivity"]) if "." in pkg else run(
            ["termux-open", name]
        )

    def open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if has("termux-open-url"):
            return run(["termux-open-url", url])
        return run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])

    def send_message(self, contact: str, text: str, app: str) -> str:
        if app == "whatsapp":
            return self.open_url(f"https://wa.me/{urllib.parse.quote(contact)}?text={urllib.parse.quote(text)}")
        if has("termux-sms-send"):
            return run(["termux-sms-send", "-n", contact, text])
        return run(["am", "start", "-a", "android.intent.action.SENDTO", "-d", f"sms:{contact}"])

    def read_messages(self, limit: int) -> str:
        if has("termux-sms-list"):
            return run(["termux-sms-list", "-l", str(limit)])
        if has("termux-notification-list"):
            return run(["termux-notification-list"])
        return "Install termux-api to read messages."


class AdbBackend:
    """Uses `adb shell` against a connected phone (full UI control)."""

    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial
        self.prefix = ["adb"] + (["-s", serial] if serial else [])

    def _sh(self, *args: str) -> str:
        return run(self.prefix + ["shell", *args])

    def type_text(self, text: str) -> str:
        escaped = text.replace(" ", "%s")
        return self._sh("input", "text", escaped)

    def press_key(self, keys: str) -> str:
        keymap = {"enter": "66", "back": "4", "home": "3", "volume_up": "24", "volume_down": "25"}
        return self._sh("input", "keyevent", keymap.get(keys.lower(), keys))

    def click(self, x: int, y: int) -> str:
        return self._sh("input", "tap", str(x), str(y))

    def screenshot(self) -> str:
        remote = "/sdcard/nova-shot.png"
        self._sh("screencap", "-p", remote)
        local = f"nova-shot-{int(time.time())}.png"
        run(self.prefix + ["pull", remote, local])
        return local

    def open_app(self, name: str) -> str:
        pkg = APP_PACKAGES.get(name.lower(), name)
        return self._sh(
            "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"
        )

    def open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return self._sh("am", "start", "-a", "android.intent.action.VIEW", "-d", url)

    def send_message(self, contact: str, text: str, app: str) -> str:
        if app == "whatsapp":
            self.open_url(f"https://wa.me/{urllib.parse.quote(contact)}?text={urllib.parse.quote(text)}")
            return "Opened WhatsApp with the message ready."
        self._sh("am", "start", "-a", "android.intent.action.SENDTO", "-d", f"sms:{contact}")
        time.sleep(2)
        self._sh("input", "text", text.replace(" ", "%s"))
        return self._sh("input", "keyevent", "66")

    def read_messages(self, limit: int) -> str:
        return self._sh("dumpsys", "notification", "--noredact")[:4000]


APP_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "telegram": "org.telegram.messenger",
    "signal": "org.thoughtcrime.securesms",
    "chrome": "com.android.chrome",
    "camera": "com.android.camera2",
    "settings": "com.android.settings",
    "youtube": "com.google.android.youtube",
    "maps": "com.google.android.apps.maps",
    "spotify": "com.spotify.music",
    "gmail": "com.google.android.gm",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Nova phone agent")
    parser.add_argument("--adb", action="store_true", help="drive the phone over ADB instead of Termux")
    parser.add_argument("--serial", help="adb device serial")
    args = parser.parse_args()

    backend = AdbBackend(args.serial) if args.adb else TermuxBackend()
    capabilities = ["type_text", "press_key", "click", "screenshot", "open_app", "open_url", "send_message", "read_messages"]

    try:
        api("/api/devices/%s/hello" % DEVICE_NAME, {"capabilities": capabilities})
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not announce to server: {exc}", file=sys.stderr)

    print(f"Nova phone agent connected to {SERVER} as '{DEVICE_NAME}'")
    while True:
        try:
            payload = api("/api/bridge/poll", {"name": DEVICE_NAME, "capabilities": capabilities})
            job = payload.get("job")
            if not job:
                time.sleep(POLL_INTERVAL)
                continue
            action = job["action"]
            fn = getattr(backend, action, None)
            result = fn(**job.get("args", {})) if fn else f"unsupported action: {action}"
            api("/api/bridge/result", {"name": DEVICE_NAME, "id": job["id"], "result": str(result)[:2000]})
        except KeyboardInterrupt:
            print("\nbye")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"poll error: {exc}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
