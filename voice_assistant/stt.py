"""Speech-to-Text using faster-whisper (local)."""

from __future__ import annotations

import io
import tempfile
from typing import Optional

import soundfile as sf

from voice_assistant.cache import model_cache


class SpeechToText:
    """Local STT using faster-whisper with model caching."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: Optional[str] = "pt",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self._initialized = False

    def _load_model(self):
        """Actually load the model (called by cache)."""
        from faster_whisper import WhisperModel
        print(f"Loading whisper model '{self.model_size}'...")
        model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            download_root=None,
        )
        print("Whisper model loaded!")
        return model

    def _ensure_model(self):
        """Lazy-load the whisper model with caching."""
        if self._model is not None:
            return

        # Use global model cache
        cache_key = f"whisper_{self.model_size}_{self.device}_{self.compute_type}"
        try:
            self._model = model_cache.get_model(cache_key, self._load_model)
            self._initialized = True
        except Exception as e:
            print(f"Failed to load whisper model: {e}")
            raise

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes to text."""
        self._ensure_model()

        if not audio_bytes:
            return ""

        try:
            # Write to temp file (faster-whisper needs file path)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # Transcribe
            segments, info = self._model.transcribe(
                tmp_path,
                language=self.language,
                beam_size=5,
                best_of=5,
                condition_on_previous_text=True,
            )

            # Collect all text
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            # Cleanup temp file
            import os
            os.unlink(tmp_path)

            return " ".join(text_parts).strip()

        except Exception as e:
            print(f"Transcription error: {e}")
            return ""

    def health(self) -> bool:
        """Check if STT is working."""
        try:
            self._ensure_model()
            return self._initialized
        except Exception:
            return False
