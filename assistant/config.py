"""Configuration, loaded from environment variables with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NOVA_DATA_DIR", ROOT / "data"))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
