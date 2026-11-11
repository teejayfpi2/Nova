"""LLM client for any OpenAI-compatible chat-completions endpoint.

Works with OpenAI, Azure OpenAI, Groq, Together, OpenRouter, Mistral, DeepSeek,
Ollama, LM Studio, vLLM, llama.cpp server and the OpenHands LLM proxy.

If the endpoint is an OpenHands managed proxy, set OH_LLM_API_KEY_REFRESH_URL /
OH_LLM_API_KEY_REFRESH_HEADERS (normally exported for you) and the client will
fetch a short-lived key automatically instead of using a static one.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import settings


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    raw: dict[str, Any]


class ManagedKeyProvider:
    """Fetches and caches a short-lived API key from the OpenHands proxy."""

    def __init__(self, url: str, headers: dict[str, str], ttl: float = 600.0) -> None:
        self.url = url
        self.headers = headers
        self.ttl = ttl
        self._key = ""
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._key and (time.time() - self._fetched_at) < self.ttl:
                return self._key
            req = urllib.request.Request(self.url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode())
            except Exception as exc:  # noqa: BLE001 - surfaced to caller
                raise LLMError(f"could not refresh LLM key: {exc}") from exc
            key = (
                payload.get("api_key")
                or payload.get("key")
                or payload.get("value")
                or payload.get("token")
            )
            if not key and isinstance(payload.get("data"), dict):
                key = payload["data"].get("api_key") or payload["data"].get("key")
            if not key:
                raise LLMError("key refresh endpoint returned no api_key field")
            self._key = str(key)
            self._fetched_at = time.time()
            return self._key


def _resolve_managed_headers() -> dict[str, str]:
    raw = os.environ.get("OH_LLM_API_KEY_REFRESH_HEADERS", "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    resolved: dict[str, str] = {}
    for name, value in parsed.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            value = os.environ.get(value[2:-1], "")
        if value:
            resolved[name] = value
    return resolved


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout or settings.llm_timeout
        self._managed: ManagedKeyProvider | None = None
        refresh_url = os.environ.get("OH_LLM_API_KEY_REFRESH_URL")
        if refresh_url and not self.api_key:
            headers = _resolve_managed_headers()
            if headers:
                self._managed = ManagedKeyProvider(refresh_url, headers)

    # -- low level -------------------------------------------------------
    def _auth_key(self) -> str:
        if self._managed is not None:
            return self._managed.get()
        return self.api_key

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        key = self._auth_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM request failed: {exc}") from exc

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.temperature if temperature is None else temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if max_tokens:
            body["max_tokens"] = max_tokens

        payload = self._post("/chat/completions", body)
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected LLM response: {json.dumps(payload)[:500]}") from exc

        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))

        return LLMResponse(content=message.get("content") or "", tool_calls=calls, raw=payload)

    def is_available(self) -> bool:
        try:
            self.chat([{"role": "user", "content": "ping"}], max_tokens=1)
            return True
        except LLMError:
            return False
