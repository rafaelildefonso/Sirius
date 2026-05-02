"""Speech-to-Text using faster-whisper (local)."""

from __future__ import annotations

import io
import tempfile
from typing import Optional

import soundfile as sf


class SpeechToText:
    """Local STT using faster-whisper."""

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

    def _ensure_model(self):
        """Lazy-load the whisper model."""
        if self._model is not None:
            return

        try:
            from faster_whisper import WhisperModel

            print(f"Loading whisper model '{self.model_size}'...")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=None,  # Use default cache dir
            )
            self._initialized = True
            print("Whisper model loaded!")
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
