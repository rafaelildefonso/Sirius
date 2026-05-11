"""Audio recording and playback utilities."""

from __future__ import annotations

import io
import threading
import time
import wave
from typing import Callable, Optional

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
        
        # Audio level tracking for UI
        self._last_level_db = -60.0
        self._on_audio_level: Optional[Callable[[float], None]] = None

    def set_audio_level_callback(self, callback: Optional[Callable[[float], None]]) -> None:
        """Set callback for real-time audio level updates (0.0 to 1.0)."""
        self._on_audio_level = callback

    def _calculate_rms_db(self, audio: np.ndarray) -> float:
        """Calculate RMS level in dB."""
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-9:
            return -100.0
        return 20 * np.log10(rms)

    def _callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """Called for each audio block."""
        if status:
            print(f"Audio callback status: {status}")
        
        # Calculate and report audio level in real-time
        level_db = self._calculate_rms_db(indata)
        self._last_level_db = level_db
        level_normalized = max(0.0, min(1.0, (level_db + 60) / 60))  # Normalize -60dB to 0dB
        
        if self._on_audio_level:
            try:
                self._on_audio_level(level_normalized)
            except Exception:
                pass
        
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


class ContinuousAudioRecorder:
    """Continuous audio recorder with VAD (Voice Activity Detection).

    Keeps microphone always open, detects voice activity, and records
    when speech is detected.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        vad_threshold_db: float = -40.0,
        vad_debounce_ms: float = 300,
        silence_timeout_ms: float = 1500,
        buffer_duration_ms: float = 5000,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.vad_threshold_db = vad_threshold_db
        self.vad_debounce_ms = vad_debounce_ms
        self.silence_timeout_ms = silence_timeout_ms
        self.buffer_duration_ms = buffer_duration_ms

        # State
        self._running = False
        self._recording = False
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._callback_thread: Optional[threading.Thread] = None

        # Audio buffer (circular)
        self._buffer_lock = threading.Lock()
        self._audio_buffer: list[np.ndarray] = []
        self._max_buffer_frames = int((buffer_duration_ms / 1000.0) * sample_rate)

        # VAD state
        self._vad_active = False
        self._vad_start_time: Optional[float] = None
        self._last_voice_time: Optional[float] = None
        self._current_recording: list[np.ndarray] = []

        # Audio level tracking for UI meter
        self._last_level_db = -60.0

        # Callbacks
        self._on_vad_detected: Optional[Callable[[], None]] = None
        self._on_recording_complete: Optional[Callable[[bytes], None]] = None
        self._on_audio_level: Optional[Callable[[float], None]] = None

    def set_callbacks(
        self,
        on_vad_detected: Optional[Callable[[], None]] = None,
        on_recording_complete: Optional[Callable[[bytes], None]] = None,
        on_audio_level: Optional[Callable[[float], None]] = None,
    ) -> None:
        """Set callbacks for VAD events."""
        self._on_vad_detected = on_vad_detected
        self._on_recording_complete = on_recording_complete
        self._on_audio_level = on_audio_level

    def _calculate_rms_db(self, audio: np.ndarray) -> float:
        """Calculate RMS level in dB."""
        if audio.size == 0:
            return -100.0
        rms = np.sqrt(np.mean(audio ** 2))
        if rms == 0:
            return -100.0
        return 20 * np.log10(rms)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """Called for each audio block."""
        if status:
            print(f"Audio callback status: {status}")

        # Calculate audio level
        level_db = self._calculate_rms_db(indata)
        self._last_level_db = level_db  # Store for UI meter
        level_normalized = max(0.0, min(1.0, (level_db + 60) / 60))  # Normalize -60dB to 0dB

        if self._on_audio_level:
            try:
                self._on_audio_level(level_normalized)
            except Exception:
                pass

        with self._buffer_lock:
            # Add to circular buffer
            self._audio_buffer.append(indata.copy())
            total_samples = sum(f.shape[0] for f in self._audio_buffer)
            while total_samples > self._max_buffer_frames and self._audio_buffer:
                removed = self._audio_buffer.pop(0)
                total_samples -= removed.shape[0]

            # VAD logic
            current_time = time.time()
            is_voice = level_db > self.vad_threshold_db

            if is_voice:
                self._last_voice_time = current_time

                if not self._vad_active:
                    # Start of voice activity
                    if self._vad_start_time is None:
                        self._vad_start_time = current_time
                    elif (current_time - self._vad_start_time) * 1000 >= self.vad_debounce_ms:
                        # Debounce passed, confirm VAD
                        self._vad_active = True
                        self._recording = True
                        # Include pre-buffer
                        self._current_recording = self._audio_buffer.copy()
                        if self._on_vad_detected:
                            try:
                                self._on_vad_detected()
                            except Exception as e:
                                print(f"VAD callback error: {e}")
                else:
                    # Continue recording
                    self._current_recording.append(indata.copy())
            else:
                self._vad_start_time = None

                if self._vad_active:
                    # Check silence timeout
                    silence_duration = (current_time - self._last_voice_time) * 1000 if self._last_voice_time else 0

                    if silence_duration < self.silence_timeout_ms:
                        # Still recording during brief silence
                        self._current_recording.append(indata.copy())
                    else:
                        # Silence timeout, stop recording
                        self._vad_active = False
                        self._recording = False
                        self._process_recording()

    def _process_recording(self) -> None:
        """Process completed recording and trigger callback."""
        if not self._current_recording:
            return

        # Concatenate all frames
        audio_data = np.concatenate(self._current_recording, axis=0)
        self._current_recording = []

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
        wav_bytes = buffer.read()

        if self._on_recording_complete:
            try:
                self._on_recording_complete(wav_bytes)
            except Exception as e:
                print(f"Recording complete callback error: {e}")

    def start(self) -> None:
        """Start continuous recording with VAD."""
        if self._running:
            return

        self._running = True
        self._audio_buffer = []
        self._current_recording = []

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=int(self.sample_rate * 0.02),  # 20ms blocks
        )
        self._stream.start()
        print("Continuous audio recording started (VAD active)")

    def stop(self) -> None:
        """Stop continuous recording."""
        if not self._running:
            return

        self._running = False

        # Process any remaining recording
        if self._recording and self._current_recording:
            self._process_recording()

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._buffer_lock:
            self._audio_buffer = []
            self._current_recording = []

        print("Continuous audio recording stopped")

    def is_running(self) -> bool:
        """Check if continuous recording is active."""
        return self._running

    def is_recording(self) -> bool:
        """Check if currently recording (voice detected)."""
        return self._recording

    def set_vad_threshold(self, threshold_db: float) -> None:
        """Adjust VAD threshold dynamically."""
        self.vad_threshold_db = threshold_db


class ClapDetector:
    """Detects 2 claps pattern for wake-up from background mode.

    Pattern: 2 sharp sound peaks (claps) with 300-800ms interval.
    """

    def __init__(
        self,
        threshold_db: float = -20.0,
        min_clap_interval_ms: float = 300,
        max_clap_interval_ms: float = 800,
        clap_min_duration_ms: float = 50,
        clap_max_duration_ms: float = 150,
        required_claps: int = 2,
    ):
        self.threshold_db = threshold_db
        self.min_clap_interval_ms = min_clap_interval_ms
        self.max_clap_interval_ms = max_clap_interval_ms
        self.clap_min_duration_ms = clap_min_duration_ms
        self.clap_max_duration_ms = clap_max_duration_ms
        self.required_claps = required_claps

        # State
        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._callback: Optional[Callable[[], None]] = None
        self._debug = False

        # Clap detection state
        self._clap_count = 0
        self._last_clap_time: Optional[float] = None
        self._in_clap = False
        self._clap_start_time: Optional[float] = None
        self._reset_timer: Optional[threading.Timer] = None

        # Audio level tracking for UI meter
        self._last_level_db = -60.0

    def set_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for when clap pattern is detected."""
        self._callback = callback

    def set_debug(self, enabled: bool) -> None:
        """Enable/disable debug output showing audio levels."""
        self._debug = enabled

    def _print_debug_level(self, level_db: float, is_loud: bool) -> None:
        """Print audio level for debugging."""
        import sys
        bar_len = 40
        # Normalize for display: -60dB to 0dB range
        normalized = max(0.0, min(1.0, (level_db + 60) / 60))
        filled = int(normalized * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        marker = " <<< CLAP!" if is_loud else ""
        sys.stdout.write(f"\r[CLAP] {bar} {level_db:6.1f}dB{marker}")
        sys.stdout.flush()

    def _calculate_rms_db(self, audio: np.ndarray) -> float:
        """Calculate RMS level in dB."""
        if audio.size == 0:
            return -100.0
        rms = np.sqrt(np.mean(audio ** 2))
        if rms == 0:
            return -100.0
        return 20 * np.log10(rms)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """Called for each audio block."""
        if status:
            print(f"Clap detector status: {status}")

        level_db = self._calculate_rms_db(indata)
        self._last_level_db = level_db  # Store for UI meter
        current_time = time.time()

        # Check if we're in a clap (sound above threshold)
        is_loud = level_db > self.threshold_db

        # Debug output
        if self._debug:
            self._print_debug_level(level_db, is_loud)

        if is_loud:
            if not self._in_clap:
                # Start of potential clap
                self._in_clap = True
                self._clap_start_time = current_time
        else:
            if self._in_clap:
                # End of clap sound
                self._in_clap = False
                if self._clap_start_time:
                    clap_duration_ms = (current_time - self._clap_start_time) * 1000

                    # Validate clap duration (should be sharp and short)
                    if self.clap_min_duration_ms <= clap_duration_ms <= self.clap_max_duration_ms:
                        self._process_clap(current_time)

    def _process_clap(self, timestamp: float) -> None:
        """Process detected clap and check for pattern completion."""
        self._clap_count += 1
        # Clear debug line if active
        if self._debug:
            import sys
            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()
        print(f"👏 Palma #{self._clap_count} detectada")

        if self._clap_count >= self.required_claps:
            # Check timing with previous clap
            if self._last_clap_time:
                interval_ms = (timestamp - self._last_clap_time) * 1000

                if self.min_clap_interval_ms <= interval_ms <= self.max_clap_interval_ms:
                    # Valid pattern detected!
                    print(f"✅ Padrão de 2 palmas confirmado (intervalo: {interval_ms:.0f}ms)")
                    self._clap_count = 0
                    self._last_clap_time = None
                    if self._callback:
                        try:
                            self._callback()
                        except Exception as e:
                            print(f"Clap callback error: {e}")
                else:
                    # Interval too short or too long, reset
                    print(f"❌ Intervalo inválido ({interval_ms:.0f}ms), resetando")
                    self._clap_count = 1
                    self._last_clap_time = timestamp
            else:
                # First clap, wait for second
                self._last_clap_time = timestamp
                # Set timeout to reset if no second clap
                self._schedule_reset()

    def _schedule_reset(self) -> None:
        """Schedule reset of clap count if no second clap comes."""
        if self._reset_timer:
            self._reset_timer.cancel()

        reset_delay = (self.max_clap_interval_ms / 1000.0) + 0.1
        self._reset_timer = threading.Timer(reset_delay, self._reset_claps)
        self._reset_timer.start()

    def _reset_claps(self) -> None:
        """Reset clap detection state."""
        if self._clap_count > 0:
            print(f"⏱️ Timeout - resetando contador de palmas ({self._clap_count} palmas perdidas)")
        self._clap_count = 0
        self._last_clap_time = None

    def start(self) -> None:
        """Start clap detection."""
        if self._running:
            return

        self._running = True
        self._clap_count = 0
        self._last_clap_time = None

        self._stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=int(16000 * 0.02),  # 20ms blocks
        )
        self._stream.start()
        print("👂 Clap detector ativo (aguardando 2 palmas)")

    def stop(self) -> None:
        """Stop clap detection."""
        if not self._running:
            return

        self._running = False

        # Clear debug line if active
        if self._debug:
            import sys
            sys.stdout.write("\r" + " " * 70 + "\n")
            sys.stdout.flush()

        if self._reset_timer:
            self._reset_timer.cancel()
            self._reset_timer = None

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        self._clap_count = 0
        self._last_clap_time = None
        self._in_clap = False
        print("⏹️ Clap detector parado")

    def is_running(self) -> bool:
        """Check if clap detector is active."""
        return self._running


