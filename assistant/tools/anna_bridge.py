"""Anna Strategic Operations Bridge for Nova.

Lets Nova delegate complex, multi-step cloud tasks to a remote agent
endpoint (the "Strategic Operations Center") over a small JSON HTTP API.

Nothing is enabled until you configure it: set ``NOVA_ANNA_URL`` to the
endpoint's task-launch URL and ``NOVA_ANNA_API_KEY`` to a bearer token.
Without both, the tools stay in "Local-Only" mode and say so.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import ToolContext, tool

# Upper bound on the HTTP wait, kept below the agent loop's patience.
_MAX_WAIT = 600


def _config() -> tuple[str, str]:
    """Read endpoint config at call time so env changes take effect live."""
    url = os.environ.get("NOVA_ANNA_URL", "").strip()
    key = os.environ.get("NOVA_ANNA_API_KEY", "").strip()
    return url, key


def _not_configured() -> str:
    return (
        "Anna is in 'Local-Only' mode. Set NOVA_ANNA_URL and NOVA_ANNA_API_KEY "
        "to enable cloud delegation to the Strategic Operations Center."
    )


@tool(dangerous=True)
def delegate_to_anna(
    task: str,
    background: str = "",
    wait_seconds: int = 300,
    ctx: ToolContext = None,
) -> str:
    """Delegate a complex cloud task to Anna (Strategic Operations Center).

    Use this for high-level research, document generation (PDF/PPTX),
    advanced web automation (Talent Browser), or long-running analysis.

    task: The detailed description of the task for Anna.
    background: Optional background info or data to help Anna.
    wait_seconds: How long to wait for a direct result before returning a job ID.
    """
    url, key = _config()
    if not url or not key:
        return _not_configured()

    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return f"Anna endpoint must be an http(s) URL, got: {url!r}"

    wait = max(1, min(int(wait_seconds), _MAX_WAIT))
    payload = {"task": task, "context": background, "timeout": wait}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Nova-Assistant/1.0 (+https://github.com/teejayfpi2/Nova)",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=wait + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        return f"Anna endpoint returned HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        return f"Could not reach Anna Strategic Operations Center: {exc}"

    if not isinstance(data, dict):
        return f"Anna returned an unexpected response: {str(data)[:300]}"

    if data.get("status") == "completed":
        return f"Anna completed the task:\n\n{data.get('result', '(no summary)')}"

    agent_id = data.get("agent_id") or data.get("id") or "(unknown)"
    return f"Anna is working in the background (Agent ID: {agent_id}). Check progress later."


@tool(dangerous=True)
def generate_presentation(topic: str, slide_count: int = 5, ctx: ToolContext = None) -> str:
    """Ask Anna to generate a professional PowerPoint presentation.

    topic: The subject of the presentation.
    slide_count: Target number of slides.
    """
    task = (
        f"Generate a professional PowerPoint presentation on the topic: {topic}. "
        f"Target {slide_count} slides."
    )
    return delegate_to_anna(task, ctx=ctx)


@tool(dangerous=True)
def web_automation_task(instruction: str, url: str = "", ctx: ToolContext = None) -> str:
    """Delegate a complex web automation or scraping task to Anna's Talent Browser.

    instruction: What to do or find on the web.
    url: Initial URL to start from.
    """
    task = f"Use Talent Browser to perform this task: {instruction}. Start at: {url}"
    return delegate_to_anna(task, ctx=ctx)
