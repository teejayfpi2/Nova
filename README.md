# Nova — a personal assistant for your laptop and phone

Nova is a self-hosted AI assistant you talk to. It listens, talks back, remembers
things about you, and — unlike a plain chatbot — it actually *does* things on your
devices: types text, presses keys, clicks, opens apps, sends messages, reads your
notifications, searches the web, runs commands and sets reminders.

It is one small Python service. You run the server on one machine (a laptop, a
Raspberry Pi, a cheap VPS), open the web app on your phone and laptop, and connect
the devices you want it to control.

```
        ┌───────────────┐        WebSocket / REST         ┌──────────────┐
        │  Phone (PWA)  │◀───────────────────────────────▶│              │
        └───────────────┘                                 │              │
        ┌───────────────┐        WebSocket / REST         │  Nova server │
        │ Laptop (PWA)  │◀───────────────────────────────▶│  (the brain) │
        └───────────────┘                                 │              │
                                                          └──────┬───────┘
   ┌────────────────────┐   long-poll (outbound only)            │
   │ phone_agent.py     │◀───────────────────────────────────────┤
   │ (Termux or ADB)    │                                         │
   ├────────────────────┤                                         │
   │ laptop_agent.py    │◀────────────────────────────────────────┘
   └────────────────────┘
```

The agents on your devices only make *outbound* requests, so this works even when
your phone is on mobile data behind a carrier NAT — no port forwarding needed.

## What it can do

| Area | Examples |
| --- | --- |
| Memory | "Remember my sister's birthday is 4 March", "what's my Wi-Fi password?" |
| Notes & to-dos | "Note down the part number", "add milk to my list", "what's on my list?" |
| Reminders | "Remind me to call mum at 6pm", "remind me every day at 8 to take pills" |
| Web | "Who won the game last night?", "summarise this page: <url>" |
| Phone | "Text Alex I'm running late", "read my last messages", "open WhatsApp" |
| Laptop | "Type this into the form", "open Spotify", "take a screenshot", "press ctrl+s" |
| Code | "Run the tests and tell me what failed", "what's my disk usage?" |
| Voice | Hold the mic to talk; replies are spoken back |

## Quick start

### 1. Install

```bash
git clone <this repo> nova && cd nova
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# recommended extras (local voice, desktop control)
pip install faster-whisper edge-tts pyautogui
```

### 2. Give it a brain (a language model)

Nova speaks the OpenAI chat-completions API, so you can point it at almost
anything. Pick one:

```bash
# OpenAI
export NOVA_LLM_BASE_URL=https://api.openai.com/v1
export NOVA_LLM_API_KEY=sk-...
export NOVA_LLM_MODEL=gpt-4o-mini

# or a fully local model with Ollama (no API key, nothing leaves your machine)
ollama pull llama3.1
export NOVA_LLM_BASE_URL=http://localhost:11434/v1
export NOVA_LLM_MODEL=llama3.1

# or Groq, Together, OpenRouter, LM Studio, vLLM, llama.cpp — any compatible URL
```

### 3. Run the server

```bash
export NOVA_AUTH_TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
python -m assistant.cli serve
# -> http://0.0.0.0:8000
```

Open `http://<your-machine>:8000` on your laptop, and the same URL on your phone.

### 4. Install the phone/laptop app

Open the web app in the browser and use **Add to Home Screen** (iOS Safari) or
**Install app** (Android Chrome / desktop Chrome). It becomes a real app icon with
its own window, and voice input works from there.

Put the server URL and the access token into **⚙ Settings** the first time.

## Connecting your devices so Nova can act on them

The web app is the *interface*. To let Nova *control* a device, run an agent on it.

### Phone (Android, Termux)

```bash
pkg install python termux-api
pip install requests
export NOVA_SERVER=https://your-server:8000
export NOVA_TOKEN=your-token
python bridges/phone_agent.py
```

Install the **Termux:API** app from F-Droid to unlock SMS sending, reading
notifications, camera and clipboard.

For full UI control (taps at coordinates, reading the screen), connect the phone
by USB and run in ADB mode from a computer:

```bash
python bridges/phone_agent.py --adb
```

### Laptop

```bash
pip install pyautogui requests
export NOVA_SERVER=https://your-server:8000
export NOVA_TOKEN=your-token
python bridges/laptop_agent.py
```

