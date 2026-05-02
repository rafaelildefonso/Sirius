"""Main voice assistant application."""

from __future__ import annotations

import random
import sys
import threading
import time
import queue
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit('\\', 2)[0])

from voice_assistant.audio import AudioRecorder, play_audio
from voice_assistant.llm import OllamaClient
from voice_assistant.hotkey import PushToTalkHandler
from voice_assistant.ui import VoiceAssistantUI

# Try to import best available STT/TTS (without testing at import time)
stt_module = None
try:
    from voice_assistant.stt import SpeechToText
    stt_module = SpeechToText
except Exception:
    try:
        from voice_assistant.stt_alt import WhisperSTT
        stt_module = WhisperSTT
    except Exception:
        from voice_assistant.stt_alt import SpeechRecognitionSTT
        stt_module = SpeechRecognitionSTT

tts_module = None
try:
    # Try Edge TTS first (best quality, male voice available)
    from voice_assistant.tts_edge import EdgeTTS
    _test = EdgeTTS()
    _test._ensure_setup()
    tts_module = EdgeTTS
    print("Using Microsoft Edge TTS (neural voices)")
except Exception as e:
    print(f"Edge TTS not available: {e}")
    try:
        from voice_assistant.tts import TextToSpeech
        tts_module = TextToSpeech
    except Exception:
        try:
            from voice_assistant.tts_alt import Pyttsx3TTS
            tts_module = Pyttsx3TTS
        except Exception:
            from voice_assistant.tts_alt import WindowsNativeTTS
            tts_module = WindowsNativeTTS