class ClapCalibrator:
    """Helper to record user claps and suggest optimal settings."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.claps: list[dict] = []
        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._in_clap = False
        self._clap_start_time = 0
        self._clap_peak_db = -100.0

    def _calculate_rms_db(self, audio: np.ndarray) -> float:
        if audio.size == 0: return -100.0
        rms = np.sqrt(np.mean(audio ** 2))
        return 20 * np.log10(rms) if rms > 0 else -100.0

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        level_db = self._calculate_rms_db(indata)
        current_time = time.time()

        # Simple threshold for calibration (not the final one)
        is_loud = level_db > -35.0

        if is_loud:
            if not self._in_clap:
                self._in_clap = True
                self._clap_start_time = current_time
                self._clap_peak_db = level_db
            else:
                self._clap_peak_db = max(self._clap_peak_db, level_db)
        else:
            if self._in_clap:
                self._in_clap = False
                duration_ms = (current_time - self._clap_start_time) * 1000
                if duration_ms > 10: # Filter out noise
                    self.claps.append({
                        "duration_ms": duration_ms,
                        "peak_db": self._clap_peak_db,
                        "timestamp": self._clap_start_time
                    })
                    print(f"Calibration: Clap recorded ({duration_ms:.0f}ms, {self._clap_peak_db:.1f}dB)")

    def start(self) -> None:
        self.claps = []
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=int(self.sample_rate * 0.01) # 10ms
        )
        self._stream.start()

    def stop(self) -> dict:
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        if not self.claps:
            return {}

        # Calculate averages
        avg_peak = sum(c['peak_db'] for c in self.claps) / len(self.claps)
        avg_dur = sum(c['duration_ms'] for c in self.claps) / len(self.claps)
        
        # Calculate intervals if > 1 clap
        intervals = []
        for i in range(1, len(self.claps)):
            intervals.append((self.claps[i]['timestamp'] - self.claps[i-1]['timestamp']) * 1000)
        
        avg_interval = sum(intervals) / len(intervals) if intervals else 500

        # Suggested settings:
        # Threshold: 10dB below average peak
        # Duration: avg +/- 50%
        # Interval: avg +/- 200ms
        return {
            "threshold_db": round(avg_peak - 8, 1),
            "clap_min_duration_ms": max(20, round(avg_dur * 0.5, 0)),
            "clap_max_duration_ms": round(avg_dur * 2.0, 0),
            "min_clap_interval_ms": max(150, round(avg_interval - 200, 0)),
            "max_clap_interval_ms": round(avg_interval + 200, 0),
            "count": len(self.claps)
        }