If the server itself runs on the laptop, you can skip this — Nova already has a
local bridge to that machine and will use `pyautogui` directly.

## Try it

Say or type:

- "Remember I park in space B12."
- "Text Sam I'll be there in ten."
- "Remind me in 30 minutes to check the oven."
- "Open my notes app and type the meeting summary."
- "Search for a good pasta recipe and read me the first one."
- "Run `df -h` and tell me if I'm low on space."

## Configuration

Everything is an environment variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NOVA_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `NOVA_LLM_API_KEY` | – | Key for that endpoint |
| `NOVA_LLM_MODEL` | `gpt-4o-mini` | Model name |
| `NOVA_HOST` / `NOVA_PORT` | `0.0.0.0` / `8000` | Server bind address |
| `NOVA_AUTH_TOKEN` | – | Shared secret; **set this** if the server is reachable from the internet |
| `NOVA_STT_BACKEND` | `auto` | `auto`, `openai`, `faster-whisper`, `whisper`, `vosk` |
| `NOVA_TTS_BACKEND` | `auto` | `auto`, `edge-tts`, `openai`, `pyttsx3`, `say`, `espeak` |
| `NOVA_WHISPER_MODEL` | `base` | Local Whisper size (`tiny`…`large`) |
| `NOVA_TTS_VOICE` | `en-US-AriaNeural` | edge-tts voice |
| `NOVA_MAX_STEPS` | `12` | Max tool calls per request |
| `NOVA_SHELL` | `true` | Allow the shell tool |
| `NOVA_DEVICE_CONTROL` | `true` | Allow device tools |
| `NOVA_DATA_DIR` | `./data` | Where `memory.db` and screenshots live |

## Security

Read this before exposing Nova to the internet.

- **Set `NOVA_AUTH_TOKEN`.** Without it, anyone who can reach the port can use
  the assistant *and* the shell tool. Treat the token like a password.
- Prefer a private network (Tailscale, WireGuard, your home LAN) over opening a
  port to the world. If you must expose it, put it behind HTTPS.
- The `run_shell` and `run_python` tools execute real commands. Set
  `NOVA_SHELL=false` to switch them off entirely.
- The device agents can type and click on your behalf — that is the point, but it
  also means a compromised token is a compromised device. Keep it secret.
- Memory is a plain SQLite file at `data/memory.db`. Back it up or delete it
  freely.

## Docker

```bash
docker build -t nova .
docker run -p 8000:8000 \
  -e NOVA_LLM_API_KEY=sk-... \
  -e NOVA_AUTH_TOKEN=change-me \
  -v "$PWD/data:/app/data" \
  nova
```

## Development

```bash
pip install -r requirements.txt pytest httpx
python -m pytest tests -q          # 17 tests, no network needed

# run a fake model + server for offline hacking
python scripts/fake_openai_server.py 9099 &
NOVA_LLM_BASE_URL=http://127.0.0.1:9099/v1 NOVA_LLM_API_KEY=x NOVA_LLM_MODEL=fake \
  python -m assistant.cli chat
```

### Layout

```
assistant/
  agent.py       the reasoning loop: prompt -> tool calls -> answer
  llm.py         OpenAI-compatible client (+ managed key refresh)
  memory.py      SQLite long-term memory: facts, notes, todos, reminders
  voice.py       speech-to-text and text-to-speech with fallbacks
  bridges.py     local + remote device control
  scheduler.py   fires reminders in the background
  server.py      FastAPI app: REST, WebSocket, PWA hosting
  tools/         the tools the model can call
  static/        the installable web/PWA interface
bridges/
  phone_agent.py   runs on Android (Termux or ADB)
  laptop_agent.py  runs on a second computer
```

## Troubleshooting

- **"I could not reach my language model"** — check `NOVA_LLM_BASE_URL`,
  `NOVA_LLM_API_KEY` and that the model name exists.
- **No voice input** — the browser needs mic permission and an HTTPS origin (or
  `localhost`). Install a local STT backend or set an API key.
- **Device action times out** — the agent on that device is not running or cannot
  reach the server. Check `/api/devices` shows it online.
- **Nothing happens on the phone** — install Termux:API, or use ADB mode.