class VoiceAssistant:
    """Orchestrates voice interaction flow."""

    def __init__(self):
        self.state = "idle"  # idle, recording, processing, playing
        self.running = False

        # Components
        self.audio_recorder = AudioRecorder()
        # Use best available STT
        if stt_module.__name__ == "SpeechToText":
            self.stt = stt_module(model_size="small")
        elif stt_module.__name__ == "WhisperSTT":
            self.stt = stt_module(model_size="base")
        else:
            self.stt = stt_module(language="pt-BR")

        # Use best available TTS
        if tts_module.__name__ == "EdgeTTS":
            # Use male voice (Antonio) for natural sound
            self.tts = tts_module(voice="pt-BR-AntonioNeural", rate="+10%")
        elif tts_module.__name__ == "TextToSpeech":
            self.tts = tts_module(voice_id="af_bella")
        elif tts_module.__name__ == "Pyttsx3TTS":
            self.tts = tts_module(rate=180)
        else:
            self.tts = tts_module()

        self.llm = OllamaClient(model="gemma3:1b")  # Use available model
        self.hotkey: Optional[PushToTalkHandler] = None
        self.ui: Optional[VoiceAssistantUI] = None

        # Threading
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._processing_thread: Optional[threading.Thread] = None
        self._interrupt_playback = False

        # History for context
        self._conversation_history: list[dict] = []
        self._max_history = 4  # Keep last 2 exchanges

    def _on_push(self) -> None:
        """Called when hotkey is pressed."""
        # If playing, interrupt and start new recording
        if self.state == "playing":
            self._interrupt_playback = True
            # Stop audio playback
            try:
                import pygame
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
            except Exception:
                pass
            # Clear subtitle and go to recording
            self.ui.clear_subtitle()
            self.state = "recording"
            self._update_ui_state()
            self.audio_recorder.start()
            return

        if self.state != "idle":
            return

        self.state = "recording"
        self._update_ui_state()

        # Start recording
        try:
            self.audio_recorder.start()
        except Exception as e:
            print(f"Failed to start recording: {e}")
            self.state = "error"
            self._update_ui_state()

    def _on_release(self) -> None:
        """Called when hotkey is released."""
        if self.state != "recording":
            return

        # Stop recording
        try:
            audio_data = self.audio_recorder.stop()
            if audio_data:
                self._audio_queue.put(audio_data)
                # Start processing in background thread
                self._processing_thread = threading.Thread(
                    target=self._process_audio,
                    daemon=True,
                )
                self._processing_thread.start()
            else:
                self.state = "idle"
                self._update_ui_state()
        except Exception as e:
            print(f"Error stopping recording: {e}")
            self.state = "idle"
            self._update_ui_state()

    def _process_audio(self) -> None:
        """Process recorded audio with streaming subtitles."""
        try:
            audio_data = self._audio_queue.get(timeout=1.0)
        except queue.Empty:
            self.state = "idle"
            self._update_ui_state()
            return

        # State: Processing (while getting transcription)
        self.state = "processing"
        self._update_ui_state()

        # Step 1: Speech-to-Text
        transcription = self.stt.transcribe(audio_data)
        if not transcription:
            print("No speech detected")
            self.state = "idle"
            self._update_ui_state()
            return

        print(f"Transcribed: {transcription}")

        # Show user transcription (dim text color)
        self.ui.set_subtitle(transcription)

        # Update history with user message
        self._conversation_history.append({"role": "user", "content": transcription})

        # Step 2: LLM Streaming - collect response without showing
        # Text will only appear during TTS playback (word-by-word)
        response_parts = []

        for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1]):
            response_parts.append(token)
            # No UI update during streaming - text appears during TTS

        # Join tokens and clean the full response
        full_response = "".join(response_parts)
        full_response = self.llm._clean_response(full_response)

        print(f"Response: {full_response}")

        # Update history with assistant message
        self._conversation_history.append({"role": "assistant", "content": full_response})
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]

        # Step 3: Text-to-Speech
        self.state = "playing"
        self._update_ui_state()

        # Prepare words for synchronized subtitles
        words = full_response.split()
        if not words:
            self.state = "idle"
            self._update_ui_state()
            return

        # Estimate speech rate: ~150 words per minute = 2.5 wps = 400ms per word
        ms_per_word = 400

        # Handle different TTS APIs
        try:
            if self.tts.__class__.__name__ == 'EdgeTTS':
                audio_response = self.tts.synthesize(full_response)
                if audio_response:
                    import tempfile
                    import pygame
                    import os

                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                            tmp.write(audio_response)
                            tmp_path = tmp.name

                        # Use faster fixed rate: ~180ms per word (faster speech)
                        # Show 2 words at a time for smoother feel
                        words_per_chunk = 2
                        ms_per_chunk = 360  # 2 words * 180ms

                        pygame.mixer.init()
                        pygame.mixer.music.load(tmp_path)
                        pygame.mixer.music.play()

                        # Playback with synchronized subtitles and voice animation
                        start_time = time.time()
                        chunk_index = 0
                        word_index = 0
                        last_update = 0

                        while pygame.mixer.music.get_busy():
                            # Check for interrupt
                            if self._interrupt_playback:
                                pygame.mixer.music.stop()
                                break

                            elapsed = (time.time() - start_time) * 1000  # ms

                            # Update every chunk
                            target_chunk = int(elapsed / ms_per_chunk)
                            if target_chunk > chunk_index:
                                chunk_index = min(target_chunk, (len(words) + words_per_chunk - 1) // words_per_chunk)
                                word_index = min(chunk_index * words_per_chunk, len(words))

                                # Show words up to current index
                                displayed_text = " ".join(words[:word_index])
                                self.ui.set_subtitle(displayed_text)
                                last_update = elapsed

                            # Voice animation - stronger pulse, more dynamic
                            if word_index < len(words):
                                # High activity when speaking - vary based on "time since last word"
                                phase = (elapsed % ms_per_chunk) / ms_per_chunk  # 0.0 to 1.0 within chunk
                                level = 0.4 + (0.6 * (1 - phase)) + random.random() * 0.3
                            else:
                                level = 0.2 + random.random() * 0.2

                            self.ui.set_audio_level(min(1.0, level))
                            time.sleep(0.02)  # ~50fps for smoother animation

                        # If interrupted, don't show final text, just clear and return
                        if self._interrupt_playback:
                            self.ui.clear_subtitle()
                            self.ui.set_audio_level(0.0)
                            self._interrupt_playback = False
                            # Don't go to idle - we're already in recording state
                            # _on_push already started the new recording
                            return

                        # Show final text briefly then clear
                        self.ui.set_subtitle(full_response)
                        time.sleep(0.3)
                        self.ui.clear_subtitle()
                        self.ui.set_audio_level(0.0)

                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            try:
                                pygame.mixer.quit()
                                time.sleep(0.2)
                                os.unlink(tmp_path)
                            except Exception:
                                pass
            elif hasattr(self.tts, 'synthesize'):
                audio_response = self.tts.synthesize(full_response)
                if audio_response:
                    # Faster word chunks for other TTS (3 words every 400ms)
                    chunk_size = 3
                    for i in range(chunk_size, len(words) + chunk_size, chunk_size):
                        self.ui.set_subtitle(" ".join(words[:i]))
                        time.sleep(0.4)
                    self.ui.set_subtitle(full_response)
                    time.sleep(0.3)
                    self.ui.clear_subtitle()
                    play_audio(audio_response)
            elif hasattr(self.tts, 'play_direct'):
                # No text for Windows SAPI (can't sync)
                self.tts.play_direct(full_response)
        except Exception as e:
            print(f"TTS playback error: {e}")

        # Back to idle (unless interrupted - then we stay in recording)
        if not self._interrupt_playback:
            self.state = "idle"
            self._update_ui_state()

    def _update_ui_state(self) -> None:
        """Update UI with current state."""
        if self.ui:
            self.ui.set_state(self.state)

    def _update_ui_transcription(self, text: str) -> None:
        """Update UI with transcription."""
        if self.ui:
            self.ui.set_transcription(text)

    def _update_ui_response(self, text: str) -> None:
        """Update UI with response."""
        if self.ui:
            self.ui.set_response(text)

    def _check_dependencies(self) -> bool:
        """Check if required services are running."""
        print("Checking dependencies...")

        # Check Ollama
        if not self.llm.health():
            print("ERROR: Ollama is not running!")
            print("Please start it with: ollama serve")
            print("Then pull a model: ollama pull qwen3.5:2b")
            return False

        print("✓ Ollama connected")

        # Check models available
        models = self.llm.list_models()
        if not models:
            print("WARNING: No models found in Ollama")
            print("Run: ollama pull qwen3.5:2b")
        else:
            print(f"✓ Available models: {', '.join(models[:3])}")

        return True

    def run(self) -> None:
        """Run the voice assistant."""
        print("=" * 50)
        print("Jarvis Voice Assistant")
        print("=" * 50)

        # Check dependencies
        if not self._check_dependencies():
            input("Press Enter to exit...")
            return

        # Initialize STT (this downloads model if needed)
        print("\nInitializing speech recognition (first time may download models)...")
        try:
            self.stt._ensure_model()
            print("✓ Speech recognition ready")
        except Exception as e:
            print(f"ERROR: Failed to load STT: {e}")
            input("Press Enter to exit...")
            return

        # Initialize TTS
        print("\nInitializing text-to-speech...")
        try:
            # Check which TTS we're using
            if hasattr(self.tts, '_ensure_setup'):
                self.tts._ensure_setup()
                print(f"✓ Text-to-speech ready ({self.tts.__class__.__name__})")
            elif hasattr(self.tts, '_ensure_pipeline'):
                self.tts._ensure_pipeline()
                print("✓ Text-to-speech ready (Kokoro)")
            elif hasattr(self.tts, '_ensure_engine'):
                self.tts._ensure_engine()
                print("✓ Text-to-speech ready (Windows)")
            else:
                print("✓ Text-to-speech ready")
        except Exception as e:
            print(f"ERROR: Failed to load TTS: {e}")
            input("Press Enter to exit...")
            return

        print("\n" + "=" * 50)
        print("Ready! Hold Ctrl+Space to talk.")
        print("Press Escape in the UI to exit.")
        print("=" * 50 + "\n")

        # Setup hotkey
        self.hotkey = PushToTalkHandler(
            on_push=self._on_push,
            on_release=self._on_release,
        )
        self.hotkey.start()

        # Setup UI (with key bindings)
        self.ui = VoiceAssistantUI(
            on_close=self.stop,
            on_push=self._on_push,
            on_release=self._on_release,
        )
        self.ui.build()
        self.ui.run()

    def stop(self) -> None:
        """Stop the assistant."""
        print("\nShutting down...")
        self.running = False
        if self.hotkey:
            self.hotkey.stop()


def main():
    """Entry point."""
    assistant = VoiceAssistant()
    try:
        assistant.run()
    except KeyboardInterrupt:
        assistant.stop()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
