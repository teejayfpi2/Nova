"""Built-in tools the assistant can call.

Device-level tools (typing, clicking, apps, messages) route to a *bridge*: a
controller for the laptop or the phone. When no bridge is connected they fall
back to running locally, which is exactly what you want when the assistant runs
on the same machine it controls.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

from . import ToolContext, tool


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------
@tool
def remember(key: str, value: str, ctx: ToolContext = None) -> str:
    """Save a durable fact about the user (name, preferences, birthdays, ...).

    key: short label, e.g. "user_name" or "favourite_coffee"
    value: the fact itself
    """
    ctx.memory.remember(key, value)
    return f"Remembered: {key} = {value}"


@tool
def recall(query: str = "", ctx: ToolContext = None) -> str:
    """Search stored facts. Leave query empty to list everything known.

    query: text to search for in fact keys and values
    """
    facts = ctx.memory.facts(query or None)
    if not facts:
        return "I don't have anything stored for that."
    return "\n".join(f"{f['key']}: {f['value']}" for f in facts)


@tool
def forget(key: str, ctx: ToolContext = None) -> str:
    """Delete a stored fact.

    key: the label to delete
    """
    return "Deleted." if ctx.memory.forget(key) else "No such fact."


# --------------------------------------------------------------------------
# about the builder
# --------------------------------------------------------------------------
@tool
def about_builder() -> str:
    """Report who built Nova: name, role, email, phone and LinkedIn."""
    from ..identity import builder_block

    return builder_block()


# --------------------------------------------------------------------------
# notes / todos
# --------------------------------------------------------------------------
@tool
def add_note(body: str, tags: str = "", ctx: ToolContext = None) -> str:
    """Save a free-form note.

    body: the note text
    tags: optional comma-separated tags
    """
    nid = ctx.memory.add_note(body, tags)
    return f"Note saved as #{nid}."


@tool
def list_notes(query: str = "", ctx: ToolContext = None) -> str:
    """List or search notes.

    query: optional search text
    """
    notes = ctx.memory.notes(query or None)
    if not notes:
        return "No notes."
    return "\n".join(f"#{n['id']} {n['body']}" for n in notes)


@tool
def add_todo(body: str, ctx: ToolContext = None) -> str:
    """Add an item to the to-do list.

    body: what needs doing
    """
    tid = ctx.memory.add_todo(body)
    return f"Todo #{tid} added."


@tool
def list_todos(ctx: ToolContext = None) -> str:
    """List open to-do items."""
    todos = ctx.memory.todos()
    if not todos:
        return "Nothing on the list."
    return "\n".join(f"#{t['id']} {t['body']}" for t in todos)


@tool
def complete_todo(id: int, ctx: ToolContext = None) -> str:
    """Mark a to-do as done.

    id: the todo number
    """
    return "Done." if ctx.memory.complete_todo(id) else "No such todo."


# --------------------------------------------------------------------------
# reminders
# --------------------------------------------------------------------------
@tool
def set_reminder(body: str, when: str, repeat: str = "none", ctx: ToolContext = None) -> str:
    """Create a reminder.

    body: what to be reminded about
    when: natural time, e.g. "in 10 minutes", "tomorrow at 9am", "2026-05-01 08:00"
    repeat: none, daily, weekly or monthly
    """
    try:
        due = parse_when(when)
    except ValueError as exc:
        return f"Could not understand the time '{when}': {exc}"
    rid = ctx.memory.add_reminder(body, due, repeat)
    stamp = time.strftime("%a %d %b %H:%M", time.localtime(due))
    return f"Reminder #{rid} set for {stamp}."


@tool
def list_reminders(ctx: ToolContext = None) -> str:
    """List pending reminders."""
    rem = ctx.memory.reminders()
    if not rem:
        return "No reminders."
    return "\n".join(f"#{r.id} {r.body} - {r.to_dict()['due_iso']}" for r in rem)


@tool
def complete_reminder(id: int, ctx: ToolContext = None) -> str:
    """Complete or dismiss a reminder.

    id: the reminder number
    """
    return "Completed." if ctx.memory.complete_reminder(id) else "No such reminder."


# --------------------------------------------------------------------------
# time / web
# --------------------------------------------------------------------------
@tool
def current_time(timezone: str = "") -> str:
    """Get the current date and time.

    timezone: optional IANA name such as "Europe/London"
    """
    try:
        if timezone:
            from zoneinfo import ZoneInfo

            now = time.time()
            tz = ZoneInfo(timezone)
            return time.strftime("%A %d %B %Y, %H:%M %Z", time.localtime(now)) + f" ({tz})"
    except Exception:  # noqa: BLE001 - fall back to local time
        pass
    return time.strftime("%A %d %B %Y, %H:%M %Z")


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return titles, URLs and snippets.

    query: the search query
    max_results: how many results to return
    """
    return _duckduckgo_search(query, max_results)


