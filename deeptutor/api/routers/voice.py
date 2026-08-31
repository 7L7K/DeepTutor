"""Voice endpoints — text-to-speech and speech-to-text.

These are thin HTTP surfaces over :mod:`deeptutor.services.voice`. Config comes
from the admin-managed model catalog (``services.tts`` / ``services.stt``), so
voice is shared infrastructure like embedding/search — any authenticated user
may call it; it is not gated by per-user LLM grants.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
import io
import logging
import wave

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota
from deeptutor.services.voice import (
    VoiceProviderError,
    synthesize_speech,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Guard against pathological uploads (the providers cap well below this anyway).
_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB, matching OpenAI's limit.
_MAX_TTS_TEXT_CHARS = 12_000
_VOICE_QUOTA_GLOBAL_KEY = "voice-provider-global"
_VOICE_USER_QUOTA = UserExecQuota(max_concurrent=1, max_per_minute=12)
_VOICE_GLOBAL_QUOTA = UserExecQuota(max_concurrent=4, max_per_minute=48)
_DEFAULT_PCM_SAMPLE_RATE = 24_000
_DEFAULT_PCM_CHANNELS = 1
_PCM16_SAMPLE_WIDTH = 2


class TTSRequest(BaseModel):
    """Text-to-speech request body."""

    text: str = Field(..., min_length=1, max_length=_MAX_TTS_TEXT_CHARS)
    voice: str | None = None
    format: str | None = None


def _parse_pcm_content_type(content_type: str) -> tuple[int, int] | None:
    """Return ``(sample_rate, channels)`` when a provider sent raw PCM audio."""
    media_type, *params = (content_type or "").split(";")
    if media_type.strip().lower() not in {"audio/pcm", "audio/x-pcm", "audio/l16"}:
        return None
    sample_rate = _DEFAULT_PCM_SAMPLE_RATE
    channels = _DEFAULT_PCM_CHANNELS
    for item in params:
        key, sep, value = item.strip().partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip().strip('"')
        try:
            parsed = int(value)
        except ValueError:
            continue
        if key in {"rate", "sample-rate", "samplerate"} and parsed > 0:
            sample_rate = parsed
        elif key in {"channels", "channel"} and parsed > 0:
            channels = parsed
    return sample_rate, channels


def _pcm16_to_wav(audio: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Wrap provider PCM16 bytes in a WAV container browsers can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(_PCM16_SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return buffer.getvalue()


@router.post("/tts")
async def text_to_speech(payload: TTSRequest) -> Response:
    """Synthesize ``text`` to audio using the active TTS provider."""
    async with AsyncExitStack() as quota_stack:
        try:
            user_lease = await _VOICE_USER_QUOTA.acquire(get_current_user().id)
            await quota_stack.enter_async_context(user_lease)
            global_lease = await _VOICE_GLOBAL_QUOTA.acquire(_VOICE_QUOTA_GLOBAL_KEY)
            await quota_stack.enter_async_context(global_lease)
        except QuotaExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Voice capacity is busy. Retry shortly.",
            ) from exc
        try:
            audio, content_type = await synthesize_speech(
                payload.text,
                voice=payload.voice,
                response_format=payload.format,
            )
        except ValueError as exc:  # missing/invalid configuration
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except VoiceProviderError as exc:
            logger.warning("TTS provider error: %s", exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        pcm_info = _parse_pcm_content_type(content_type)
        if pcm_info:
            sample_rate, channels = pcm_info
            audio = _pcm16_to_wav(audio, sample_rate=sample_rate, channels=channels)
            content_type = "audio/wav"
        return Response(
            content=audio,
            media_type=content_type,
            headers={"Cache-Control": "no-store"},
        )


@router.post("/stt")
async def speech_to_text(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict[str, str]:
    """Transcribe an uploaded audio clip using the active STT provider."""
    # Read only one byte past the provider limit so oversized multipart bodies
    # cannot be retained in full before we reject them.
    audio = await file.read(_MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio upload.")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio exceeds the 25 MB limit.",
        )
    async with AsyncExitStack() as quota_stack:
        try:
            user_lease = await _VOICE_USER_QUOTA.acquire(get_current_user().id)
            await quota_stack.enter_async_context(user_lease)
            global_lease = await _VOICE_GLOBAL_QUOTA.acquire(_VOICE_QUOTA_GLOBAL_KEY)
            await quota_stack.enter_async_context(global_lease)
        except QuotaExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Voice capacity is busy. Retry shortly.",
            ) from exc
        try:
            text = await transcribe_audio(
                audio,
                filename=file.filename or "audio.webm",
                content_type=file.content_type or "application/octet-stream",
                language=language,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except VoiceProviderError as exc:
            logger.warning("STT provider error: %s", exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"text": text}
