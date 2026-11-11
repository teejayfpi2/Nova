"""Device bridges: how the assistant reaches the laptop and the phone.

Two kinds of bridge:

* :class:`LocalBridge` runs in-process using pyautogui / xdotool, for the machine
  the server itself runs on.
* :class:`RemoteBridge` talks to an agent process running on another machine
  (your phone, or a second laptop) over HTTP. The remote agent polls the server
  for commands, so it works from behind NAT or mobile data without port
  forwarding.
"""

from __future__ import annotations

import subprocess
import threading
import time
import urllib.parse
import urllib.request

from typing import Any

try:  # pyautogui is optional; the local bridge degrades to xdotool
    import pyautogui

    pyautogui.FAILSAFE = False
except Exception:  # noqa: BLE001
    pyautogui = None


class BridgeError(RuntimeError):
    pass


class BaseBridge:
    name = "base"

    def type_text(self, text: str) -> str:
        raise NotImplementedError

    def press_key(self, keys: str) -> str:
        raise NotImplementedError

    def click(self, x: int, y: int) -> str:
        raise NotImplementedError

    def screenshot(self) -> str:
        raise NotImplementedError

    def open_app(self, name: str) -> str:
        raise NotImplementedError

    def open_url(self, url: str) -> str:
        raise NotImplementedError

    def send_message(self, contact: str, text: str, app: str) -> str:
        raise NotImplementedError

    def read_messages(self, limit: int) -> str:
        raise NotImplementedError

    def handle(self, action: str, args: dict[str, Any]) -> str:
        fn = getattr(self, action, None)
        if fn is None:
            raise BridgeError(f"unsupported action: {action}")
        return fn(**args)


