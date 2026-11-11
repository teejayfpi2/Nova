"""Speech in and speech out.

Both directions degrade gracefully so the assistant still runs when optional
packages are missing:

STT  : OpenAI Whisper API -> faster-whisper -> openai-whisper -> vosk
TTS  : edge-tts -> OpenAI TTS API -> pyttsx3 -> macOS `say` -> espeak-ng
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from .config import settings
from .llm import LLMClient, USER_AGENT


class VoiceError(RuntimeError):
    pass


def _which(*names: str) -> str | None:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def ffmpeg_available() -> bool:
    return _which("ffmpeg") is not None


def convert_to_wav(data: bytes, suffix: str = ".webm") -> bytes:
    """Convert arbitrary audio bytes to 16 kHz mono WAV using ffmpeg."""
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        raise VoiceError("ffmpeg is required to convert audio but is not installed")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(data)
        src_path = src.name
    out_path = src_path + ".wav"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", src_path, "-ar", "16000", "-ac", "1", out_path],
            capture_output=True,
            timeout=120,
            check=True,
        )
        with open(out_path, "rb") as fh:
            return fh.read()
    finally:
        for p in (src_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


@dataclass
class Transcription:
    text: str
    backend: str


class SpeechToText:
    def __init__(self, backend: str | None = None, llm: LLMClient | None = None) -> None:
        self.backend = backend or settings.stt_backend
        self.llm = llm or LLMClient()
        self._local = None  # lazily loaded model

    def available_backends(self) -> list[str]:
        found: list[str] = []
        if self._has_credentials():
            found.append("openai")
        if _importable("faster_whisper"):
            found.append("faster-whisper")
        if _importable("whisper"):
            found.append("whisper")
        if _importable("vosk"):
            found.append("vosk")
        return found

    def _has_credentials(self) -> bool:
        return bool(self.llm.api_key) or self.llm._managed is not None  # noqa: SLF001

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> Transcription:
        backend = self._pick()
        if backend == "openai":
            return Transcription(self._openai(audio, suffix), "openai")
        wav = convert_to_wav(audio, suffix) if suffix not in {".wav"} else audio
        if backend in {"faster-whisper", "whisper"}:
            return Transcription(self._whisper(wav, backend), backend)
        if backend == "vosk":
            return Transcription(self._vosk(wav), "vosk")
        raise VoiceError(
            "No speech-to-text backend available. Install one with "
            "`pip install faster-whisper` or set an OpenAI-compatible API key."
        )

    def _pick(self) -> str:
        if self.backend != "auto":
            return self.backend
        found = self.available_backends()
        if not found:
            raise VoiceError("no speech-to-text backend found")
        return found[0]

    def _openai(self, audio: bytes, suffix: str) -> str:
        import json
        import urllib.request

        boundary = "----novaform"
        parts: list[bytes] = []

        def field(name: str, value: str) -> None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )

        field("model", "whisper-1")
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="audio{suffix}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
        )
        parts.append(audio)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {self.llm._auth_key()}",  # noqa: SLF001
            "User-Agent": USER_AGENT,
        }
        req = urllib.request.Request(
            f"{self.llm.base_url}/audio/transcriptions", data=body, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode()).get("text", "").strip()
        except Exception as exc:  # noqa: BLE001
            raise VoiceError(f"OpenAI transcription failed: {exc}") from exc

    def _whisper(self, wav: bytes, backend: str) -> str:
        if self._local is None:
            if backend == "faster-whisper":
                from faster_whisper import WhisperModel

                self._local = ("faster-whisper", WhisperModel(settings.whisper_model))
            else:
                import whisper

                self._local = ("whisper", whisper.load_model(settings.whisper_model))

        kind, model = self._local
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            fh.write(wav)
            path = fh.name
        try:
            if kind == "faster-whisper":
                segments, _ = model.transcribe(path, language="en")
                return " ".join(seg.text for seg in segments).strip()
            return model.transcribe(path).get("text", "").strip()
        finally:
            os.unlink(path)

    def _vosk(self, wav: bytes) -> str:
        import json
        import wave

        from vosk import KaldiRecognizer, Model

        if self._local is None:
            self._local = Model(lang="en-us")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            fh.write(wav)
            path = fh.name
        try:
            with wave.open(path, "rb") as wf:
                rec = KaldiRecognizer(self._local, wf.getframerate())
                rec.SetWords(True)
                results = []
                while True:
                    data = wf.readframes(4000)
                    if not data:
                        break
                    if rec.AcceptWaveform(data):
                        results.append(json.loads(rec.Result()).get("text", ""))
                results.append(json.loads(rec.FinalResult()).get("text", ""))
            return " ".join(r for r in results if r).strip()
        finally:
            os.unlink(path)


class TextToSpeech:
    def __init__(self, backend: str | None = None, llm: LLMClient | None = None) -> None:
        self.backend = backend or settings.tts_backend
        self.llm = llm or LLMClient()
        self.voice = settings.tts_voice

    def available_backends(self) -> list[str]:
        found: list[str] = []
        if _importable("edge_tts"):
            found.append("edge-tts")
        if self._has_credentials():
            found.append("openai")
        if _importable("pyttsx3"):
            found.append("pyttsx3")
        if _which("say"):
            found.append("say")
        if _which("espeak-ng", "espeak"):
            found.append("espeak")
        return found

    def _has_credentials(self) -> bool:
        return bool(self.llm.api_key) or self.llm._managed is not None  # noqa: SLF001

    def synthesize(self, text: str) -> tuple[bytes, str]:
        """Return (audio_bytes, mime_type)."""
        backend = self._pick()
        if backend == "edge-tts":
            return self._edge(text), "audio/mpeg"
        if backend == "openai":
            return self._openai(text), "audio/mpeg"
        if backend == "pyttsx3":
            return self._pyttsx3(text), "audio/wav"
        if backend == "say":
            return self._say(text), "audio/aiff"
        if backend == "espeak":
            return self._espeak(text), "audio/wav"
        raise VoiceError("No text-to-speech backend available")

    def _pick(self) -> str:
        if self.backend != "auto":
            return self.backend
        found = self.available_backends()
        if not found:
            raise VoiceError("no text-to-speech backend found")
        return found[0]

    def _edge(self, text: str) -> bytes:
        import edge_tts

        async def run() -> bytes:
            communicate = edge_tts.Communicate(text, self.voice)
            buf = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            return bytes(buf)

        return asyncio.run(run())

    def _openai(self, text: str) -> bytes:
        import json
        import urllib.request

        body = json.dumps(
            {"model": "tts-1", "input": text, "voice": "alloy", "response_format": "mp3"}
        ).encode()
        req = urllib.request.Request(
            f"{self.llm.base_url}/audio/speech",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.llm._auth_key()}",  # noqa: SLF001
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            raise VoiceError(f"OpenAI TTS failed: {exc}") from exc

    def _pyttsx3(self, text: str) -> bytes:
        import pyttsx3

        engine = pyttsx3.init()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            path = fh.name
        engine.save_to_file(text, path)
        engine.runAndWait()
        with open(path, "rb") as fh:
            data = fh.read()
        os.unlink(path)
        return data

    def _say(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as fh:
            path = fh.name
        subprocess.run(["say", "-o", path, text], check=True, timeout=120)
        with open(path, "rb") as fh:
            data = fh.read()
        os.unlink(path)
        return data

    def _espeak(self, text: str) -> bytes:
        exe = _which("espeak-ng", "espeak")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            path = fh.name
        subprocess.run([exe, "-w", path, text], check=True, timeout=120)
        with open(path, "rb") as fh:
            data = fh.read()
        os.unlink(path)
        return data


def _importable(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None
