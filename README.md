# Nova — a personal assistant for your laptop and phone

Nova is a self-hosted AI assistant you talk to. It listens, talks back, remembers
things about you, and — unlike a plain chatbot — it actually *does* things on your
devices: types text, presses keys, clicks, opens apps, sends messages, reads your
notifications, searches the web, runs commands and sets reminders.

It ships as **three pieces**: one Python server (the brain), a real **Android app**
(installable APK), and a **desktop app** for your laptop. Both apps can either just
talk to Nova or let it *control* that device.

And it is more than a chatbot: Nova can hand whole jobs to a team of autonomous
OpenHands agents that use a terminal, edit files, browse the web and build and run
software. Ask for something big — "clone this repo and fix the failing tests",
"research X and write me a brief", "build me a script that renames my photos" — and
Nova delegates it, then reports back.

```
        ┌───────────────┐   REST / WebSocket   ┌──────────────┐
        │ Nova Android  │◀────────────────────▶│              │
        │   app (APK)   │                      │              │
        └───────────────┘                      │              │
        ┌───────────────┐   REST / WebSocket   │ Nova server  │
        │ Nova Desktop  │◀────────────────────▶│ (the brain)  │
        │  (Electron)   │                      │              │
        └───────────────┘                      └──────┬───────┘
                                                      │ delegates
                                       ┌──────────────▼──────────────┐
                                       │  OpenHands agent sandbox    │
                                       │  terminal · files · browser │
                                       └─────────────────────────────┘
```

The apps only make *outbound* requests, so this works even when your phone is on
mobile data behind a carrier NAT — no port forwarding needed.

## Built by

Nova was created and is developed by **Ayanlowo Olatunji Ayobami**.

| | |
| --- | --- |
| Email | [ayanlowo89@gmail.com](mailto:ayanlowo89@gmail.com) |
| Phone | [+2347038193753](tel:+2347038193753) |
| LinkedIn | [linkedin.com/in/olatunjiayanlowo](https://www.linkedin.com/in/olatunjiayanlowo) |

The builder's details live in one place — [`assistant/identity.py`](assistant/identity.py) —
and are surfaced everywhere: the agent's system prompt (so you can just *ask Nova*
who built it), seeded memory facts (`builder_name`, `builder_email`, ...), the
`/api/about` endpoint, the web settings panel, the desktop app's Settings sheet and
the Android app's Settings screen. Ask Nova "who built you?" and it will answer,
then use its web tools to look up the LinkedIn profile for more.

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
| **Delegate** | "Clone that repo and fix the failing tests", "build me a photo-renamer" |
| **Research** | "Research the best e-bikes under £2k and write me a brief with sources" |
| **Build** | "Write and test a script that converts my videos to mp4" |
| Voice | Hold the mic to talk; replies are spoken back |

## Quick start

The easiest way to configure Nova is a `.env` file in the project root — it works
the same on Windows, macOS and Linux, so you never need `export` or `set`. Copy
the template and fill it in:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

```ini
# .env
NOVA_LLM_BASE_URL=https://api.openai.com/v1
NOVA_LLM_API_KEY=sk-...
NOVA_LLM_MODEL=gpt-4o-mini
NOVA_AUTH_TOKEN=change-me-to-a-long-random-string
```

Nova reads this file automatically on startup. Values set in your shell still win,
so you can override any line for one run without editing the file.

### 1. Install

```bash
git clone <this repo> nova && cd nova

# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell or cmd)
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Then, optionally, the extras that unlock local voice and laptop control:

```bash
pip install faster-whisper edge-tts pyautogui
```

### 2. Give it a brain (a language model)

Nova speaks the OpenAI chat-completions API, so you can point it at almost
anything. Set these in `.env` (see the template above). Pick one:

```ini
# OpenAI
NOVA_LLM_BASE_URL=https://api.openai.com/v1
NOVA_LLM_API_KEY=sk-...
NOVA_LLM_MODEL=gpt-4o-mini

# or a fully local model with Ollama (no API key, nothing leaves your machine)
#   ollama pull llama3.1
NOVA_LLM_BASE_URL=http://localhost:11434/v1
NOVA_LLM_MODEL=llama3.1

# or Groq, Together, OpenRouter, LM Studio, vLLM, llama.cpp — any compatible URL
```

### 3. Run the server

Generate a token and put it in `.env` as `NOVA_AUTH_TOKEN`, then start the server:

```bash
# macOS / Linux
python -m assistant.cli serve

# Windows
py -m assistant.cli serve
```

If you'd rather set the token for one run instead of using `.env`:

```bash
# macOS / Linux
export NOVA_AUTH_TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
python -m assistant.cli serve