@tool
def fetch_page(url: str, max_chars: int = 6000) -> str:
    """Download a web page and return its readable text.

    url: the page to fetch
    max_chars: truncate the text to this many characters
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Nova"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode(errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"Failed to fetch {url}: {exc}"
    text = _strip_html(raw)
    return text[:max_chars]


# --------------------------------------------------------------------------
# device control - routed through bridges when present
# --------------------------------------------------------------------------
def _device(ctx: ToolContext, target: str) -> Any:
    return ctx.bridge(target) if ctx else None


@tool
def type_text(text: str, target: str = "laptop", ctx: ToolContext = None) -> str:
    """Type text into whatever is focused on the device.

    text: the text to type
    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.type_text(text)
    if target == "laptop":
        return _local_type(text)
    return f"No {target} bridge connected."


@tool
def press_key(keys: str, target: str = "laptop", ctx: ToolContext = None) -> str:
    """Press a key or keyboard shortcut.

    keys: e.g. "enter", "ctrl+s", "cmd+space"
    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.press_key(keys)
    if target == "laptop":
        return _local_press(keys)
    return f"No {target} bridge connected."


@tool
def click_at(x: int, y: int, target: str = "laptop", ctx: ToolContext = None) -> str:
    """Move the mouse and click at screen coordinates.

    x: horizontal pixel
    y: vertical pixel
    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.click(x, y)
    if target == "laptop":
        return _local_click(x, y)
    return f"No {target} bridge connected."


@tool
def screenshot(target: str = "laptop", ctx: ToolContext = None) -> str:
    """Take a screenshot and save it, returning the file path.

    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.screenshot()
    if target == "laptop":
        return _local_screenshot()
    return f"No {target} bridge connected."


@tool
def open_app(name: str, target: str = "laptop", ctx: ToolContext = None) -> str:
    """Open an application by name.

    name: application name, e.g. "spotify", "chrome", "whatsapp"
    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.open_app(name)
    if target == "laptop":
        return _local_open_app(name)
    return f"No {target} bridge connected."


@tool
def open_url(url: str, target: str = "laptop", ctx: ToolContext = None) -> str:
    """Open a URL in the default browser.

    url: the address to open
    target: "laptop" or "phone"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.open_url(url)
    if target == "laptop":
        return _local_open_url(url)
    return f"No {target} bridge connected."


@tool
def send_message(
    contact: str, text: str, app: str = "sms", target: str = "phone", ctx: ToolContext = None
) -> str:
    """Send a message to a contact through a messaging app.

    contact: name or phone number
    text: message body
    app: sms, whatsapp, telegram, signal, imessage
    target: "phone" (default) or "laptop"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.send_message(contact, text, app)
    return f"No {target} bridge connected, so I cannot send that message."


@tool
def read_messages(limit: int = 5, target: str = "phone", ctx: ToolContext = None) -> str:
    """Read the most recent messages/notifications from the device.

    limit: how many to return
    target: "phone" or "laptop"
    """
    dev = _device(ctx, target)
    if dev is not None:
        return dev.read_messages(limit)
    return f"No {target} bridge connected."


