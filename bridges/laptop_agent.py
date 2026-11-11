#!/usr/bin/env python3
"""Nova laptop agent.

Runs on a second computer and lets the Nova server control it: typing, keys,
clicks, screenshots, opening apps and URLs. Like the phone agent it polls the
server, so it works from anywhere without port forwarding.

    pip install pyautogui requests
    export NOVA_SERVER=https://your-server:8000
    python laptop_agent.py
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
DEVICE_NAME = os.environ.get("NOVA_DEVICE_NAME", "desktop")
POLL_INTERVAL = float(os.environ.get("NOVA_POLL_INTERVAL", "1.0"))

try:
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:  # noqa: BLE001
    pyautogui = None


def api(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(
        f"{SERVER}{path}", data=data, headers=headers, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return f"{cmd[0]} not installed"
    return ((proc.stdout or "") + (proc.stderr or "")).strip() or "ok"


class LaptopBackend:
    def type_text(self, text: str) -> str:
        if pyautogui:
            pyautogui.typewrite(text, interval=0.01)
            return "typed"
        return sh(["xdotool", "type", "--", text])

    def press_key(self, keys: str) -> str:
        combo = [k.strip().replace("cmd", "ctrl") for k in keys.split("+")]
        if pyautogui:
            pyautogui.hotkey(*combo) if len(combo) > 1 else pyautogui.press(combo[0])
            return "pressed"
        return sh(["xdotool", "key", "+".join(combo)])

    def click(self, x: int, y: int) -> str:
        if pyautogui:
            pyautogui.click(x, y)
            return f"clicked {x},{y}"
        return sh(["xdotool", "mousemove", str(x), str(y), "click", "1"])

    def screenshot(self) -> str:
        path = f"nova-shot-{int(time.time())}.png"
        if pyautogui:
            pyautogui.screenshot(path)
            return path
        return sh(["import", "-window", "root", path])

    def open_app(self, name: str) -> str:
        for cmd in (["gtk-launch", name], ["xdg-open", name], ["open", "-a", name]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"opened {name}"
        return f"could not open {name}"

    def open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        for cmd in (["xdg-open", url], ["open", url]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"opened {url}"
        return "no browser opener found"

    def send_message(self, contact: str, text: str, app: str) -> str:
        if app == "whatsapp":
            return self.open_url(f"https://wa.me/{urllib.parse.quote(contact)}?text={urllib.parse.quote(text)}")
        if app == "telegram":
            return self.open_url(f"https://t.me/{urllib.parse.quote(contact)}")
        return self.open_url(f"sms:{urllib.parse.quote(contact)}?body={urllib.parse.quote(text)}")

    def read_messages(self, limit: int) -> str:
        return "reading messages is only supported on the phone agent"


def main() -> int:
    parser = argparse.ArgumentParser(description="Nova laptop agent")
    parser.parse_args()

    backend = LaptopBackend()
    capabilities = ["type_text", "press_key", "click", "screenshot", "open_app", "open_url", "send_message"]
    try:
        api(f"/api/devices/{DEVICE_NAME}/hello", {"capabilities": capabilities})
    except Exception as exc:  # noqa: BLE001
        print(f"warning: {exc}", file=sys.stderr)

    print(f"Nova laptop agent connected to {SERVER} as '{DEVICE_NAME}'")
    while True:
        try:
            job = api("/api/bridge/poll", {"name": DEVICE_NAME, "capabilities": capabilities}).get("job")
            if not job:
                time.sleep(POLL_INTERVAL)
                continue
            fn = getattr(backend, job["action"], None)
            result = fn(**job.get("args", {})) if fn else f"unsupported action: {job['action']}"
            api("/api/bridge/result", {"name": DEVICE_NAME, "id": job["id"], "result": str(result)[:2000]})
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"poll error: {exc}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
