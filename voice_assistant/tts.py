"""Text-to-Speech using Kokoro (local)."""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
import soundfile as sf

from voice_assistant.cache import model_cache


class TextToSpeech:
    """Local TTS using Kokoro with model caching."""

    def __init__(
        self,
        voice_id: str = "af_bella",
        speed: float = 1.0,
        lang_code: str = "a",  # 'a' for American English, 'b' for British
    ):
        self.voice_id = voice_id
        self.speed = speed
        self.lang_code = lang_code
        self._pipeline = None
        self._initialized = False

    def _load_pipeline(self):
        """Actually load the pipeline (called by cache)."""
        from kokoro import KPipeline
        print("Loading Kokoro TTS pipeline...")
        pipeline = KPipeline(lang_code=self.lang_code)
        print("Kokoro TTS loaded!")
        return pipeline

    def _ensure_pipeline(self):
        """Lazy-load kokoro pipeline with caching."""
        if self._pipeline is not None:
            return

        # Use global model cache
        cache_key = f"kokoro_{self.lang_code}"
        try:
            self._pipeline = model_cache.get_model(cache_key, self._load_pipeline)
            self._initialized = True
        except Exception as e:
            print(f"Failed to load Kokoro: {e}")
            raise

    def synthesize(self, text: str) -> Optional[bytes]:
        """Synthesize text to audio bytes (WAV format)."""
        if not text or not text.strip():
            return None

        self._ensure_pipeline()

        try:
            # Generate audio
            audio_chunks = []
            generator = self._pipeline(text, voice=self.voice_id, speed=self.speed)

            for _, _, audio in generator:
                audio_chunks.append(audio)

            if not audio_chunks:
                return None

            # Concatenate audio
            combined = np.concatenate(audio_chunks)

            # Convert to WAV bytes
            buffer = io.BytesIO()
            sf.write(buffer, combined, 24000, format="WAV")
            buffer.seek(0)

            return buffer.read()

        except Exception as e:
            print(f"TTS synthesis error: {e}")
            return None

    def list_voices(self) -> list[str]:
        """List available voice IDs."""
        return [
            "af_bella",  # American female
            "af_heart",  # American female (warm)
            "am_adam",   # American male
            "am_michael", # American male
            "bf_emma",   # British female
            "bm_george", # British male
        ]

    def set_voice(self, voice_id: str) -> None:
        """Change voice."""
        if voice_id in self.list_voices():
            self.voice_id = voice_id

    def health(self) -> bool:
        """Check if TTS is working."""
        try:
            self._ensure_pipeline()
            return self._initialized
        except Exception:
            return False
