"""
System sounds for SIRIUS.

Plays short .wav feedback sounds (e.g. startup chime) without going
through the TTS pipeline or the UI audio-chunk callback.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

_BASE_DIR = Path(__file__).resolve().parent.parent
INIT_SOUND = "init_sound.wav"
_INIT_GAIN = 0.25  # soft volume — startup chime shouldn't startle anyone


def _resolve_sound_path(name: str) -> Path | None:
    """Locate a bundled sound file (dev tree or PyInstaller onefile)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / name)
        candidates.append(Path(sys.executable).parent / name)
    candidates.append(_BASE_DIR / name)
    for p in candidates:
        if p.is_file():
            return p
    return None


def _play_wav(path: Path) -> None:
    """Decode a wav file and play it via sounddevice (blocking)."""
    import miniaudio

    decoded = miniaudio.decode(
        path.read_bytes(),
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
    )
    samples = np.array(decoded.samples, dtype=np.float32) * _INIT_GAIN
    sd.play(samples, decoded.sample_rate)
    sd.wait()


def play_init_sound() -> None:
    """Play the startup sound if enabled. Never raises."""
    try:
        from memory.config_manager import get_init_sound_enabled

        if not get_init_sound_enabled():
            return
        path = _resolve_sound_path(INIT_SOUND)
        if path is None:
            print(f"[SIRIUS] Init sound not found: {INIT_SOUND}")
            return
        _play_wav(path)
    except Exception as e:
        print(f"[SIRIUS] Init sound failed: {e}")


def play_init_sound_async() -> None:
    """Play the startup sound in a daemon thread (non-blocking)."""
    threading.Thread(target=play_init_sound, daemon=True).start()
