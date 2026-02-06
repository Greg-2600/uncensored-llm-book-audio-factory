from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from .settings import settings


class LocalTTSError(RuntimeError):
    pass


_model_lock = asyncio.Lock()
_model: Optional[Any] = None


def _resolve_speaker(model: Any, voice: str | None) -> str | None:
    if not voice:
        return None
    speakers = getattr(model, "speakers", None)
    if not speakers:
        return None
    if voice in speakers:
        return voice
    lower = voice.lower()
    for speaker in speakers:
        if str(speaker).lower() == lower:
            return str(speaker)
    return None


def _ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise LocalTTSError("ffmpeg is required for audio output")


def convert_mp3_to_m4b(*, mp3_path: Path, m4b_path: Path) -> None:
    if m4b_path.exists():
        return
    _ensure_ffmpeg()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mp3_path),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(m4b_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise LocalTTSError("ffmpeg failed to create m4b")


def _synthesize_sync(*, text: str, voice: str | None, speed: float, fmt: str) -> bytes:
    global _model
    if _model is None:
        try:
            from TTS.api import TTS
        except Exception as exc:  # noqa: BLE001
            raise LocalTTSError("Coqui TTS is not installed") from exc
        _model = TTS(model_name=settings.local_tts_model, progress_bar=False, gpu=False)

    speaker = _resolve_speaker(_model, voice) or settings.local_tts_default_voice

    _ensure_ffmpeg()
    speed = max(0.5, min(2.0, speed))

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "tts.wav"
        out_path = Path(tmpdir) / f"tts.{fmt}"

        kwargs = {}
        if speaker:
            kwargs["speaker"] = speaker

        _model.tts_to_file(text=text, file_path=str(wav_path), **kwargs)

        if fmt == "mp3":
            codec = "libmp3lame"
            extra = ["-q:a", "2"]
        elif fmt == "m4b":
            codec = "aac"
            extra = ["-b:a", "128k"]
        else:
            raise LocalTTSError("Unsupported audio format")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-filter:a",
            f"atempo={speed}",
            "-vn",
            "-c:a",
            codec,
            *extra,
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise LocalTTSError("ffmpeg failed to create audio")

        return out_path.read_bytes()


async def synthesize_speech(
    *,
    text: str,
    voice: str | None,
    speed: float,
    format: str = "mp3",
) -> bytes:
    return await asyncio.to_thread(
        _synthesize_sync,
        text=text,
        voice=voice,
        speed=speed,
        fmt=format,
    )