# Windows PowerShell
$env:NOVA_AUTH_TOKEN = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
py -m assistant.cli serve

# Windows cmd
set NOVA_AUTH_TOKEN=change-me-to-a-long-random-string
py -m assistant.cli serve
```

Either way the banner prints exactly what to type into the phone and desktop apps:

```
  Nova is starting.
  On this computer:  http://localhost:8000
  On your phone:     http://192.168.1.42:8000
  Access token:      <your token>
```

Open `http://<your-machine>:8000` on your laptop, and the same URL on your phone.

The **server URL** is your computer's address on the network — the phone and
computer must be on the same Wi-Fi. Don't use `localhost`/`127.0.0.1` in the app:
on the phone that means the phone itself. The **access token** is whatever you set
`NOVA_AUTH_TOKEN` to; if you left it empty, the server needs no token and the app
can leave the field blank (but anyone who can reach the port can then use Nova, so
set one if the port is exposed beyond your LAN).

### 4. Install the phone and laptop apps

**Android phone — install the APK**

A ready-to-install debug APK is built for you. Build it fresh any time with:

```bash
./scripts/build_apk.sh          # downloads a private JDK+SDK on first run, no root needed
# -> android/app/build/outputs/apk/debug/app-debug.apk
```

**Or let GitHub build it.** The `Build Android APK` workflow
(`.github/workflows/android.yml`) runs on every push that touches `android/**`,
on pull requests, and on demand from the Actions tab (**Run workflow**). Each run:

- builds the debug APK on a clean Ubuntu runner,
- uploads it as the **`nova-debug-apk`** artifact (download it from the run page), and
- on a push to `main`, refreshes a rolling **`latest`** release you can install
  straight from your phone at
  `https://github.com/teejayfpi2/Nova/releases/download/latest/nova-android-debug.apk`.

The Android project uses the committed Gradle wrapper, so the same
`./gradlew assembleDebug` works locally and in CI.

Then get it onto the phone, either way works:

```bash
# over USB (developer mode + USB debugging on)
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

or copy the `.apk` to the phone (email it to yourself, Google Drive, `adb push`)
and tap it — allow "install from unknown sources" when Android asks.

Open **Nova**, tap **⚙ Settings**, and enter your server URL and token. Nova asks
for microphone and notification permissions so you can talk to it and so it can
read your notifications.

**Laptop — install the desktop app**

Easiest: grab the installer for your OS from the rolling **`latest`** release
(`https://github.com/teejayfpi2/Nova/releases/tag/latest`):

| OS | Download |
| --- | --- |
| Windows | `Nova.Setup.1.0.0.exe` (installer) or `Nova.1.0.0.exe` (portable) |
| macOS | `Nova-1.0.0-arm64.dmg` |
| Linux | `Nova-1.0.0.AppImage` (portable) or `nova-desktop_1.0.0_amd64.deb` |

Install it like any normal app. On Linux, make the AppImage executable
(`chmod +x Nova-1.0.0.AppImage`) and double-click, or `sudo dpkg -i` the `.deb`.

**Or build it yourself.** Installers must be built on the OS you want to target:

```bash
./scripts/build_desktop.sh          # installers for the current OS -> desktop/dist/
./scripts/build_desktop.sh --win    # Windows: NSIS installer + portable exe
./scripts/build_desktop.sh --mac    # macOS: dmg + zip
./scripts/build_desktop.sh --linux  # Linux: AppImage + deb
```

The `Build Desktop Apps` workflow builds all three platforms on every push that
touches `desktop/**`, uploads them as artifacts, and refreshes the `latest`
release. To just run it from source instead:

```bash
cd desktop && npm install && npm start
```

Nova lives in your menu bar / system tray. Open **Settings** inside the app, enter
the server URL and token, and tick **Let Nova control this computer** if you want
it to type, click and open things for you.

The web/PWA version still works too — open the server URL in a browser and choose
**Add to Home Screen** / **Install app** if you prefer not to install a binary.

## Superpowers: delegating to OpenHands agents

Nova's own brain can be *any* OpenAI-compatible model (see above). On top of that,
Nova can hand big, multi-step jobs to autonomous OpenHands agents that have a real
terminal, file editor and browser. Give Nova an OpenHands agent server and it gains
four new tools: `delegate_task`, `check_task`, `research_topic` and `build_software`.

```bash
export NOVA_OPENHANDS_URL=http://127.0.0.1:60000      # an OpenHands agent server
export NOVA_OPENHANDS_SESSION_KEY=your-session-key
export NOVA_OPENHANDS_MODEL=openhands_Default          # any model it serves
export NOVA_OPENHANDS_WORKDIR=/workspace               # where delegated work happens
```

