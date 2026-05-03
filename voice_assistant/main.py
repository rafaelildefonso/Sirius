"""Main voice assistant application."""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
import queue
from typing import Dict, Optional
import os

# Suppress pygame startup banner before any pygame import
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Add parent to path for imports
# Ensure project root and venv site-packages are in path
# We use absolute paths to avoid confusion
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Try to find and add venv site-packages manually if we are in a sparse environment
venv_site = os.path.join(project_root, ".venv", "Lib", "site-packages")
if os.path.exists(venv_site) and venv_site not in sys.path:
    sys.path.append(venv_site)

from voice_assistant.audio import AudioRecorder, ContinuousAudioRecorder, ClapDetector, play_audio, ClapCalibrator
from voice_assistant.llm import OllamaClient, ChatResponse
from voice_assistant.llm_groq import GroqClient
from voice_assistant.hotkey import PushToTalkHandler
from voice_assistant.ui import VoiceAssistantUI
from voice_assistant.tools import create_default_executor, ToolExecutor
from voice_assistant.memory import MemoryManager

# Inject credentials from centralized TOML
try:
    project_src = os.path.join(project_root, "src")
    if project_src not in sys.path:
        sys.path.append(project_src)
    from openjarvis.core.credentials import inject_credentials
    inject_credentials()
