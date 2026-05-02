"""Text-to-Speech using Kokoro (local)."""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
import soundfile as sf


class TextToSpeech:
    """Local TTS using Kokoro (open source)."""

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

    def _ensure_pipeline(self):
        """Lazy-load kokoro pipeline."""
        if self._pipeline is not None:
            return

        try:
            from kokoro import KPipeline

            print("Loading Kokoro TTS pipeline...")
            self._pipeline = KPipeline(lang_code=self.lang_code)
            self._initialized = True
            print("Kokoro TTS loaded!")
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