@tool
def clipboard(action: str = "get", text: str = "", ctx: ToolContext = None) -> str:
    """Read or write the clipboard.

    action: "get" or "set"
    text: text to copy when action is "set"
    """
    if action == "get":
        for cmd in (["xclip", "-selection", "clipboard", "-o"], ["pbpaste"]):
            try:
                return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
            except FileNotFoundError:
                continue
        return "No clipboard tool available."
    for cmd in (["xclip", "-selection", "clipboard"], ["pbcopy"]):
        try:
            subprocess.run(cmd, input=text, text=True, timeout=5, check=True)
            return "Copied."
        except FileNotFoundError:
            continue
    return "No clipboard tool available."


@tool
def notify(title: str, message: str) -> str:
    """Show a desktop notification.

    title: notification title
    message: notification body
    """
    try:
        subprocess.run(["notify-send", title, message], timeout=5, check=False)
        return "Notification shown."
    except FileNotFoundError:
        return "notify-send is not installed."


# --------------------------------------------------------------------------
# code / shell
# --------------------------------------------------------------------------
@tool(dangerous=True)
def run_shell(command: str, timeout: int = 60, ctx: ToolContext = None) -> str:
    """Run a shell command on this computer and return its output.

    command: the shell command line
    timeout: seconds before the command is killed
    """
    if ctx and not ctx.settings.shell_enabled:
        return "Shell access is disabled in settings."
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    out = (proc.stdout or "") + (proc.stderr or "")
    return out[-4000:] or f"(no output, exit {proc.returncode})"


@tool(dangerous=True)
def run_python(code: str) -> str:
    """Execute a snippet of Python and return printed output.

    code: the Python source to run
    """
    buf = io.StringIO()
    import contextlib

    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {"__name__": "__main__"})  # noqa: S102 - intended feature
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return buf.getvalue()[-4000:] or "(no output)"


# --------------------------------------------------------------------------
# OpenHands superpowers
# --------------------------------------------------------------------------
def _openhands(ctx: ToolContext):
    from ..openhands import OpenHandsClient

    client = OpenHandsClient()
    if not client.configured:
        return None, (
            "OpenHands is not configured. Set NOVA_OPENHANDS_URL and "
            "NOVA_OPENHANDS_SESSION_KEY to enable autonomous task delegation."
        )
    return client, ""


@tool(dangerous=True)
def delegate_task(task: str, wait_seconds: int = 240, ctx: ToolContext = None) -> str:
    """Hand a whole job to an autonomous OpenHands agent that can use a terminal,
    edit files, browse the web and run code, then report the result.

    Use this for multi-step work a chat model cannot do alone: clone and build a
    repo, run tests and fix them, install packages, refactor code, scrape a site,
    or research something across many pages. The agent works in its own sandbox.

    task: a complete, self-contained description of what to accomplish
    wait_seconds: how long to wait for the job before returning a job id to poll
    """
    client, err = _openhands(ctx)
    if client is None:
        return err
    try:
        cid = client.start_task(task)
    except Exception as exc:  # noqa: BLE001
        return f"could not start OpenHands task: {exc}"
    result = client.wait(cid, timeout=float(max(5, wait_seconds)))
    if result.finished:
        body = result.response or "(the agent finished without a written summary)"
        return f"OpenHands finished the task.\n\n{body}"
    return (
        f"OpenHands is still working (job id {cid}). "
        f"Ask me to check on it with check_task."
    )


@tool
def check_task(job_id: str, ctx: ToolContext = None) -> str:
    """Check the status and result of a previously delegated OpenHands task.

    job_id: the id returned by delegate_task
    """
    client, err = _openhands(ctx)
    if client is None:
        return err
    try:
        result = client.status(job_id)
    except Exception as exc:  # noqa: BLE001
        return f"could not check task: {exc}"
    if result.finished:
        return f"Task {job_id} is {result.status}.\n\n{result.response or '(no summary)'}"
    return f"Task {job_id} is still {result.status}."


