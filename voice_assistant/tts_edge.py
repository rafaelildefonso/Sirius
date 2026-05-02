"""Edge TTS - Microsoft neural voices (online but free)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Optional


class EdgeTTS:
    """Microsoft Edge TTS - high quality neural voices."""

    # Available Portuguese voices
    VOICES_PT_BR = {
        "feminine": "pt-BR-FranciscaNeural",      # Feminine
        "masculine": "pt-BR-AntonioNeural",       # Masculine - natural!
        "thaís": "pt-BR-ThalitaMultilingualNeural",
        "leticia": "pt-BR-LeticiaNeural",
    }

    VOICES_PT_PT = {
        "feminine": "pt-PT-RaquelNeural",
        "masculine": "pt-PT-DuarteNeural",
    }

    def __init__(self, voice: str = "pt-BR-AntonioNeural", rate: str = "+0%"):
        self.voice = voice
        self.rate = rate  # Speed: "-50%" (slower) to "+50%" (faster)
        self._initialized = False

    def _ensure_setup(self):
        """Check edge-tts is available."""
        if self._initialized:
            return

        try:
            import edge_tts
            self._initialized = True
        except ImportError:
            raise RuntimeError("edge_tts not installed. Run: uv pip install edge-tts")

    async def _synthesize_async(self, text: str, output_file: str) -> None:
        """Async synthesis."""
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        await communicate.save(output_file)

    def synthesize(self, text: str) -> Optional[bytes]:
        """Synthesize text to audio bytes (MP3 format)."""
        if not text or not text.strip():
            return None

        self._ensure_setup()

        try:
            # Create temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            # Run async
            asyncio.run(self._synthesize_async(text, tmp_path))

            # Read back
            with open(tmp_path, 'rb') as f:
                audio_bytes = f.read()

            # Cleanup
            Path(tmp_path).unlink()

            return audio_bytes

        except Exception as e:
            print(f"Edge TTS error: {e}")
            return None

    def play_direct(self, text: str) -> None:
        """Synthesize and play directly."""
        import io

        audio = self.synthesize(text)
        if audio:
            # Play MP3
            try:
                from voice_assistant.audio import play_audio
                play_audio(audio)
            except Exception:
                # Fallback: save and use system player
                import tempfile
                import os
                import subprocess

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio)
                    tmp_path = tmp.name

                # Play with default player
                os.startfile(tmp_path)

    def set_voice(self, voice_name: str) -> None:
        """Set voice by name."""
        if voice_name in self.VOICES_PT_BR:
            self.voice = self.VOICES_PT_BR[voice_name]
        elif voice_name in self.VOICES_PT_PT:
            self.voice = self.VOICES_PT_PT[voice_name]
        else:
            # Assume it's a direct voice ID
            self.voice = voice_name

    def health(self) -> bool:
        """Check if Edge TTS is available."""
        try:
            self._ensure_setup()
            return self._initialized
        except Exception:
            return False

    def list_voices(self) -> list[str]:
        """List available voice options."""
        return [
            "masculine (pt-BR-AntonioNeural)",
            "feminine (pt-BR-FranciscaNeural)",
            "masculine_pt (pt-PT-DuarteNeural)",
            "feminine_pt (pt-PT-RaquelNeural)",
        ]
