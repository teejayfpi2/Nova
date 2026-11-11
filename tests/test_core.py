"""Tests for memory, time parsing, tool schemas and the agent loop."""

from __future__ import annotations

import time

import pytest

from assistant.agent import Agent
from assistant.llm import LLMResponse, ToolCall
from assistant.memory import Memory
from assistant.tools import REGISTRY
from assistant.tools.builtin import parse_when


@pytest.fixture()
def memory(tmp_path):
    return Memory(tmp_path / "test.db")


def test_facts_roundtrip(memory):
    memory.remember("user_name", "Ada")
    assert memory.facts()[0]["value"] == "Ada"
    memory.remember("user_name", "Grace")
    assert memory.facts()[0]["value"] == "Grace"  # upsert, not duplicate
    assert memory.forget("user_name") is True
    assert memory.facts() == []


def test_notes_todos_reminders(memory):
    memory.add_note("buy milk", "shopping")
    assert "buy milk" in memory.notes()[0]["body"]
    tid = memory.add_todo("write report")
    assert memory.todos()[0]["id"] == tid
    assert memory.complete_todo(tid) is True
    rid = memory.add_reminder("stand up", time.time() + 60, "daily")
    assert memory.reminders()[0].id == rid
    assert memory.due_reminders() == []


def test_repeating_reminder_rolls_forward(memory):
    rid = memory.add_reminder("stretch", time.time() - 1, "daily")
    before = memory.reminders()[0].due
    memory.complete_reminder(rid)
    after = memory.reminders()[0].due
    assert after > before + 86000


def test_parse_when_relative_and_absolute():
    now = time.time()
    assert 590 < parse_when("in 10 minutes", now) - now < 610
    assert 3500 < parse_when("in 1 hour", now) - now < 3700
    due = parse_when("tomorrow at 9am", now)
    assert time.localtime(due).tm_hour == 9


def test_tool_schemas_are_valid():
    schemas = REGISTRY.schemas()
    names = {s["function"]["name"] for s in schemas}
    assert {"remember", "web_search", "send_message", "type_text", "set_reminder"} <= names
    for schema in schemas:
        fn = schema["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"


class ScriptedLLM:
    """Returns queued responses so the agent loop can be tested without a server."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


def test_agent_executes_tool_then_answers(memory):
    llm = ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="1", name="remember", arguments={"key": "city", "value": "Lisbon"})],
                raw={},
            ),
            LLMResponse(content="Saved that.", tool_calls=[], raw={}),
        ]
    )
    agent = Agent(memory=memory, llm=llm)
    events = list(agent.stream("remember I live in Lisbon"))
    assert any(e["type"] == "tool" and e["name"] == "remember" for e in events)
    assert events[-1]["type"] == "final"
    assert memory.facts()[0]["value"] == "Lisbon"


def test_agent_reports_llm_failure(memory):
    from assistant.llm import LLMError

    class BrokenLLM:
        def chat(self, *a, **k):
            raise LLMError("no key")

    agent = Agent(memory=memory, llm=BrokenLLM())
    events = list(agent.stream("hello"))
    assert events[-1]["type"] == "final"
    assert "could not reach" in events[-1]["text"]


def test_duckduckgo_parser_extracts_clean_links():
    from assistant.tools.builtin import _parse_ddg

    page = (
        "<a rel='nofollow' href=\"//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=x\" "
        "class='result-link'>Example A</a>"
        "<td class='result-snippet'>First snippet</td>"
        "<a rel='nofollow' href=\"//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb\" "
        "class='result-link'>Example B</a>"
        "<td class='result-snippet'>Second snippet</td>"
    )
    results = _parse_ddg(page, 5)
    assert len(results) == 2
    assert "https://example.com/a" in results[0]
    assert "Example A" in results[0]
    assert "First snippet" in results[0]
    assert "https://example.org/b" in results[1]


def test_openhands_client_requires_config():
    from assistant.openhands import OpenHandsClient, OpenHandsError

    client = OpenHandsClient(base_url="", session_key="")
    assert client.configured is False
    with pytest.raises(OpenHandsError):
        client.start_task("do something")


def test_openhands_start_task_builds_payload(monkeypatch):
    from assistant import openhands

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id": "conv-123"}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = req.data
        return FakeResp()

    monkeypatch.setattr(openhands.urllib.request, "urlopen", fake_urlopen)
    client = openhands.OpenHandsClient(base_url="http://127.0.0.1:60000", session_key="k")
    cid = client.start_task("build a thing", model="openhands_Default")

    assert cid == "conv-123"
    assert captured["url"].endswith("/api/conversations")
    assert captured["headers"].get("X-session-api-key") == "k"
    import json

    payload = json.loads(captured["body"])
    assert payload["initial_message"]["content"][0]["text"] == "build a thing"
    assert payload["agent"]["llm"]["model"] == "openhands_Default"
    assert {"name": "terminal"} in payload["agent"]["tools"]


def test_delegate_task_reports_when_unconfigured(monkeypatch):
    from assistant import openhands

    real = openhands.OpenHandsClient
    monkeypatch.setattr(openhands, "OpenHandsClient", lambda *a, **k: real("", ""))
    out = REGISTRY.call("delegate_task", {"task": "x"}, ctx=None)
    assert "not configured" in out


def test_llm_client_sends_extra_headers(monkeypatch):
    from assistant import llm as llm_mod

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"hi"}}]}'

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return FakeResp()

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
    client = llm_mod.LLMClient(
        base_url="http://127.0.0.1:60000/v1",
        api_key="",
        model="openhands_Default",
        extra_headers={"X-Session-API-Key": "secret"},
    )
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "hi"
    assert captured["headers"].get("X-session-api-key") == "secret"


def test_llm_client_sends_user_agent(monkeypatch):
    # Groq sits behind Cloudflare, which answers the default urllib User-Agent
    # with a 403 (error 1010). Without an explicit User-Agent every Groq request
    # fails, so pin it down.
    from assistant import llm as llm_mod

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"hi"}}]}'

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return FakeResp()

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
    client = llm_mod.LLMClient(base_url="https://api.groq.com/openai/v1", api_key="k")
    client.chat([{"role": "user", "content": "hi"}])
    assert captured["headers"].get("User-agent") == llm_mod.USER_AGENT
