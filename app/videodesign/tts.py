import uuid
import wave
from pathlib import Path

from app.videodesign.audio import measure_audio_duration
from app.videodesign.config import settings
from app.videodesign.errors import TTS_GENERATION_FAILED, TTS_PROVIDER_UNAVAILABLE, VideoDesignError
from app.videodesign.planner import estimate_duration, make_caption_chunks
from app.videodesign.schemas import CaptionChunk


class TTSResult:
    def __init__(self, audio_path: Path, duration_seconds: float, caption_chunks: list[CaptionChunk]):
        self.audio_path = audio_path
        self.duration_seconds = duration_seconds
        self.caption_chunks = caption_chunks


class TTSClient:
    async def generate(self, text: str, project_id: str, scene_id: str, provider: str, voice_id: str) -> TTSResult:
        storage_dir = settings.storage_dir / project_id / "audio"
        storage_dir.mkdir(parents=True, exist_ok=True)
        if provider in ("free_tts", "edge_tts"):
            return await self._edge_tts(text, storage_dir, scene_id, voice_id)
        if provider == "timing_only":
            return self._timing_only(text, storage_dir, scene_id)
        raise VideoDesignError(TTS_PROVIDER_UNAVAILABLE, f"TTS provider is not supported: {provider}")

    async def _edge_tts(self, text: str, storage_dir: Path, scene_id: str, voice_id: str) -> TTSResult:
        try:
            import edge_tts
        except ImportError as exc:
            raise VideoDesignError(
                TTS_PROVIDER_UNAVAILABLE,
                "Install edge-tts or use provider='timing_only' for tests.",
                retryable=False,
            ) from exc

        audio_path = storage_dir / f"{scene_id}_{uuid.uuid4().hex}.mp3"
        try:
            communicate = edge_tts.Communicate(text, voice_id or settings.tts_voice_id)
            await communicate.save(str(audio_path))
        except Exception as exc:
            raise VideoDesignError(TTS_GENERATION_FAILED, f"TTS generation failed: {exc}", retryable=True) from exc
        duration = measure_audio_duration(audio_path) or estimate_duration(text)
        return TTSResult(audio_path=audio_path, duration_seconds=duration, caption_chunks=make_caption_chunks(text, duration))

    def _timing_only(self, text: str, storage_dir: Path, scene_id: str) -> TTSResult:
        duration = estimate_duration(text)
        audio_path = storage_dir / f"{scene_id}_{uuid.uuid4().hex}.wav"
        sample_rate = 8000
        frame_count = int(duration * sample_rate)
        with wave.open(str(audio_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(b"\x00\x00" * frame_count)
        duration = measure_audio_duration(audio_path) or duration
        return TTSResult(audio_path=audio_path, duration_seconds=duration, caption_chunks=make_caption_chunks(text, duration))