Then just ask: *"delegate a task to build me a Python script that organises my
Downloads folder by file type, with tests."* Nova starts a sandboxed agent, waits
for it, and reads back the result. `check_task` lets you ask about a job later.

### Using the OpenHands LLM as Nova's brain

If you already run an OpenHands agent server, you can point Nova's own model at it
so no separate API key is needed:

```bash
export NOVA_LLM_BASE_URL=http://127.0.0.1:60000/v1
export NOVA_LLM_MODEL=openhands_Default
export NOVA_LLM_API_KEY=                                   # empty is fine
export NOVA_LLM_HEADERS='{"X-Session-API-Key": "your-session-key"}'
```

Any custom headers can be supplied as JSON via `NOVA_LLM_HEADERS`. If your endpoint
uses a short-lived key, Nova can refresh it automatically when
`OH_LLM_API_KEY_REFRESH_URL` is set — it re-reads the key on every request.

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
| `NOVA_LLM_HEADERS` | – | Extra request headers as JSON (e.g. for a session key) |
| `NOVA_OPENHANDS_URL` | – | OpenHands agent server for delegation tools |
| `NOVA_OPENHANDS_SESSION_KEY` | – | Key for that agent server |
| `NOVA_OPENHANDS_MODEL` | `openhands_Default` | Model the delegated agents use |
| `NOVA_OPENHANDS_WORKDIR` | – | Working directory for delegated work |
| `NOVA_OPENHANDS_TIMEOUT` | `60` | Per-request timeout (seconds) to the agent server |
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
python -m pytest tests -q          # 22 tests, no network needed

# run a fake model + server for offline hacking
python scripts/fake_openai_server.py 9099 &
NOVA_LLM_BASE_URL=http://127.0.0.1:9099/v1 NOVA_LLM_API_KEY=x NOVA_LLM_MODEL=fake \
  python -m assistant.cli chat
```

### Layout

```
assistant/
  agent.py       the reasoning loop: prompt -> tool calls -> answer
  llm.py         OpenAI-compatible client (+ managed key refresh, custom headers)
  openhands.py   OpenHands agent server client used by the delegation tools
  memory.py      SQLite long-term memory: facts, notes, todos, reminders
  voice.py       speech-to-text and text-to-speech with fallbacks
  bridges.py     local + remote device control
  scheduler.py   fires reminders in the background
  server.py      FastAPI app: REST, WebSocket, PWA hosting
  tools/         the tools the model can call (incl. delegate_task & friends)
  static/        the installable web/PWA interface
android/         the Android app (Kotlin) -> build with scripts/build_apk.sh
desktop/         the laptop app (Electron) -> build with npm run dist
bridges/
  phone_agent.py   runs on Android (Termux or ADB)
  laptop_agent.py  runs on a second computer (Python, no build needed)
scripts/
  build_apk.sh           one-shot Android build (self-contained toolchain)
  gen_android_sources.py regenerates the Android sources
  gen_desktop_sources.py regenerates the desktop app sources
```

## Troubleshooting

- **"I could not reach my language model"** — check `NOVA_LLM_BASE_URL`,
  `NOVA_LLM_API_KEY` and that the model name exists.
- **No voice input** — the browser needs mic permission and an HTTPS origin (or
  `localhost`). Install a local STT backend or set an API key.
- **Device action times out** — the agent on that device is not running or cannot
  reach the server. Check `/api/devices` shows it online.
- **Nothing happens on the phone** — install Termux:API, or use ADB mode.
- **Delegation says "not configured"** — set `NOVA_OPENHANDS_URL` and
  `NOVA_OPENHANDS_SESSION_KEY`, and make sure the agent server is reachable.
- **`delegate_task` times out** — the delegated job can take minutes; raise
  `NOVA_OPENHANDS_TIMEOUT` (seconds) or use `check_task` with the returned id.
- **"App not installed"** — Android says this when a Nova is already on the phone
  that was signed with a *different* key (e.g. an older download built before the
  key was pinned). Uninstall the old Nova first, then install again:

  ```bash
  adb uninstall ai.nova.assistant      # or: Settings → Apps → Nova → Uninstall
  adb install -r android/app/build/outputs/apk/debug/app-debug.apk
  ```

  All builds now share one key (`android/nova-debug.keystore`), so this only
  happens once when moving off an older build. After that, updates install over
  the top.
- **APK won't install** — allow "install from unknown sources" for your file
  manager/browser, or use `adb install -r`. The APK is signed with the project's
  own key (`android/nova-debug.keystore`, password `android`), not your machine's
  auto-generated debug key — that is deliberate, so CI and local builds match.
- **Desktop app shows "offline"** — open Settings in the app and check the server
  URL/token, then hit **Test connection**. The tray icon keeps it running.
