"""End-to-end tests for the HTTP API using a fake LLM."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from assistant.llm import LLMResponse, ToolCall


class FakeLLM:
    def __init__(self):
        self.model = "fake"
        self.base_url = "http://fake"
        self.api_key = "fake"
        self._managed = None
        self._next: list[LLMResponse] = []

    def queue(self, *responses: LLMResponse) -> None:
        self._next.extend(responses)

    def chat(self, messages, tools=None, **kwargs):
        if self._next:
            return self._next.pop(0)
        return LLMResponse(content="Hello from the fake model.", tool_calls=[], raw={})

    def is_available(self):
        return True


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVA_DATA_DIR", str(tmp_path))
    import assistant.config as config

    importlib.reload(config)
    import assistant.memory as memory_mod

    importlib.reload(memory_mod)
    import assistant.server as server

    importlib.reload(server)
    server.llm = FakeLLM()
    server.agent = server.Agent(memory=server.memory, llm=server.llm)
    with TestClient(server.app) as c:
        c.fake_llm = server.llm
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_chat_roundtrip(client):
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 200
    assert "fake model" in resp.json()["reply"]


def test_chat_requires_message(client):
    assert client.post("/api/chat", json={}).status_code == 400


def test_chat_runs_tools(client):
    client.fake_llm.queue(
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="1", name="add_todo", arguments={"body": "buy milk"})],
            raw={},
        ),
        LLMResponse(content="Added it.", tool_calls=[], raw={}),
    )
    reply = client.post("/api/chat", json={"message": "add buy milk"}).json()["reply"]
    assert reply == "Added it."
    todos = client.get("/api/memory").json()["todos"]
    assert todos[0]["body"] == "buy milk"


def test_reminder_api(client):
    resp = client.post("/api/reminders", json={"body": "call mum", "when": "in 5 minutes"})
    assert resp.status_code == 200
    assert resp.json()["due"] > 0
    listed = client.get("/api/reminders").json()["reminders"]
    assert listed[0]["body"] == "call mum"


def test_devices_endpoint(client):
    devices = client.get("/api/devices").json()["devices"]
    assert "laptop" in devices


def test_bridge_protocol(client):
    client.post("/api/devices/phone/hello", json={"capabilities": ["type_text"]})
    poll = client.post("/api/bridge/poll", json={"name": "phone"}).json()
    assert poll["job"] is None  # nothing queued yet
    assert client.get("/api/devices").json()["devices"]["phone"]["online"] is True


def test_index_serves_ui(client):
    html = client.get("/").text
    assert "Nova" in html and "app.js" in html


def test_about_endpoint_returns_builder(client):
    body = client.get("/api/about").json()
    assert body["app"] == "Nova"
    b = body["builder"]
    assert b["name"] == "Ayanlowo Olatunji Ayobami"
    assert b["email"] == "ayanlowo89@gmail.com"
    assert b["phone"] == "+2347038193753"
    assert "linkedin.com/in/olatunjiayanlowo" in b["linkedin"]


def test_builder_facts_are_seeded_and_recallable(client):
    # The server seeds the builder's details into memory on startup.
    facts = {f["key"]: f["value"] for f in client.get("/api/memory").json()["facts"]}
    assert facts["builder_name"] == "Ayanlowo Olatunji Ayobami"
    assert facts["builder_email"] == "ayanlowo89@gmail.com"
    assert facts["builder_phone"] == "+2347038193753"
    assert "olatunjiayanlowo" in facts["builder_linkedin"]


def test_about_builder_tool(client):
    from assistant.tools import REGISTRY

    tool = REGISTRY.get("about_builder")
    assert tool is not None
    text = tool.func()
    assert "Ayanlowo Olatunji Ayobami" in text
    assert "ayanlowo89@gmail.com" in text
    assert "olatunjiayanlowo" in text


def test_system_prompt_includes_builder(client):
    from assistant import server

    prompt = server.agent._system_prompt()
    assert "Ayanlowo Olatunji Ayobami" in prompt
    assert "olatunjiayanlowo" in prompt


def test_device_tool_routes_through_remote_bridge(client):
    """A device tool call must reach the phone agent and return its result.

    Regression: the chat endpoint once ran the blocking agent loop on the event
    loop, so the phone's poll request could never be served and the call
    deadlocked.
    """
    import threading
    import time

    client.post("/api/devices/phone/hello", json={"capabilities": ["type_text"]})
    client.fake_llm.queue(
        LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="d1",
                    name="type_text",
                    arguments={"text": "hi there", "target": "phone"},
                )
            ],
            raw={},
        ),
        LLMResponse(content="Typed it.", tool_calls=[], raw={}),
    )

    captured = {}

    def phone():
        deadline = time.time() + 10
        while time.time() < deadline:
            job = client.post("/api/bridge/poll", json={"name": "phone"}).json()["job"]
            if job:
                captured.update(job)
                client.post(
                    "/api/bridge/result",
                    json={"name": "phone", "id": job["id"], "result": "typed on phone"},
                )
                return
            time.sleep(0.05)

    worker = threading.Thread(target=phone)
    worker.start()
    reply = client.post("/api/chat", json={"message": "type a greeting"}).json()["reply"]
    worker.join(timeout=10)

    assert captured.get("action") == "type_text"
    assert captured.get("args") == {"text": "hi there"}
    assert reply == "Typed it."


def test_websocket_streams_tool_and_final(client):
    client.fake_llm.queue(
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="1", name="list_todos", arguments={})],
            raw={},
        ),
        LLMResponse(content="Nothing on the list.", tool_calls=[], raw={}),
    )
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"message": "what's on my list?"})
        seen = [ws.receive_json() for _ in range(4)]
    types = [m["type"] for m in seen]
    assert "thinking" in types
    assert "tool" in types
    assert seen[-1]["type"] == "final"
    assert seen[-1]["text"] == "Nothing on the list."
