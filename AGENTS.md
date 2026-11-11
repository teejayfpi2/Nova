# AGENTS.md

Repository guidance for AI agents working in this project.

## What this is

Nova is a self-hosted personal assistant: a FastAPI server ("the brain") plus an
installable PWA front end, plus small device agents that let it control a phone
and a laptop. See `README.md` for the user-facing guide.

## Layout

- `assistant/agent.py` — the reasoning loop (prompt → tool calls → answer). Streams events.
- `assistant/llm.py` — OpenAI-compatible client. Also supports the OpenHands managed
  key proxy via `OH_LLM_API_KEY_REFRESH_URL` / `OH_LLM_API_KEY_REFRESH_HEADERS`.
- `assistant/memory.py` — SQLite long-term memory (facts, notes, todos, reminders, history).
- `assistant/tools/__init__.py` — `@tool` decorator + registry that builds JSON schemas.
- `assistant/tools/builtin.py` — all built-in tools.
- `assistant/bridges.py` — `LocalBridge` (in-process, pyautogui/xdotool) and
  `RemoteBridge` (HTTP long-poll to a device agent).
- `assistant/server.py` — REST + WebSocket + static hosting.
- `bridges/phone_agent.py`, `bridges/laptop_agent.py` — run on the target devices.
- `scripts/fake_openai_server.py` — offline stub model for tests and hacking.

## Commands

```bash
python -m pytest tests -q                      # 18 tests, no network needed
python -m assistant.cli chat                   # interactive
python -m assistant.cli serve                  # run the server
python scripts/fake_openai_server.py 9099 &    # stub model
```

## Conventions

- Tools: decorate a function with `@tool`; first docstring paragraph is the
  description; document params as `name: description` lines. Add `ctx: ToolContext`
  when the tool needs memory/settings/bridges.
- Device tools take `target="laptop"|"phone"` and route through `ctx.bridge(target)`,
  falling back to local execution.
- The agent loop is **blocking**. Never call it directly from an async route on the
  event loop — use `asyncio.to_thread` (see `/api/chat`), or device-bridge polling
  will deadlock. There is a regression test for this.
- Keep dependencies in `requirements.txt` and `pyproject.toml` in sync.

## Gotchas

- `python-multipart` is required for the audio upload endpoint.
- Voice is optional and degrades: STT `openai`→`faster-whisper`→`whisper`→`vosk`;
  TTS `edge-tts`→`openai`→`pyttsx3`→`say`→`espeak`. `ffmpeg` is needed to convert
  browser audio to WAV for local Whisper.
- Web search scrapes DuckDuckGo's **lite** endpoint (the html one serves an
  anti-bot page to plain clients) with a browser user agent.
- `data/memory.db` is the whole long-term memory; it is gitignored.