except Exception:
    pass

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

    def __init__(
        self,
        clap_threshold_db: float = -20.0,
        clap_min_interval_ms: float = 200,
        clap_max_interval_ms: float = 1000,
        clap_min_duration_ms: float = 30,
        clap_max_duration_ms: float = 200,
        clap_debug: bool = False,
    ):
        self.state = "idle"  # idle, recording, listening, processing, playing
        self.running = False
        self._live_mode = False
        self._live_mode_requested = False

        # Components
        self.audio_recorder = AudioRecorder()
        self._continuous_recorder: Optional[ContinuousAudioRecorder] = None
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

        # Initialize Ollama as fallback first
        fallback_llm = OllamaClient(model="qwen3.5:2b")

        # Initialize Memory
        memory_path = os.path.join(project_root, "memory.json")
        self.memory = MemoryManager(memory_path)

        # GroqClient manages its own fallback to Ollama internally.
        # We always keep GroqClient as self.llm so it can try Groq first
        # and fall back to Ollama per-request if needed.
        self.llm = GroqClient(
            model="llama-3.3-70b-versatile",
            fallback_client=fallback_llm,
        )
        if self.llm.is_available():
            print("[INFO] Using Groq (llama-3.3-70b-versatile)")
        else:
            print("[INFO] Groq unavailable, will use Ollama local as fallback")
        self.hotkey: Optional[PushToTalkHandler] = None
        self.ui: Optional[VoiceAssistantUI] = None

        # Threading
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._processing_thread: Optional[threading.Thread] = None
        self._interrupt_playback = False
        self._interrupt_thinking = False
        self._thinking_active = False  # Track if we're in thinking phase

        # History for context
        self._conversation_history: list[dict] = []
        self._max_history = 4  # Keep last 2 exchanges

        # Tool executor for computer control
        self._tool_executor: ToolExecutor = create_default_executor(memory=self.memory)
        self._max_tool_iterations = 3  # Prevent infinite loops

        # Interruption detection during playback
        self._interruption_monitor: Optional[threading.Thread] = None
        self._stop_interruption_monitor = threading.Event()
        self._playback_lock = threading.Lock()

        # Background mode (Shift+Escape)
        self._background_mode = False
        self._clap_detector: Optional[ClapDetector] = None
        self._was_live_mode_before_background = False

        # Test audio recorder for clap settings calibration
        self._test_audio_recorder: Optional[ContinuousAudioRecorder] = None

        # Clap detection config
        self._clap_threshold_db = clap_threshold_db
        self._clap_min_interval_ms = clap_min_interval_ms
        self._clap_max_interval_ms = clap_max_interval_ms
        self._clap_min_duration_ms = clap_min_duration_ms
        self._clap_max_duration_ms = clap_max_duration_ms
        self._clap_debug = clap_debug

    def _try_fast_action(self, text: str) -> Optional[str]:
        """Try to execute common actions using regex for instant response."""
        import re
        text = text.lower().strip()
        
        # 1. Open/Close Apps
        open_match = re.search(r"(?:abre|abra|abrir|open|iniciar|lancer)\s+(?:o|a|os|as)?\s*([\w\s]+)", text)
        if open_match:
            app = open_match.group(1).strip()
            print(f"[FastPath] Opening app: {app}")
            res = self._tool_executor.execute("open_application", {"app_name": app})
            return f"Com certeza! Abrindo {app} para você." if res.success else f"Tentei abrir o {app}, mas não consegui encontrá-lo."

        close_match = re.search(r"(?:fecha|fechar|encerrar|close|quit)\s+(?:o|a|os|as)?\s*([\w\s]+)", text)
        if close_match:
            app = close_match.group(1).strip()
            print(f"[FastPath] Closing app: {app}")
            res = self._tool_executor.execute("close_window", {"app_name": app})
            return f"Feito! Fechei o {app}." if res.success else f"Não consegui fechar o {app}, talvez ele já esteja fechado."

        # 2. Volume
        vol_match = re.search(r"volume\s+(?:no|em|para)?\s*(\d+)", text)
        if vol_match:
            val = int(vol_match.group(1))
            print(f"[FastPath] Setting volume: {val}")
            self._tool_executor.execute("set_system_volume", {"level": val})
            return f"Volume ajustado para {val} por cento."

        # 3. Time
        if any(w in text for w in ["que horas", "qual a hora", "horas são", "me diga a hora"]):
            res = self._tool_executor.execute("get_current_time", {})
            return f"Agora são {res.content}."

        # 4. YouTube
        yt_match = re.search(r"(?:toca|tocar|play|ouvir|ver|search on youtube)\s+(?:no youtube|no yt)?\s*(.+)", text)
        if yt_match:
            query = yt_match.group(1).strip()
            if "youtube" in query: query = query.replace("no youtube", "").replace("youtube", "").strip()
            print(f"[FastPath] YouTube: {query}")
            self._tool_executor.execute("youtube_search_and_play", {"search_query": query})
            return f"Beleza! Vou tocar {query} no YouTube agora mesmo."

        return None

    def _on_push(self) -> None:
        """Alias for _on_press - called when hotkey is pressed."""
        self._on_press()

    def _on_press(self) -> None:
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

        # If thinking/processing, interrupt it and start fresh
        if self.state == "processing" and self._thinking_active:
            self._interrupt_thinking = True
            self.ui.set_subtitle("(interrompido)")
            # Small delay to let the processing thread see the flag
            time.sleep(0.1)
            # Now start fresh recording
            self._thinking_active = False
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

        # --- FAST PATH ---
        fast_response = self._try_fast_action(transcription)
        if fast_response:
            print(f"[FastPath] Response: {fast_response}")
            self._conversation_history.append({"role": "assistant", "content": fast_response})
            self.state = "playing"
            self._update_ui_state()
            self.ui.set_subtitle(fast_response)
            self.tts.say(fast_response)
            self.memory.save_conversation(self._conversation_history)
            self.state = "idle"
            self._update_ui_state()
            return

        # Step 2: LLM with tool calling
        start_time = time.time()
        
        # Reset interrupt flags
        self._interrupt_thinking = False
        self._thinking_active = True
        
        # Get tool definitions - limit to essential tools for speed
        all_tool_definitions = self._tool_executor.get_tool_definitions()
        
        # Prioritize tools
        essential_tools = ["open_url", "open_application", "search_web", 
                          "get_current_time", "set_system_volume", "focus_window", 
                          "close_window", "list_running_apps", "youtube_search_and_play"]
        
        tool_definitions = [t for t in all_tool_definitions 
                           if any(name in str(t) for name in essential_tools)]
        
        # Inject memory context
        memory_summary = self.memory.get_summary_string()
        
        full_system_prompt = (
            "Você é o Sirius (antigo Jarvis), o assistente de voz pessoal do usuário. "
            "Responda de forma curta, natural e conversacional em português. "
            "Não use markdown, não use emojis, não use blocos de código.\n\n"
            "REGRAS CRÍTICAS:\n"
            "1. SEMPRE use a ferramenta 'search_web' para qualquer pergunta factual, curiosidade, notícias ou informações que exijam precisão.\n"
            "2. EXERÇA PENSAMENTO CRÍTICO: Não aceite o primeiro resultado da busca se ele parecer datado ou incompleto. Procure por nomes famosos e recordes mundiais (ex: Felix Baumgartner para queda livre).\n"
            "3. NUNCA responda fatos com base apenas no seu conhecimento interno se for uma lista de dados ou recordes.\n"
            "4. Se o usuário pedir para pesquisar, pesquise com profundidade.\n"
            "5. Use as memórias abaixo para personalizar o tratamento.\n\n"
            f"Contexto do usuário (MEMÓRIA):\n{memory_summary}"
        )

        # Check if model supports tools
        llm_model = getattr(self.llm, 'model', '')
        model_supports_tools = any(
            model in llm_model.lower()
            for model in ["qwen2.5", "qwen3.5", "llama3.2", "mistral", "llama-3.3", "llama-3.1"]
        ) or isinstance(self.llm, GroqClient)

        full_response = ""
        tool_calls_executed = []

        if model_supports_tools and tool_definitions:
            # Use chat with tools (non-streaming for simpler handling)
            self.ui.set_subtitle("Pensando...")
            try:
                response: ChatResponse = self.llm.chat_with_tools(
                    transcription,
                    tools=tool_definitions,
                    history=self._conversation_history[:-1],
                    system_prompt=full_system_prompt,
                )
                
                # Check if user interrupted during thinking
                if self._interrupt_thinking:
                    self._thinking_active = False
                    return
                
                # Check if model doesn't support tools (returned 400 error)
                if response.text == "__TOOLS_NOT_SUPPORTED__":
                    self._thinking_active = False
                    # Fallback to normal streaming without tools
                    response_parts = []
                    for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                        response_parts.append(token)
                    full_response = "".join(response_parts)
                else:
                    # Execute tool calls if any
                    try:
                        current_response = response
                        tool_results = []  # Initialize to ensure it's available

                        # Execute tool calls
                        if current_response.has_tool_calls:
                            tool_results = []
                            for call in current_response.tool_calls:
                                # Avoid repeating the same search in one turn
                                if call.name == "search_web" and any("search_web" in str(tc) for tc in tool_calls_executed):
                                    continue
                                    
                                print(f"Executing tool: {call.name}({call.arguments})")
                                result = self._tool_executor.execute(call.name, call.arguments)
                                tool_results.append({
                                    "tool": call.name,
                                    "result": result.content,
                                    "success": result.success,
                                })
                                tool_calls_executed.append(call.name)

                            if not tool_results:
                                full_response = current_response.text or "Ação concluída."
                            else:
                                # Build a clean summary of tool results
                                raw_data = " ".join(r['result'] for r in tool_results)

                                synthesis_prompt = (
                                    f"Pergunta do usuário: {transcription}\n"
                                    f"Dados encontrados: {raw_data}\n\n"
                                    "Responda à pergunta de forma natural e conversacional em português, "
                                    "como se estivesse numa conversa. Máximo 2 frases. "
                                    "NÃO mencione que pesquisou ou encontrou dados."
                                )

                                final_answer = self.llm.chat(
                                    synthesis_prompt,
                                    system_prompt="Você é o Sirius, assistente de voz. Responda de forma curta e natural."
                                )

                                if final_answer and len(final_answer.strip()) > 5:
                                    full_response = final_answer
                                else:
                                    # Best-effort fallback: extract first meaningful sentences from raw data
                                    raw_text = raw_data.strip()
                                    import re
                                    # Split by sentence-ending markers, but try to avoid splitting on numbers like '1.'
                                    # We use a negative lookbehind for digits
                                    sentences = re.split(r'(?<!\b\d)[.!?]\s+', raw_text)
                                    
                                    # Take first 3 sentences for better context while still being brief
                                    valid_sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
                                    full_response = ". ".join(valid_sentences[:3])
                                    if full_response and not full_response.endswith(('.', '!', '?')):
                                        full_response += "."
                                        
                                    if not full_response:
                                        full_response = raw_text[:250]
                        else:
                            # No tool calls, use response text
                            full_response = current_response.text

                    except Exception as e:
                        print(f"Tool calling failed, falling back to normal chat: {e}")
                        # Fallback to normal streaming
                        response_parts = []
                        for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                            response_parts.append(token)
                        full_response = "".join(response_parts)

            except Exception as e:
                print(f"Tool calling failed, falling back to normal chat: {e}")
                # Fallback to normal streaming
                response_parts = []
                for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                    response_parts.append(token)
                full_response = "".join(response_parts)

        else:
            # Model doesn't support tools - use normal chat (non-streaming is more reliable)
            try:
                full_response = self.llm.chat(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt)
            except Exception as e:
                # Fallback to streaming if chat fails
                response_parts = []
                for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                    response_parts.append(token)
                full_response = "".join(response_parts)

        full_response = self.llm._clean_response(full_response)
        
        # If response is empty, provide a fallback message
        if not full_response or not full_response.strip():
            full_response = "Desculpe, não consegui entender. Pode repetir a pergunta?"
        
        # Thinking phase is done
        self._thinking_active = False

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

        # Log and speak the final response
        print(f"\nSirius: {full_response}")
        
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
                    print(f"\nSirius: {full_response}")
                    self.tts.speak(full_response)
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

        print("[OK] Ollama connected")

        # Check models available
        models = self.llm.list_models()
        if not models:
            print("WARNING: No models found in Ollama")
            print("Run: ollama pull qwen3.5:2b")
        else:
            print(f"[OK] Available models: {', '.join(models[:3])}")

        return True

    def run(self) -> None:
        """Run the voice assistant."""
        print("=" * 50)
        print("Sirius Voice Assistant")
        print("=" * 50)

        # Check dependencies
        if not self._check_dependencies():
            input("Press Enter to exit...")
            return

        # Initialize STT (this downloads model if needed)
        print("\nInitializing speech recognition (first time may download models)...")
        try:
            self.stt._ensure_model()
            print("[OK] Speech recognition ready")
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
                print(f"[OK] Text-to-speech ready ({self.tts.__class__.__name__})")
            elif hasattr(self.tts, '_ensure_pipeline'):
                self.tts._ensure_pipeline()
                print("[OK] Text-to-speech ready (Kokoro)")
            elif hasattr(self.tts, '_ensure_engine'):
                self.tts._ensure_engine()
                print("[OK] Text-to-speech ready (Windows)")
            else:
                print("[OK] Text-to-speech ready")
        except Exception as e:
            print(f"ERROR: Failed to load TTS: {e}")
            input("Press Enter to exit...")
            return

        print("\n" + "=" * 50)
        print("Ready! Hold Ctrl+Space to talk.")
        print("Press 'L' to toggle LIVE MODE (microphone always on).")
        print("Press Shift+Escape for BACKGROUND MODE (2 claps to wake).")
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
            on_live_toggle=self._on_live_mode_toggle,
            on_background_toggle=self._on_background_mode_toggle,
            on_settings=self._on_settings_click,
        )
        self.ui.build()
        self.ui.run()

    def _on_live_mode_toggle(self, enabled: bool) -> None:
        """Handle live mode toggle from UI."""
        self._live_mode_requested = enabled

        if enabled:
            print("\n🎙️ Modo Live ativado - Microfone sempre aberto")
            self._start_live_mode()
        else:
            print("\n⏹️ Modo Live desativado - Voltando ao push-to-talk")
            self._stop_live_mode()

    def _start_live_mode(self) -> None:
        """Start continuous audio recording with VAD."""
        if self._continuous_recorder is None:
            self._continuous_recorder = ContinuousAudioRecorder(
                sample_rate=16000,
                channels=1,
                vad_threshold_db=-40.0,
                vad_debounce_ms=300,
                silence_timeout_ms=1500,
            )
            self._continuous_recorder.set_callbacks(
                on_vad_detected=self._on_vad_detected,
                on_recording_complete=self._on_live_recording_complete,
                on_audio_level=self._on_live_audio_level,
            )

        self._live_mode = True
        self._continuous_recorder.start()

    def _stop_live_mode(self) -> None:
        """Stop continuous audio recording."""
        self._live_mode = False
        if self._continuous_recorder and self._continuous_recorder.is_running():
            self._continuous_recorder.stop()

    def _on_vad_detected(self) -> None:
        """Called when VAD detects voice activity in live mode."""
        if self.state == "playing":
            # Interruption detected during playback
            print("🛑 Interrupção detectada - parando resposta")
            self._interrupt_playback = True
            try:
                import pygame
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                self._stop_interruption_monitor.set()
            except Exception:
                pass

        # Update state to recording
        if self.state not in ["processing", "recording"]:
            self.state = "recording"
            self._update_ui_state()

    def _on_live_audio_level(self, level: float) -> None:
        """Update UI with live audio level during listening state."""
        if self.state in ["listening", "idle", "recording"]:
            # Send level to UI for waveform
            self.ui.set_audio_level(level)

    def _on_live_recording_complete(self, audio_data: bytes) -> None:
        """Process completed recording from live mode."""
        if not audio_data:
            return

        # Don't process if we're already processing and not interrupting
        if self.state == "processing" and not self._interrupt_playback:
            return

        # Put audio in queue and process
        self._audio_queue.put(audio_data)

        # Stop any ongoing interruption monitor
        self._stop_interruption_monitor.set()

        # Process in background thread
        self._processing_thread = threading.Thread(
            target=self._process_audio_live,
            daemon=True,
        )
        self._processing_thread.start()

    def _process_audio_live(self) -> None:
        """Process recorded audio in live mode (same as normal but handles interruptions)."""
        try:
            audio_data = self._audio_queue.get(timeout=1.0)
        except queue.Empty:
            if not self._interrupt_playback:
                self.state = "idle" if self._live_mode else "idle"
                self._update_ui_state()
            return

        # Handle interruption case
        if self._interrupt_playback:
            self._interrupt_playback = False
            self._stop_interruption_monitor.clear()

        # Go to processing state
        self.state = "processing"
        self._update_ui_state()

        # Step 1: Speech-to-Text
        transcription = self.stt.transcribe(audio_data)
        if not transcription:
            print("Nenhuma fala detectada")
            self.state = "idle" if self._live_mode else "idle"
            self._update_ui_state()
            return

        print(f"Transcrito (live): {transcription}")
        self.ui.set_subtitle(transcription)

        # Update history
        self._conversation_history.append({"role": "user", "content": transcription})

        # --- FAST PATH ---
        fast_response = self._try_fast_action(transcription)
        if fast_response:
            print(f"[FastPath Live] Response: {fast_response}")
            self._conversation_history.append({"role": "assistant", "content": fast_response})
            self.state = "playing"
            self._update_ui_state()
            self.ui.set_subtitle(fast_response)
            self._play_tts_with_interruption(fast_response)
            self.memory.save_conversation(self._conversation_history)
            self.state = "listening" if self._live_mode else "idle"
            self._update_ui_state()
            return

        # Step 2: LLM with tool calling
        system_prompt = getattr(self.llm, 'system_prompt', "")
        memory_ext = self.memory.get_system_prompt_extension()
        full_system_prompt = system_prompt + memory_ext
        
        all_tool_definitions = self._tool_executor.get_tool_definitions()
        essential_tools = ["open_url", "open_application", "search_web", 
                          "get_current_time", "set_system_volume", "focus_window", 
                          "close_window", "list_running_apps", "youtube_search_and_play"]
        
        tool_definitions = [t for t in all_tool_definitions 
                           if any(name in str(t) for name in essential_tools)]

        model_supports_tools = any(
            model in self.llm.model.lower()
            for model in ["qwen", "gemma", "llama3", "mistral"]
        )

        full_response = ""

        if model_supports_tools and tool_definitions:
            self.ui.set_subtitle("Pensando...")
            try:
                response: ChatResponse = self.llm.chat_with_tools(
                    transcription,
                    tools=tool_definitions,
                    history=self._conversation_history[:-1],
                    system_prompt=full_system_prompt,
                )

                if response.has_tool_calls:
                    tool_results = []
                    for call in response.tool_calls:
                        print(f"Executando ferramenta (live): {call.name}({call.arguments})")
                        result = self._tool_executor.execute(call.name, call.arguments)
                        tool_results.append({
                            "tool": call.name,
                            "result": result.content,
                            "success": result.success,
                        })

                    tool_result_message = "Resultados:\n" + "\n".join(
                        f"- {r['tool']}: {r['result']}" for r in tool_results
                    )

                    follow_up = f"Dados da busca: {tool_result_message}\n\nResponda ao usuário de forma muito curta em português."
                    
                    messages = self._conversation_history[:-1] + [
                        {"role": "user", "content": transcription},
                        {"role": "assistant", "content": response.text or "Ação concluída."},
                    ]
                    
                    final_answer = self.llm.chat(follow_up, history=messages, system_prompt="Responda de forma concisa.")
                    
                    if final_answer and len(final_answer.strip()) > 5:
                        full_response = final_answer
                    else:
                        combined = tool_results[0]['result']
                        summary = combined.split('.')[0] if '.' in combined else combined
                        full_response = f"Encontrei isso: {summary[:100]}."
                else:
                    full_response = response.text

            except Exception as e:
                print(f"Falha no tool calling, usando chat normal: {e}")
                response_parts = []
                for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                    response_parts.append(token)
                full_response = "".join(response_parts)
        else:
            response_parts = []
            for token in self.llm.chat_stream(transcription, history=self._conversation_history[:-1], system_prompt=full_system_prompt):
                response_parts.append(token)
            full_response = "".join(response_parts)

        full_response = self.llm._clean_response(full_response)
        print(f"Resposta: {full_response}")

        # Update history and save to memory
        self._conversation_history.append({"role": "assistant", "content": full_response})
        self.memory.save_conversation(self._conversation_history)
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]

        # Step 3: Text-to-Speech with interruption monitoring
        self.state = "playing"
        self._update_ui_state()

        # Start interruption monitor before playing
        self._stop_interruption_monitor.clear()
        self._start_interruption_monitor()

        # Play TTS
        self._play_tts_with_interruption(full_response)

        # Stop interruption monitor
        self._stop_interruption_monitor.set()

        # Go back to idle/listening
        if self._live_mode:
            self.state = "listening"
        else:
            self.state = "idle"
        self._update_ui_state()

    def _start_interruption_monitor(self) -> None:
        """Start thread to monitor for interruptions during playback."""
        if self._interruption_monitor and self._interruption_monitor.is_alive():
            return

        self._stop_interruption_monitor.clear()
        self._interruption_monitor = threading.Thread(
            target=self._monitor_for_interruption,
            daemon=True,
        )
        self._interruption_monitor.start()

    def _monitor_for_interruption(self) -> None:
        """Monitor for user speech during TTS playback (VAD + STT confirmation)."""
        if not self._continuous_recorder:
            return

        # Wait for VAD to trigger during playback
        check_interval = 0.05  # 50ms
        confirmation_required = 0.5  # 500ms of continuous voice
        voice_start_time = None

        while not self._stop_interruption_monitor.is_set():
            # Check if we're still playing
            if self.state != "playing":
                break

            # Check if VAD is active (voice detected)
            if self._continuous_recorder.is_recording():
                if voice_start_time is None:
                    voice_start_time = time.time()
                elif time.time() - voice_start_time >= confirmation_required:
                    # Voice confirmed for 500ms - trigger interruption
                    print("🎤 Interrupção confirmada (VAD + tempo)")
                    self._interrupt_playback = True
                    try:
                        import pygame
                        if pygame.mixer.music.get_busy():
                            pygame.mixer.music.stop()
                    except Exception:
                        pass
                    break
            else:
                voice_start_time = None

            time.sleep(check_interval)

    def _play_tts_with_interruption(self, text: str) -> None:
        """Play TTS with support for interruption."""
        words = text.split()
        if not words:
            return

        try:
            if self.tts.__class__.__name__ == 'EdgeTTS':
                audio_response = self.tts.synthesize(text)
                if audio_response:
                    import tempfile
                    import pygame
                    import os

                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                            tmp.write(audio_response)
                            tmp_path = tmp.name

                        words_per_chunk = 2
                        ms_per_chunk = 360

                        pygame.mixer.init()
                        pygame.mixer.music.load(tmp_path)
                        pygame.mixer.music.play()

                        start_time = time.time()
                        chunk_index = 0
                        word_index = 0

                        while pygame.mixer.music.get_busy():
                            # Check for interrupt
                            if self._interrupt_playback:
                                pygame.mixer.music.stop()
                                break

                            elapsed = (time.time() - start_time) * 1000

                            target_chunk = int(elapsed / ms_per_chunk)
                            if target_chunk > chunk_index:
                                chunk_index = min(target_chunk, (len(words) + words_per_chunk - 1) // words_per_chunk)
                                word_index = min(chunk_index * words_per_chunk, len(words))

                                displayed_text = " ".join(words[:word_index])
                                self.ui.set_subtitle(displayed_text)

                            # Voice animation
                            if word_index < len(words):
                                phase = (elapsed % ms_per_chunk) / ms_per_chunk
                                level = 0.4 + (0.6 * (1 - phase)) + random.random() * 0.3
                            else:
                                level = 0.2 + random.random() * 0.2

                            self.ui.set_audio_level(min(1.0, level))
                            time.sleep(0.02)

                        # Handle interruption
                        if self._interrupt_playback:
                            self.ui.clear_subtitle()
                            self.ui.set_audio_level(0.0)
                            self._interrupt_playback = False
                            return

                        # Show final text
                        self.ui.set_subtitle(text)
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
                audio_response = self.tts.synthesize(text)
                if audio_response:
                    chunk_size = 3
                    for i in range(chunk_size, len(words) + chunk_size, chunk_size):
                        if self._interrupt_playback:
                            break
                        self.ui.set_subtitle(" ".join(words[:i]))
                        time.sleep(0.4)
                    if not self._interrupt_playback:
                        self.ui.set_subtitle(text)
                        time.sleep(0.3)
                        self.ui.clear_subtitle()
                        play_audio(audio_response)
            elif hasattr(self.tts, 'play_direct'):
                self.tts.play_direct(text)
        except Exception as e:
            print(f"Erro no TTS: {e}")

    def stop(self) -> None:
        """Stop the assistant."""
        print("\nShutting down...")
        self.running = False

        # Stop live mode if active
        if self._live_mode:
            self._stop_live_mode()

        # Stop background mode if active
        if self._background_mode:
            if self._clap_detector and self._clap_detector.is_running():
                self._clap_detector.stop()

        # Stop interruption monitor
        self._stop_interruption_monitor.set()

        if self.hotkey:
            self.hotkey.stop()

    def _on_background_mode_toggle(self, enabled: bool) -> None:
        """Handle background mode toggle from UI (Shift+Escape)."""
        if enabled:
            self._enter_background_mode()
        else:
            self._exit_background_mode()

    def _enter_background_mode(self) -> None:
        """Enter background mode - minimize window but keep listening for claps."""
        print("\n🔽 Entrando em modo background...")
        self._background_mode = True

        # Save current live mode state
        self._was_live_mode_before_background = self._live_mode

        # Stop normal recording if active
        if self._live_mode and self._continuous_recorder:
            self._continuous_recorder.stop()
            self._live_mode = False

        # Initialize and start clap detector with configurable parameters
        if self._clap_detector is None:
            self._clap_detector = ClapDetector(
                threshold_db=self._clap_threshold_db,
                min_clap_interval_ms=self._clap_min_interval_ms,
                max_clap_interval_ms=self._clap_max_interval_ms,
                clap_min_duration_ms=self._clap_min_duration_ms,
                clap_max_duration_ms=self._clap_max_duration_ms,
            )
            self._clap_detector.set_callback(self._on_clap_detected)

        # Enable debug mode if requested
        if self._clap_debug:
            print(f"[CLAP DEBUG] Threshold: {self._clap_threshold_db}dB")
            print(f"[CLAP DEBUG] Interval: {self._clap_min_interval_ms}-{self._clap_max_interval_ms}ms")
            print(f"[CLAP DEBUG] Duration: {self._clap_min_duration_ms}-{self._clap_max_duration_ms}ms")
            self._clap_detector.set_debug(True)
            print("[CLAP DEBUG] Mostrando níveis de áudio em tempo real...")
            print("[CLAP DEBUG] Bate palmas para ver o nível (Ctrl+C para sair do debug)")

        self._clap_detector.start()
        print("👂 Aguardando 2 palmas para voltar...")
        print(f"   (threshold: {self._clap_threshold_db}dB, intervalo: {self._clap_min_interval_ms}-{self._clap_max_interval_ms}ms)")

    def _exit_background_mode(self) -> None:
        """Exit background mode - restore window."""
        print("\n🔼 Saindo do modo background...")
        self._background_mode = False

        # Stop clap detector
        if self._clap_detector and self._clap_detector.is_running():
            self._clap_detector.stop()

        # Restore live mode if it was active before
        if self._was_live_mode_before_background:
            self._start_live_mode()

    def _on_clap_detected(self) -> None:
        """Called when 2 claps are detected in background mode."""
        print("\n👏👏 Palmas detectadas! Restaurando janela...")

        # Restore window from background
        self.ui.restore_from_background()
        self._background_mode = False

        # Stop clap detector
        if self._clap_detector and self._clap_detector.is_running():
            self._clap_detector.stop()

        # Immediately start recording and processing
        # This simulates the user already speaking
        if self._continuous_recorder is None:
            self._continuous_recorder = ContinuousAudioRecorder(
                sample_rate=16000,
                channels=1,
                vad_threshold_db=-40.0,
                vad_debounce_ms=300,
                silence_timeout_ms=1500,
            )
            self._continuous_recorder.set_callbacks(
                on_vad_detected=self._on_vad_detected,
                on_recording_complete=self._on_live_recording_complete,
                on_audio_level=self._on_live_audio_level,
            )

        # Start continuous recorder and trigger recording immediately
        self._live_mode = True
        self._continuous_recorder.start()

        # Give a small moment for audio buffer to fill, then set state
        self.state = "listening"
        self._update_ui_state()

        print("🎙️ Já estou ouvindo! Fale agora...")

    def is_background_mode(self) -> bool:
        """Check if in background mode."""
        return self._background_mode

    def _on_settings_click(self) -> None:
        """Open clap detection settings window."""
        current_config = {
            "threshold_db": self._clap_threshold_db,
            "min_interval_ms": self._clap_min_interval_ms,
            "max_interval_ms": self._clap_max_interval_ms,
            "min_duration_ms": self._clap_min_duration_ms,
            "max_duration_ms": self._clap_max_duration_ms,
        }

        self.ui.open_clap_settings(
            current_config=current_config,
            on_save=self._on_clap_settings_save,
            audio_level_callback=self._get_current_audio_level,
            on_start_test=self._start_clap_test,
            on_stop_test=self._stop_clap_test,
            on_calibrate=self._on_calibrate_click,
        )

    def _start_clap_test(self) -> None:
        """Start test audio recorder for clap calibration."""
        print("🎤 Iniciando teste de microfone para calibração...")

        if self._test_audio_recorder is None:
            self._test_audio_recorder = ContinuousAudioRecorder(
                sample_rate=16000,
                channels=1,
                vad_threshold_db=-60.0,  # Very sensitive for testing
                vad_debounce_ms=50,
                silence_timeout_ms=5000,
            )
            # Don't set any callbacks - we just want the level meter

        if not self._test_audio_recorder.is_running():
            self._test_audio_recorder.start()
            print("✅ Microfone ativado! Bata palmas para ver o nível.")

    def _stop_clap_test(self) -> None:
        """Stop test audio recorder."""
        print("⏹️ Parando teste de microfone...")

        if self._test_audio_recorder and self._test_audio_recorder.is_running():
            self._test_audio_recorder.stop()
            print("✅ Microfone desativado.")

    def _on_calibrate_click(self) -> None:
        """Start automatic clap calibration."""
        print("🎯 Iniciando calibração automática...")
        self.ui.set_subtitle("Calibrando... Bata 3 palmas fortes com intervalo de 1 segundo.")
        
        calibrator = ClapCalibrator(sample_rate=16000)
        calibrator.start()
        
        def finish_calibration():
            time.sleep(5)  # Wait 5 seconds for claps
            results = calibrator.stop()
            if results:
                print(f"✅ Calibração concluída: {results}")
                # Update local settings
                self._clap_threshold_db = results['threshold_db']
                self._clap_min_duration_ms = results['clap_min_duration_ms']
                self._clap_max_duration_ms = results['clap_max_duration_ms']
                self._clap_min_interval_ms = results['min_clap_interval_ms']
                self._clap_max_interval_ms = results['max_clap_interval_ms']
                
                self.ui.set_subtitle("Calibração concluída com sucesso!")
                # Re-open settings to show new values
                self.ui._root.after(1000, self._on_settings_click)
            else:
                self.ui.set_subtitle("Nenhuma palma detectada. Tente novamente.")

        threading.Thread(target=finish_calibration, daemon=True).start()

    def _get_current_audio_level(self) -> float:
        """Get current audio level in dB for the meter."""
        # Use the continuous recorder if available and running
        if (self._continuous_recorder and
            self._continuous_recorder.is_running() and
            hasattr(self._continuous_recorder, '_last_level_db')):
            return self._continuous_recorder._last_level_db

        # If clap detector is running, use its level
        if (self._clap_detector and
            self._clap_detector.is_running() and
            hasattr(self._clap_detector, '_last_level_db')):
            return self._clap_detector._last_level_db

        # If test recorder is running, use its level
        if (self._test_audio_recorder and
            self._test_audio_recorder.is_running() and
            hasattr(self._test_audio_recorder, '_last_level_db')):
            return self._test_audio_recorder._last_level_db

        return -60.0  # Default silence level

    def _on_clap_settings_save(self, config: Dict[str, float]) -> None:
        """Apply new clap detection settings."""
        print("\n⚙️ Atualizando configuração de palmas:")
        print(f"   Threshold: {config['threshold_db']:.1f}dB")
        print(f"   Intervalo: {config['min_interval_ms']:.0f}-{config['max_interval_ms']:.0f}ms")
        print(f"   Duração: {config['min_duration_ms']:.0f}-{config['max_duration_ms']:.0f}ms")

        self._clap_threshold_db = config["threshold_db"]
        self._clap_min_interval_ms = config["min_interval_ms"]
        self._clap_max_interval_ms = config["max_interval_ms"]
        self._clap_min_duration_ms = config["min_duration_ms"]
        self._clap_max_duration_ms = config["max_duration_ms"]

        # Update existing detector if running
        if self._clap_detector:
            self._clap_detector.threshold_db = self._clap_threshold_db
            self._clap_detector.min_clap_interval_ms = self._clap_min_interval_ms
            self._clap_detector.max_clap_interval_ms = self._clap_max_interval_ms
            self._clap_detector.clap_min_duration_ms = self._clap_min_duration_ms
            self._clap_detector.clap_max_duration_ms = self._clap_max_duration_ms

        print("✅ Configuração salva!")


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Sirius Voice Assistant")
    parser.add_argument(
        "--clap-threshold",
        type=float,
        default=-20.0,
        help="Clap detection threshold in dB (default: -20.0, more negative = more sensitive)",
    )
    parser.add_argument(
        "--clap-min-interval",
        type=float,
        default=200,
        help="Minimum interval between claps in ms (default: 200)",
    )
    parser.add_argument(
        "--clap-max-interval",
        type=float,
        default=1000,
        help="Maximum interval between claps in ms (default: 1000)",
    )
    parser.add_argument(
        "--clap-min-duration",
        type=float,
        default=30,
        help="Minimum clap duration in ms (default: 30)",
    )
    parser.add_argument(
        "--clap-max-duration",
        type=float,
        default=200,
        help="Maximum clap duration in ms (default: 200)",
    )
    parser.add_argument(
        "--clap-debug",
        action="store_true",
        help="Enable clap detection debug output",
    )
    args = parser.parse_args()

    assistant = VoiceAssistant(
        clap_threshold_db=args.clap_threshold,
        clap_min_interval_ms=args.clap_min_interval,
        clap_max_interval_ms=args.clap_max_interval,
        clap_min_duration_ms=args.clap_min_duration,
        clap_max_duration_ms=args.clap_max_duration,
        clap_debug=args.clap_debug,
    )
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
