"""Audio recording and playback utilities."""

from __future__ import annotations

import io
import threading
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioRecorder:
    """Records audio from microphone until stopped."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None

    def _callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """Called for each audio block."""
        if status:
            print(f"Audio callback status: {status}")
        if self._recording:
            self._frames.append(indata.copy())

    def start(self) -> None:
        """Start recording audio."""
        self._recording = True
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.float32,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> bytes:
        """Stop recording and return audio as WAV bytes."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return b""

        # Concatenate all frames
        audio_data = np.concatenate(self._frames, axis=0)

        # Convert to WAV bytes
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self.sample_rate)
            # Convert float32 to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())

        buffer.seek(0)
        return buffer.read()

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording


def play_audio(audio_bytes: bytes, sample_rate: int = 24000) -> None:
    """Play audio from WAV bytes."""
    try:
        # Try sounddevice first (lighter)
        buffer = io.BytesIO(audio_bytes)
        data, sr = sf.read(buffer, dtype=np.float32)
        sd.play(data, sr)
        sd.wait()
    except Exception as e:
        print(f"Error playing audio: {e}")
        # Fallback to pygame
        try:
            import pygame
            pygame.mixer.init(frequency=sample_rate)
            buffer = io.BytesIO(audio_bytes)
            pygame.mixer.music.load(buffer)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                import time
                time.sleep(0.1)
        except Exception as e2:
            print(f"Fallback audio playback failed: {e2}")
