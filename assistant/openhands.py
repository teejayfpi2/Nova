"""OpenHands integration: LLM provider plus autonomous task delegation.

Two capabilities, both optional and off unless configured:

1. **OpenHands as the brain.** Point Nova at an OpenHands agent server
   (``NOVA_LLM_BASE_URL`` + ``NOVA_LLM_HEADERS``) or at the OpenHands Cloud LLM
   proxy with a managed key. Nova then uses OpenHands' models for its own
   tool-calling loop.

2. **OpenHands as a superpower.** ``delegate_task`` hands a whole job to a real
   OpenHands agent running in a sandbox with a terminal, file editor, browser
   and code execution. Nova stays responsive while that runs in the background,
   then reports back. This is what lets Nova do things a plain chatbot cannot:
   clone a repo, run tests, build an APK, drive a browser, refactor code.

The delegation API is documented in the ``openhands-api`` skill.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class OpenHandsError(RuntimeError):
    pass


@dataclass
class DelegationResult:
    conversation_id: str
    status: str
    response: str
    events: int = 0
    url: str = ""

    @property
    def finished(self) -> bool:
        return self.status in {"finished", "error", "stuck"}


DEFAULT_TOOLS = [
    {"name": "terminal"},
    {"name": "file_editor"},
    {"name": "task_tracker"},
]


@dataclass
class OpenHandsClient:
    """Minimal client for an OpenHands agent server.

    Works with a local agent server (``http://127.0.0.1:60000``) and with a
    sandbox obtained from OpenHands Cloud: in both cases you need the base URL
    and the session API key.
    """

    base_url: str = field(
        default_factory=lambda: os.environ.get("NOVA_OPENHANDS_URL", "").rstrip("/")
    )
    session_key: str = field(
        default_factory=lambda: os.environ.get("NOVA_OPENHANDS_SESSION_KEY", "")
    )
    default_model: str = field(
        default_factory=lambda: os.environ.get("NOVA_OPENHANDS_MODEL", "openhands_Default")
    )
    working_dir: str = field(
        default_factory=lambda: os.environ.get("NOVA_OPENHANDS_WORKDIR", "/workspace")
    )
    timeout: float = field(
        default_factory=lambda: float(os.environ.get("NOVA_OPENHANDS_TIMEOUT", "60"))
    )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.session_key)

    # -- transport --------------------------------------------------------
    def _request(self, method: str, path: str, body: dict[str, Any] | None = None,
                 timeout: float | None = None) -> Any:
        if not self.configured:
            raise OpenHandsError(
                "OpenHands is not configured. Set NOVA_OPENHANDS_URL and "
                "NOVA_OPENHANDS_SESSION_KEY."
            )
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "X-Session-API-Key": self.session_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise OpenHandsError(f"OpenHands HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise OpenHandsError(f"OpenHands request failed: {exc}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    # -- high level -------------------------------------------------------
    def start_task(
        self,
        task: str,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        working_dir: str | None = None,
    ) -> str:
        """Start an autonomous OpenHands conversation. Returns its id."""
        payload = {
            "agent": {
                "kind": "Agent",
                "llm": {"model": model or self.default_model},
                "tools": tools or DEFAULT_TOOLS,
            },
            "workspace": {
                "kind": "LocalWorkspace",
                "working_dir": working_dir or self.working_dir,
            },
            "initial_message": {
                "content": [{"type": "text", "text": task}],
                "run": True,
            },
        }
        result = self._request("POST", "/api/conversations", payload, timeout=90)
        cid = result.get("id") or result.get("conversation_id")
        if not cid:
            raise OpenHandsError(f"no conversation id in response: {result}")
        return str(cid)

    def status(self, conversation_id: str) -> DelegationResult:
        info = self._request("GET", f"/api/conversations/{conversation_id}")
        state = str(info.get("execution_status", "unknown"))
        response = ""
        if state in {"finished", "error", "stuck"}:
            try:
                final = self._request(
                    "GET", f"/api/conversations/{conversation_id}/agent_final_response"
                )
                response = final.get("response", "") or ""
            except OpenHandsError:
                response = ""
        return DelegationResult(
            conversation_id=conversation_id,
            status=state,
            response=response,
            url=f"{self.base_url}/conversations/{conversation_id}",
        )

    def wait(self, conversation_id: str, timeout: float = 900.0,
             poll: float = 10.0) -> DelegationResult:
        deadline = time.time() + timeout
        last = self.status(conversation_id)
        while not last.finished and time.time() < deadline:
            time.sleep(poll)
            last = self.status(conversation_id)
        return last

    def run_task(self, task: str, timeout: float = 900.0, **kwargs: Any) -> DelegationResult:
        """Start a task and block until it finishes (or the timeout expires)."""
        cid = self.start_task(task, **kwargs)
        return self.wait(cid, timeout=timeout)