class LocalBridge(BaseBridge):
    """Controls the machine the server runs on."""

    def __init__(self, name: str = "laptop") -> None:
        self.name = name

    def type_text(self, text: str) -> str:
        if pyautogui:
            pyautogui.typewrite(text, interval=0.01)
            return "Typed."
        return _xdotool(["type", "--", text])

    def press_key(self, keys: str) -> str:
        combo = [k.strip().replace("cmd", "ctrl").replace("super", "win") for k in keys.split("+")]
        if pyautogui:
            if len(combo) == 1:
                pyautogui.press(combo[0])
            else:
                pyautogui.hotkey(*combo)
            return "Pressed."
        return _xdotool(["key", "+".join(combo)])

    def click(self, x: int, y: int) -> str:
        if pyautogui:
            pyautogui.click(x, y)
            return f"Clicked {x},{y}."
        return _xdotool(["mousemove", str(x), str(y), "click", "1"])

    def screenshot(self) -> str:
        import os

        path = os.path.join(
            os.path.dirname(__file__), "..", "data", f"screenshot-{int(time.time())}.png"
        )
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if pyautogui:
            pyautogui.screenshot(path)
            return path
        try:
            subprocess.run(["import", "-window", "root", path], check=True, timeout=20)
            return path
        except Exception as exc:  # noqa: BLE001
            raise BridgeError(f"screenshot failed: {exc}") from exc

    def open_app(self, name: str) -> str:
        for cmd in (["gtk-launch", name], ["xdg-open", name], ["open", "-a", name]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Opening {name}."
            except FileNotFoundError:
                continue
        raise BridgeError(f"could not open {name}")

    def open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        for cmd in (["xdg-open", url], ["open", url]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Opened {url}."
            except FileNotFoundError:
                continue
        raise BridgeError("could not open a browser")

    def send_message(self, contact: str, text: str, app: str) -> str:
        if app == "imessage":
            url = f"imessage://{urllib.parse.quote(contact)}&body={urllib.parse.quote(text)}"
        elif app == "whatsapp":
            url = f"https://wa.me/{urllib.parse.quote(contact)}?text={urllib.parse.quote(text)}"
        else:
            url = f"sms:{urllib.parse.quote(contact)}?body={urllib.parse.quote(text)}"
        return self.open_url(url)

    def read_messages(self, limit: int) -> str:
        raise BridgeError("reading messages on the laptop is not supported by this bridge")


class RemoteBridge(BaseBridge):
    """Talks to a remote agent that polls the server for work.

    The remote agent is any process that speaks the tiny protocol documented in
    ``bridges/android_agent.py``: it polls ``/api/bridge/poll`` and posts results
    back to ``/api/bridge/result``.
    """

    def __init__(self, name: str, timeout: float = 60.0) -> None:
        self.name = name
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._results: dict[str, str] = {}
        self._queue: list[dict[str, Any]] = []
        self.last_seen = 0.0
        self.capabilities: list[str] = []

    # -- called by the HTTP layer ----------------------------------------
    def enqueue(self, action: str, args: dict[str, Any]) -> str:
        job_id = f"{action}-{int(time.time() * 1000)}-{len(self._queue)}"
        with self._lock:
            self._queue.append({"id": job_id, "action": action, "args": args})
        return job_id

    def next_job(self) -> dict[str, Any] | None:
        with self._lock:
            self.last_seen = time.time()
            if self._queue:
                return self._queue.pop(0)
            return None

    def submit_result(self, job_id: str, result: str) -> None:
        with self._lock:
            self._results[job_id] = result
            self.last_seen = time.time()

    def hello(self, capabilities: list[str] | None = None) -> None:
        with self._lock:
            self.last_seen = time.time()
            if capabilities is not None:
                self.capabilities = capabilities

    # -- called by tools -------------------------------------------------
    def _run(self, action: str, args: dict[str, Any]) -> str:
        job_id = self.enqueue(action, args)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            with self._lock:
                if job_id in self._results:
                    return self._results.pop(job_id)
            time.sleep(0.2)
        raise BridgeError(
            f"{self.name} did not respond within {self.timeout:.0f}s "
            "(is the agent running and online?)"
        )

    def type_text(self, text: str) -> str:
        return self._run("type_text", {"text": text})

    def press_key(self, keys: str) -> str:
        return self._run("press_key", {"keys": keys})

    def click(self, x: int, y: int) -> str:
        return self._run("click", {"x": x, "y": y})

    def screenshot(self) -> str:
        return self._run("screenshot", {})

    def open_app(self, name: str) -> str:
        return self._run("open_app", {"name": name})

    def open_url(self, url: str) -> str:
        return self._run("open_url", {"url": url})

    def send_message(self, contact: str, text: str, app: str) -> str:
        return self._run("send_message", {"contact": contact, "text": text, "app": app})

    def read_messages(self, limit: int) -> str:
        return self._run("read_messages", {"limit": limit})

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < 30 if self.last_seen else False


def _xdotool(args: list[str]) -> str:
    try:
        subprocess.run(["xdotool", *args], check=True, timeout=15)
        return "Done."
    except FileNotFoundError as exc:
        raise BridgeError("xdotool is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise BridgeError(f"xdotool failed: {exc}") from exc


class BridgeRegistry:
    """Holds the connected bridges and exposes them to tools."""

    def __init__(self) -> None:
        self._bridges: dict[str, BaseBridge] = {}
        self._lock = threading.Lock()

    def register(self, name: str, bridge: BaseBridge) -> None:
        with self._lock:
            self._bridges[name] = bridge

    def get(self, name: str) -> BaseBridge | None:
        with self._lock:
            return self._bridges.get(name)

    def as_dict(self) -> dict[str, BaseBridge]:
        with self._lock:
            return dict(self._bridges)

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, bridge in self.as_dict().items():
            if isinstance(bridge, RemoteBridge):
                out[name] = {
                    "type": "remote",
                    "online": bridge.online,
                    "capabilities": bridge.capabilities,
                }
            else:
                out[name] = {"type": "local", "online": True}
        return out


REGISTRY = BridgeRegistry()