@tool(dangerous=True)
def research_topic(topic: str, depth: str = "standard", ctx: ToolContext = None) -> str:
    """Do deep, multi-source research and return a written brief with sources.

    Use this instead of web_search when the user wants a thorough answer that
    needs reading several pages and synthesising them.

    topic: what to research, as a full question or brief
    depth: "quick" for a short answer, "standard" or "deep" for a full brief
    """
    client, err = _openhands(ctx)
    if client is None:
        return err
    style = {
        "quick": "Keep it under 150 words with the key facts only.",
        "standard": "Write a concise brief with a short summary, the key points, and sources.",
        "deep": (
            "Write a thorough brief: executive summary, detailed findings with "
            "figures, caveats, and a full source list."
        ),
    }.get(depth, "Write a concise brief with a short summary, key points, and sources.")
    task = (
        f"Research this and report back in the chat: {topic}\n\n{style}\n"
        "Use web search and read the actual pages. Cite the URLs you used."
    )
    try:
        result = client.run_task(task, timeout=600.0)
    except Exception as exc:  # noqa: BLE001
        return f"research failed: {exc}"
    return result.response or "The research agent finished without a written summary."


@tool(dangerous=True)
def build_software(spec: str, wait_seconds: int = 300, ctx: ToolContext = None) -> str:
    """Write, run and test real software from a plain-English description.

    The OpenHands agent creates the files, installs what it needs, runs the code
    and iterates until it works, then reports back with the result.

    spec: what to build, in plain English, including the language if you care
    wait_seconds: how long to wait before returning a job id to poll
    """
    client, err = _openhands(ctx)
    if client is None:
        return err
    task = (
        f"Build this and verify it actually runs:\n\n{spec}\n\n"
        "Create the files in the working directory, install dependencies, run it, "
        "fix any errors, and finish by telling me exactly how to use it."
    )
    try:
        cid = client.start_task(task)
    except Exception as exc:  # noqa: BLE001
        return f"could not start the build: {exc}"
    result = client.wait(cid, timeout=float(max(5, wait_seconds)))
    if result.finished:
        return f"Build finished.\n\n{result.response or '(no summary)'}"
    return f"Still building (job id {cid}). Ask me to check_task on it."


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
_REL = re.compile(r"^in\s+(\d+)\s*(second|sec|minute|min|hour|day|week)s?$", re.I)


