"""Configuration, loaded from environment variables with sane defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from ``.env`` in the project root into the environment.

    Real environment variables win, so ``NOVA_PORT=9000`` set in the shell still
    overrides the file. This gives Windows users the same convenience as the
    ``export`` lines in the README, without needing shell-specific syntax.
    """
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

DATA_DIR = Path(os.environ.get("NOVA_DATA_DIR", ROOT / "data"))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_json(name: str) -> dict[str, str]:
    raw = os.environ.get(name, "")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


@dataclass
class Settings:
    # --- LLM ---
    # Any OpenAI-compatible endpoint works: OpenAI, Groq, Together, Ollama,
    # LM Studio, vLLM, OpenRouter, or the OpenHands LLM proxy.
    llm_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "NOVA_LLM_BASE_URL", "https://api.openai.com/v1"
        )
    )
    llm_api_key: str = field(
        default_factory=lambda: os.environ.get("NOVA_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("NOVA_LLM_MODEL", "gpt-4o-mini")
    )
    # Extra headers, as JSON. Used by the OpenHands agent server, which
    # authenticates with X-Session-API-Key instead of a Bearer token.
    llm_headers: dict[str, str] = field(
        default_factory=lambda: _env_json("NOVA_LLM_HEADERS")
    )
    llm_timeout: float = field(
        default_factory=lambda: float(os.environ.get("NOVA_LLM_TIMEOUT", "120"))
    )
    temperature: float = field(
        default_factory=lambda: float(os.environ.get("NOVA_TEMPERATURE", "0.3"))
    )

    # --- Server ---
    host: str = field(default_factory=lambda: os.environ.get("NOVA_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("NOVA_PORT", "8000")))
    auth_token: str = field(
        default_factory=lambda: os.environ.get("NOVA_AUTH_TOKEN", "")
    )

    # --- Voice ---
    # "auto" picks the best backend available on this machine.
    stt_backend: str = field(
        default_factory=lambda: os.environ.get("NOVA_STT_BACKEND", "auto")
    )
    tts_backend: str = field(
        default_factory=lambda: os.environ.get("NOVA_TTS_BACKEND", "auto")
    )
    whisper_model: str = field(
        default_factory=lambda: os.environ.get("NOVA_WHISPER_MODEL", "base")
    )
    tts_voice: str = field(
        default_factory=lambda: os.environ.get("NOVA_TTS_VOICE", "en-US-AriaNeural")
    )

    # --- Agent behaviour ---
    max_steps: int = field(
        default_factory=lambda: int(os.environ.get("NOVA_MAX_STEPS", "12"))
    )
    device_control: bool = field(
        default_factory=lambda: _env_flag("NOVA_DEVICE_CONTROL", True)
    )
    shell_enabled: bool = field(
        default_factory=lambda: _env_flag("NOVA_SHELL", True)
    )
    data_dir: Path = field(default_factory=lambda: DATA_DIR)

    @property
    def has_llm(self) -> bool:
        # A local server (Ollama) may not need a key.
        return bool(self.llm_api_key) or "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
