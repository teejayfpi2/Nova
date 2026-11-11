"""FastAPI application: REST + WebSocket + the web/PWA interface."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .agent import Agent
from .bridges import REGISTRY as BRIDGES
from .bridges import LocalBridge, RemoteBridge
from .config import settings
from .llm import LLMClient
from .memory import Memory
from .scheduler import Scheduler
from .voice import SpeechToText, TextToSpeech, VoiceError

STATIC_DIR = Path(__file__).parent / "static"

memory = Memory()
llm = LLMClient()
stt = SpeechToText(llm=llm)
tts = TextToSpeech(llm=llm)

BRIDGES.register("laptop", LocalBridge("laptop"))
scheduler = Scheduler(memory)
agent = Agent(memory=memory, llm=llm, bridges=BRIDGES.as_dict())

app = FastAPI(title="Nova Assistant", version="0.1.0")


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def require_token(authorization: str | None = Header(default=None), token: str | None = None) -> None:
    if not settings.auth_token:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if supplied != settings.auth_token and token != settings.auth_token:
        raise HTTPException(status_code=401, detail="invalid or missing token")


# --------------------------------------------------------------------------
# live event hub (websocket + fired reminders)
# --------------------------------------------------------------------------
class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, payload: dict[str, Any]) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)


hub = Hub()


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())

    def on_reminder(reminder) -> None:  # noqa: ANN001
        hub.broadcast_threadsafe(
            {"type": "reminder", "id": reminder.id, "body": reminder.body, "due": reminder.due}
        )

    scheduler.on_fire(on_reminder)
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Nova Assistant", version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------------
# core chat
# --------------------------------------------------------------------------
def _agent_for(bridges: dict[str, Any] | None = None) -> Agent:
    if bridges:
        merged = BRIDGES.as_dict()
        merged.update(bridges)
        return Agent(memory=memory, llm=llm, bridges=merged)
    return agent


@app.post("/api/chat")
async def chat(payload: dict[str, Any], _: None = Depends(require_token)) -> dict[str, Any]:
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    session = payload.get("session", "default")
    history = payload.get("history")
    bridges = BRIDGES.as_dict()
    # The agent loop is blocking (it may wait on a remote device bridge), so it
    # must not run on the event loop or the bridge poll endpoints would starve.
    result = await asyncio.to_thread(
        _agent_for(bridges).run, message, session=session, history=history
    )
    return {"reply": result, "session": session}


@app.websocket("/api/ws")
async def ws_chat(ws: WebSocket, token: str | None = None) -> None:
    if settings.auth_token and token != settings.auth_token:
        await ws.close(code=4401)
        return
    await hub.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            message = (data.get("message") or "").strip()
            session = data.get("session", "default")
            if not message:
                continue
            await ws.send_text(json.dumps({"type": "thinking"}))

            events = _agent_for().stream(message, session=session)
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def produce() -> None:
                try:
                    for event in events:
                        asyncio.run_coroutine_threadsafe(queue.put(event), loop)
                finally:
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop)

            task = asyncio.create_task(asyncio.to_thread(produce))
            while True:
                event = await queue.get()
                if event is None:
                    break
                await ws.send_text(json.dumps({"session": session, **event}))
            await task
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:  # noqa: BLE001
        hub.disconnect(ws)


# --------------------------------------------------------------------------
# voice
# --------------------------------------------------------------------------
@app.get("/api/voice/status")
async def voice_status(_: None = Depends(require_token)) -> dict[str, Any]:
    return {
        "stt": {"configured": stt.backend, "available": stt.available_backends()},
        "tts": {"configured": tts.backend, "available": tts.available_backends()},
    }


@app.post("/api/transcribe")
async def transcribe(
    audio: UploadFile = File(...), _: None = Depends(require_token)
) -> dict[str, Any]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio")
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    try:
        result = await asyncio.to_thread(stt.transcribe, data, suffix)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"text": result.text, "backend": result.backend}


@app.post("/api/speak")
async def speak(payload: dict[str, Any], _: None = Depends(require_token)) -> Response:
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        audio, mime = await asyncio.to_thread(tts.synthesize, text)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=mime)


# --------------------------------------------------------------------------
# memory / todos / reminders
# --------------------------------------------------------------------------
@app.get("/api/memory")
async def get_memory(_: None = Depends(require_token)) -> dict[str, Any]:
    return {
        "facts": memory.facts(),
        "notes": memory.notes(),
        "todos": memory.todos(include_done=True),
        "reminders": [r.to_dict() for r in memory.reminders(include_done=True)],
    }


@app.delete("/api/memory/facts/{key}")
async def delete_fact(key: str, _: None = Depends(require_token)) -> dict[str, Any]:
    return {"deleted": memory.forget(key)}


@app.post("/api/todos")
async def create_todo(payload: dict[str, Any], _: None = Depends(require_token)) -> dict[str, Any]:
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="body is required")
    return {"id": memory.add_todo(body)}


@app.post("/api/todos/{tid}/complete")
async def finish_todo(tid: int, _: None = Depends(require_token)) -> dict[str, Any]:
    return {"completed": memory.complete_todo(tid)}


@app.post("/api/reminders")
async def create_reminder(payload: dict[str, Any], _: None = Depends(require_token)) -> dict[str, Any]:
    from .tools.builtin import parse_when

    body = (payload.get("body") or "").strip()
    when = (payload.get("when") or "").strip()
    if not body or not when:
        raise HTTPException(status_code=400, detail="body and when are required")
    try:
        due = parse_when(when)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rid = memory.add_reminder(body, due, payload.get("repeat", "none"))
    return {"id": rid, "due": due}


@app.get("/api/reminders")
async def get_reminders(_: None = Depends(require_token)) -> dict[str, Any]:
    return {"reminders": [r.to_dict() for r in memory.reminders(include_done=True)]}


# --------------------------------------------------------------------------
# devices / bridges
# --------------------------------------------------------------------------
@app.get("/api/devices")
async def devices(_: None = Depends(require_token)) -> dict[str, Any]:
    return {"devices": BRIDGES.status()}


@app.post("/api/devices/{name}/hello")
async def device_hello(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Called by a remote agent when it comes online."""
    bridge = BRIDGES.get(name)
    if not isinstance(bridge, RemoteBridge):
        bridge = RemoteBridge(name)
        BRIDGES.register(name, bridge)
    bridge.hello(payload.get("capabilities"))
    return {"ok": True, "name": name}


@app.post("/api/bridge/poll")
async def bridge_poll(payload: dict[str, Any]) -> dict[str, Any]:
    """A remote agent asks for the next command to run."""
    name = payload.get("name", "phone")
    bridge = BRIDGES.get(name)
    if not isinstance(bridge, RemoteBridge):
        bridge = RemoteBridge(name)
        BRIDGES.register(name, bridge)
    bridge.hello(payload.get("capabilities"))
    job = bridge.next_job()
    return {"job": job}


@app.post("/api/bridge/result")
async def bridge_result(payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name", "phone")
    bridge = BRIDGES.get(name)
    if not isinstance(bridge, RemoteBridge):
        raise HTTPException(status_code=404, detail="unknown device")
    bridge.submit_result(payload.get("id", ""), str(payload.get("result", "")))
    return {"ok": True}


# --------------------------------------------------------------------------
# shell / health
# --------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_configured": bool(llm.api_key) or llm._managed is not None,  # noqa: SLF001
        "model": llm.model,
        "time": time.time(),
    }


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "assistant.server:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