def parse_when(text: str, now: float | None = None) -> float:
    """Parse a natural-language time expression into a unix timestamp."""
    now = now or time.time()
    text = text.strip().lower()

    m = _REL.match(text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        factor = {
            "second": 1,
            "sec": 1,
            "minute": 60,
            "min": 60,
            "hour": 3600,
            "day": 86400,
            "week": 604800,
        }[unit]
        return now + amount * factor

    # explicit formats
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue

    # "today/tomorrow/tonight at 9", "at 09:30", "9am", "18:00"
    day_offset = 0
    rest = text
    if rest.startswith("tomorrow"):
        day_offset = 1
        rest = rest[len("tomorrow") :].strip()
    elif rest.startswith("today") or rest.startswith("tonight"):
        rest = rest.split(" ", 1)[1] if " " in rest else ""
    rest = rest.replace("at", " ").strip()

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", rest)
    if not m:
        raise ValueError("unsupported time format")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0

    base = time.localtime(now + day_offset * 86400)
    target = time.mktime(
        (base.tm_year, base.tm_mon, base.tm_mday, hour, minute, 0, 0, 0, -1)
    )
    if target < now and day_offset == 0:
        target += 86400
    return target


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _duckduckgo_search(query: str, max_results: int) -> str:
    """Search DuckDuckGo's lightweight HTML endpoint.

    The full html.duckduckgo.com endpoint serves an anti-bot page to plain
    clients, so the lite endpoint is used first with a browser user agent.
    """
    ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
    for endpoint in ("https://lite.duckduckgo.com/lite/", "https://html.duckduckgo.com/html/"):
        url = endpoint + "?" + urllib.parse.urlencode({"q": query})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = resp.read().decode(errors="replace")
        except Exception:  # noqa: BLE001 - try the next endpoint
            continue

        results = _parse_ddg(page, max_results)
        if results:
            return "\n".join(results)
    return "No results found."


def _parse_ddg(page: str, max_results: int) -> list[str]:
    # lite markup: <a ... href="//duckduckgo.com/l/?uddg=ENCODED" class='result-link'>Title</a>
    links = re.findall(
        r'<a[^>]+href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>', page, re.S
    )
    if not links:
        links = re.findall(
            r'<a[^>]+class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S
        )
    snippets = re.findall(r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>', page, re.S)
    if not snippets:
        snippets = re.findall(r'class=[\'"]result__snippet[\'"][^>]*>(.*?)</a>', page, re.S)

    out: list[str] = []
    for i, (href, title_html) in enumerate(links[:max_results]):
        title = _strip_html(title_html)
        link = _clean_ddg_link(href)
        snip = _strip_html(snippets[i]) if i < len(snippets) else ""
        out.append(f"{i + 1}. {title}\n   {link}\n   {snip[:300]}")
    return out


def _clean_ddg_link(href: str) -> str:
    href = html.unescape(href)
    if "uddg=" in href:
        query = urllib.parse.urlparse(href).query
        target = urllib.parse.parse_qs(query).get("uddg", [""])[0]
        if target:
            return target
    return href


# ---------- local device fallbacks (pyautogui / xdotool) ----------
def _local_type(text: str) -> str:
    try:
        import pyautogui

        pyautogui.typewrite(text, interval=0.01)
        return "Typed."
    except Exception:  # noqa: BLE001
        try:
            subprocess.run(["xdotool", "type", "--", text], timeout=10, check=True)
            return "Typed."
        except Exception as exc:  # noqa: BLE001
            return f"Cannot type locally: {exc}"


def _local_press(keys: str) -> str:
    combo = [k.strip() for k in keys.replace("cmd", "ctrl").split("+")]
    try:
        import pyautogui

        if len(combo) == 1:
            pyautogui.press(combo[0])
        else:
            pyautogui.hotkey(*combo)
        return "Pressed."
    except Exception:  # noqa: BLE001
        try:
            subprocess.run(["xdotool", "key", "+".join(combo)], timeout=10, check=True)
            return "Pressed."
        except Exception as exc:  # noqa: BLE001
            return f"Cannot press keys locally: {exc}"


def _local_click(x: int, y: int) -> str:
    try:
        import pyautogui

        pyautogui.click(x, y)
        return f"Clicked {x},{y}."
    except Exception:  # noqa: BLE001
        try:
            subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], timeout=10, check=True)
            return f"Clicked {x},{y}."
        except Exception as exc:  # noqa: BLE001
            return f"Cannot click locally: {exc}"


def _local_screenshot() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", f"screenshot-{int(time.time())}.png")
    path = os.path.abspath(path)
    try:
        import pyautogui

        pyautogui.screenshot(path)
        return path
    except Exception:  # noqa: BLE001
        try:
            subprocess.run(["import", "-window", "root", path], timeout=15, check=True)
            return path
        except Exception as exc:  # noqa: BLE001
            return f"Cannot screenshot locally: {exc}"


def _local_open_app(name: str) -> str:
    for cmd in (["gtk-launch", name], ["xdg-open", name], ["open", "-a", name]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opening {name}."
        except FileNotFoundError:
            continue
    return f"Could not find a way to open {name}."


def _local_open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    for cmd in (["xdg-open", url], ["open", url]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opened {url}."
        except FileNotFoundError:
            continue
    return "Could not open a browser."


def json_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
