"""Alternative Speech-to-Text using openai-whisper (fallback)."""

from __future__ import annotations

import io
import tempfile
from typing import Optional

import numpy as np


class WhisperSTT:
    """Local STT using OpenAI's base whisper (slower but more compatible)."""

    def __init__(
        self,
        model_size: str = "base",
        language: Optional[str] = "pt",
    ):
        self.model_size = model_size
        self.language = language
        self._model = None
        self._initialized = False

    def _ensure_model(self):
        """Lazy-load the whisper model."""
        if self._model is not None:
            return

        try:
            import whisper

            print(f"Loading whisper model '{self.model_size}'...")
            self._model = whisper.load_model(self.model_size)
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
            import whisper
            import soundfile as sf

            # Load audio from bytes
            buffer = io.BytesIO(audio_bytes)
            audio_array, sample_rate = sf.read(buffer, dtype=np.float32)

            # Ensure mono
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)

            # Transcribe
            result = self._model.transcribe(
                audio_array,
                language=self.language,
                fp16=False,  # CPU only
            )

            return result.get("text", "").strip()

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


class SpeechRecognitionSTT:
    """STT using speech_recognition with Google API (requires internet)."""

    def __init__(self, language: str = "pt-BR"):
        self.language = language
        self._initialized = False

    def _ensure_setup(self):
        """Setup speech recognition."""
        if self._initialized:
            return

        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._initialized = True
        except Exception as e:
            print(f"Failed to setup speech_recognition: {e}")
            raise

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe using Google Speech API."""
        self._ensure_setup()

        try:
            import speech_recognition as sr

            # Load audio
            audio_data = sr.AudioData(audio_bytes, 16000, 2)

            # Recognize
            text = self._recognizer.recognize_google(
                audio_data,
                language=self.language,
            )
            return text

        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"Google API error: {e}")
            return ""
        except Exception as e:
            print(f"Transcription error: {e}")
            return ""

    def health(self) -> bool:
        """Check if STT is working."""
        try:
            self._ensure_setup()
            return self._initialized
        except Exception:
            return False


# Default to Whisper base
try:
    from whisper import load_model
    DefaultSTT = WhisperSTT
except ImportError:
    try:
        from faster_whisper import WhisperModel
        from voice_assistant.stt import SpeechToText as DefaultSTT
    except ImportError:
        DefaultSTT = SpeechRecognitionSTT
