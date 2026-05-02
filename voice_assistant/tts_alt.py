"""Alternative TTS implementations (fallbacks)."""

from __future__ import annotations

import io
from typing import Optional


class Pyttsx3TTS:
    """TTS using pyttsx3 (Windows native, no internet required)."""

    def __init__(self, voice_id: Optional[str] = None, rate: int = 180):
        self.voice_id = voice_id
        self.rate = rate
        self._engine = None
        self._initialized = False

    def _ensure_engine(self):
        """Initialize TTS engine."""
        if self._engine is not None:
            return

        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            self._engine.setProperty('rate', self.rate)

            if self.voice_id:
                voices = self._engine.getProperty('voices')
                for voice in voices:
                    if self.voice_id in voice.id:
                        self._engine.setProperty('voice', voice.id)
                        break

            self._initialized = True
        except Exception as e:
            print(f"Failed to initialize pyttsx3: {e}")
            raise

    def synthesize(self, text: str) -> Optional[bytes]:
        """Synthesize text to audio.

        Note: pyttsx3 plays directly, so we save to file and read back.
        """
        if not text or not text.strip():
            return None

        self._ensure_engine()

        try:
            import tempfile

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            self._engine.save_to_file(text, tmp_path)
            self._engine.runAndWait()

            # Read back
            with open(tmp_path, 'rb') as f:
                audio_bytes = f.read()

            # Cleanup
            import os
            os.unlink(tmp_path)

            return audio_bytes

        except Exception as e:
            print(f"TTS synthesis error: {e}")
            return None

    def play_direct(self, text: str) -> None:
        """Play text directly without returning bytes."""
        if not text or not text.strip():
            return

        self._ensure_engine()

        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as e:
            print(f"TTS play error: {e}")

    def list_voices(self) -> list[dict]:
        """List available voices."""
        try:
            self._ensure_engine()
            voices = self._engine.getProperty('voices')
            return [
                {"id": v.id, "name": v.name, "languages": v.languages}
                for v in voices
            ]
        except Exception:
            return []

    def set_voice(self, voice_id: str) -> None:
        """Change voice."""
        self.voice_id = voice_id
        if self._engine:
            try:
                self._engine.setProperty('voice', voice_id)
            except Exception as e:
                print(f"Failed to set voice: {e}")

    def health(self) -> bool:
        """Check if TTS is working."""
        try:
            self._ensure_engine()
            return self._initialized
        except Exception:
            return False


class WindowsNativeTTS:
    """TTS using Windows SAPI directly via comtypes."""

    def __init__(self):
        self._speaker = None
        self._initialized = False

    def _ensure_speaker(self):
        """Initialize SAPI."""
        if self._speaker is not None:
            return

        try:
            import comtypes.client

            self._speaker = comtypes.client.Dispatch("SAPI.SpVoice")
            self._initialized = True
        except Exception as e:
            print(f"Failed to initialize SAPI: {e}")
            raise

    def play_direct(self, text: str) -> None:
        """Play text directly."""
        if not text or not text.strip():
            return

        self._ensure_speaker()

        try:
            self._speaker.Speak(text)
        except Exception as e:
            print(f"SAPI speak error: {e}")

    def health(self) -> bool:
        """Check if TTS is working."""
        try:
            self._ensure_speaker()
            return self._initialized
        except Exception:
            return False


# Try to use best available TTS
def get_best_tts():
    """Return the best available TTS class."""
    # Try Kokoro first (best quality)
    try:
        from voice_assistant.tts import TextToSpeech
        test = TextToSpeech()
        test._ensure_pipeline()
        return TextToSpeech
    except Exception:
        pass

    # Try pyttsx3 (Windows native)
    try:
        import pyttsx3
        return Pyttsx3TTS
    except ImportError:
        pass

    # Fallback to Windows SAPI
    return WindowsNativeTTS


DefaultTTS = get_best_tts()
