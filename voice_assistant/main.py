"""Main voice assistant application."""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import threading
import time
import queue
from typing import Dict, Optional
from datetime import datetime
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
from voice_assistant.gemini_audio import GeminiAudioClient, QuotaExceededError
from voice_assistant.user_profile import get_profile_manager, ProfileManager

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
        print("[INIT] VoiceAssistant.__init__ starting...")
        self.state = "idle"  # idle, recording, listening, processing, playing
        self.running = False
        self._live_mode = False
        self._live_mode_requested = False

        # Components
        print("[INIT] Creating AudioRecorder...")
        self.audio_recorder = AudioRecorder()
        self.audio_recorder.set_audio_level_callback(self._on_audio_level)
        self._continuous_recorder: Optional[ContinuousAudioRecorder] = None
        
        # Use best available STT
        print("[INIT] Initializing STT...")
        if stt_module.__name__ == "SpeechToText":
            self.stt = stt_module(model_size="small")
        elif stt_module.__name__ == "WhisperSTT":
            self.stt = stt_module(model_size="base")
        else:
            self.stt = stt_module(language="pt-BR")
        print(f"[INIT] STT initialized: {type(self.stt).__name__}")

        # Use best available TTS
        print("[INIT] Initializing TTS...")
        if tts_module.__name__ == "EdgeTTS":
            # Use male voice (Antonio) for natural sound
            self.tts = tts_module(voice="pt-BR-AntonioNeural", rate="+10%")
        elif tts_module.__name__ == "TextToSpeech":
            self.tts = tts_module(voice_id="af_bella")
        elif tts_module.__name__ == "Pyttsx3TTS":
            self.tts = tts_module(rate=180)
        else:
            self.tts = tts_module()

        # Load user profile for personalized experience
        print("[INIT] Loading user profile...")
        try:
            self._profile_manager = get_profile_manager()
            self._user_name = self._profile_manager.profile.userName
            if self._user_name:
                print(f"[Profile] Configurado para usuário: {self._user_name}")
        except Exception as e:
            print(f"[Profile] Erro ao carregar perfil: {e}")
            self._profile_manager = None
            self._user_name = None
        
        # Initialize Ollama as fallback first (with user profile)
        print("[INIT] Creating Ollama fallback LLM...")
        fallback_llm = OllamaClient(model="qwen3.5:2b")

        # Initialize Memory
        print("[INIT] Initializing Memory...")
        memory_path = os.path.join(project_root, "memory.json")
        self.memory = MemoryManager(memory_path)

        # GroqClient manages its own fallback to Ollama internally.
        print("[INIT] Creating Groq LLM client...")
        self.llm = GroqClient(
            model="llama-3.3-70b-versatile",
            fallback_client=fallback_llm,
        )
        if self.llm.is_available():
            print("[INFO] Using Groq (llama-3.3-70b-versatile)")
        else:
            print("[INFO] Groq unavailable, will use Ollama local as fallback")
        # Gemini native audio (primary voice engine when available)
        print("[INIT] Creating Gemini audio client...")
        self._gemini_audio: Optional[GeminiAudioClient] = None
        try:
            self._gemini_audio = GeminiAudioClient()
            if self._gemini_audio.is_available():
                print("[INFO] Using Gemini native audio (gemini-2.5-flash-native-audio-preview)")
            else:
                print("[INFO] Gemini native audio unavailable, using STT+LLM+TTS pipeline")
                self._gemini_audio = None
        except Exception as e:
            print(f"[INFO] Gemini native audio init failed: {e}")
            self._gemini_audio = None

        print("[INIT] Creating PushToTalk handler...")
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
        # 1. YouTube - MUST be before open_application to catch "abre ... no youtube"
        yt_patterns = [
            r"(?:toca|tocar|play|ouvir|ver)\s+(?:no youtube|no yt)?\s*(.+)",
            r"(?:abre|abra|abrir)\s+(?:um|uma|o|a)?\s*vid[eé]o\s+(?:no youtube|no yt|de|sobre)\s*(.+)",
            r"(?:abre|abra|abrir)\s+(?:no youtube|no yt)\s*(?:um|uma)?\s*vid[eé]o\s*(?:de|sobre)?\s*(.*)",
            r"(?:youtube|yt)\s+(?:toca|tocar|play)?\s*(.+)",
        ]
        for pattern in yt_patterns:
            yt_match = re.search(pattern, text)
            if yt_match:
                query = yt_match.group(1).strip() if yt_match.group(1) else "música relaxante"
                # Clean up common words
                for word in ["no youtube", "youtube", "no yt", "yt", "um vídeo de", "uma música de", "vídeo de"]:
                    query = query.replace(word, "").strip()
                if query:
                    print(f"[FastPath] YouTube: {query}")
                    self._tool_executor.execute("youtube_search_and_play", {"search_query": query})
                    return f"Beleza! Vou tocar {query} no YouTube agora mesmo."

        # 2. Open application (after YouTube check)
        open_match = re.search(r"(?:abre|abra|abrir|open|iniciar|lancer)\s+(?:o|a|os|as)?\s*([\w\s]+)", text)
        if open_match:
            app = open_match.group(1).strip()
            # Skip if it's a YouTube reference (should have been caught above)
            if "youtube" in app or "yt" in app:
                # Fallback to generic YouTube search
                print(f"[FastPath] YouTube (fallback): {app}")
                self._tool_executor.execute("youtube_search_and_play", {"search_query": "música relaxante"})
                return f"Vou tocar algo no YouTube para você."
            print(f"[FastPath] Opening app: {app}")
            res = self._tool_executor.execute("open_application", {"app_name": app})
            return f"Com certeza! Abrindo {app} para você." if res.success else f"Tentei abrir o {app}, mas não consegui encontrá-lo."

        # 3. Close application
        close_match = re.search(r"(?:fecha|fechar|encerrar|close|quit)\s+(?:o|a|os|as)?\s*([\w\s]+)", text)
        if close_match:
            app = close_match.group(1).strip()
            print(f"[FastPath] Closing app: {app}")
            res = self._tool_executor.execute("close_window", {"app_name": app})
            return f"Feito! Fechei o {app}." if res.success else f"Não consegui fechar o {app}, talvez ele já esteja fechado."

        # 4. Volume
        vol_match = re.search(r"volume\s+(?:no|em|para)?\s*(\d+)", text)
        if vol_match:
            val = int(vol_match.group(1))
            print(f"[FastPath] Setting volume: {val}")
            self._tool_executor.execute("set_system_volume", {"level": val})
            return f"Volume ajustado para {val} por cento."

        # 5. Time
        if any(w in text for w in ["que horas", "qual a hora", "horas são", "me diga a hora"]):
            res = self._tool_executor.execute("get_current_time", {})
            return f"Agora são {res.content}."

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

    def _process_audio_gemini(self, audio_data: bytes) -> None:
        """Process audio using Gemini native audio (audio-in, audio-out).

        Raises QuotaExceededError on rate limit, Exception on other errors.
        """
        self.ui.set_subtitle("Ouvindo...")

        # Build system prompt with memory context
        memory_summary = self.memory.get_summary_string()
        system_prompt = (
            "Você é o Sirius, o assistente de voz pessoal do usuário. "
            "Responda de forma curta, natural e conversacional em português. "
            "Não use markdown, não use emojis, não use blocos de código.\n\n"
            f"Contexto do usuário (MEMÓRIA):\n{memory_summary}"
        )

        # Send audio to Gemini and get audio back (async)
        print("[Gemini] Sending audio to Live API...")
        audio_response, transcript = asyncio.run(self._gemini_audio.chat_audio(
            audio_data,
            system_prompt=system_prompt,
        ))

        # Check if we got a valid response
        if not audio_response or len(audio_response) < 100:
            print(f"[Gemini] Warning: Empty or very small audio response ({len(audio_response) if audio_response else 0} bytes)")
            if transcript:
                print(f"[Gemini] Got transcript but no audio: {transcript}")
            # Raise error to trigger fallback
            raise RuntimeError("Gemini returned empty audio")

        # Show transcript if available
        if transcript:
            print(f"Gemini transcript: {transcript}")
            self.ui.set_subtitle(transcript)

        # Update conversation history (text-only for memory)
        self._conversation_history.append({"role": "assistant", "content": transcript or "(resposta de áudio)"})
        self.memory.save_conversation(self._conversation_history)

        # Play audio response
        print(f"[Gemini] Playing audio response ({len(audio_response)} bytes)...")
        self.state = "playing"
        self._update_ui_state()

        # Transcribe Gemini's response audio for subtitles (if no transcript provided)
        display_text = transcript
        if not display_text and audio_response:
            try:
                print("[Gemini] Transcribing response for subtitles...")
                # Convert WAV to format STT expects if needed
                import io
                import wave
                buffer = io.BytesIO(audio_response)
                with wave.open(buffer, 'rb') as wf:
                    # Read raw audio for STT
                    raw_audio = wf.readframes(wf.getnframes())
                # Transcribe in background thread to not block playback
                import threading
                transcript_result = [None]
                def transcribe():
                    try:
                        transcript_result[0] = self.stt.transcribe(audio_response)
                    except Exception as e:
                        print(f"[Gemini] Transcription error: {e}")
                t = threading.Thread(target=transcribe)
                t.start()
                # Don't wait for transcription, show generic message initially
                display_text = "Assistente respondendo..."
            except Exception as e:
                print(f"[Gemini] Could not prepare transcription: {e}")
                display_text = "Assistente respondendo..."

        try:
            import tempfile
            import pygame

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp.write(audio_response)
                    tmp_path = tmp.name

                pygame.mixer.init()
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()

                # Show initial subtitle
                if display_text:
                    self.ui.set_subtitle(display_text)

                # Playback with animation
                start_time = time.time()
                last_subtitle_update = 0
                transcription_done = False
                while pygame.mixer.music.get_busy():
                    if self._interrupt_playback:
                        pygame.mixer.music.stop()
                        break

                    # Update subtitle when transcription is ready
                    if not transcription_done and 't' in dir() and not t.is_alive():
                        transcription_done = True
                        if transcript_result[0]:
                            print(f"[Gemini] Transcription: {transcript_result[0]}")
                            self.ui.set_subtitle(transcript_result[0])

                    # Voice animation
                    elapsed = time.time() - start_time
                    level = 0.4 + 0.4 * abs((elapsed * 3) % 2 - 1) + random.random() * 0.2
                    self.ui.set_audio_level(min(1.0, level))
                    time.sleep(0.02)

                # Handle interruption
                if self._interrupt_playback:
                    self.ui.clear_subtitle()
                    self.ui.set_audio_level(0.0)
                    self._interrupt_playback = False
                    return

                # Keep subtitle visible briefly after speech ends
                time.sleep(0.5)
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
        except Exception as e:
            print(f"[Gemini] Playback error: {e}")
            # Fallback: try sounddevice
            try:
                from voice_assistant.audio import play_audio
                play_audio(audio_response)
            except Exception as e2:
                print(f"[Gemini] Fallback playback also failed: {e2}")

        # Back to idle
        if not self._interrupt_playback:
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

        # --- Try Gemini native audio first ---
        if self._gemini_audio and self._gemini_audio.is_available():
            try:
                self._process_audio_gemini(audio_data)
                return
            except QuotaExceededError:
                print("[Gemini] Quota exceeded, falling back to STT+LLM+TTS pipeline")
                self.ui.set_subtitle("Modo local...")
            except Exception as e:
                print(f"[Gemini] Error, falling back: {e}")
                self.ui.set_subtitle("Modo local...")
            # If Gemini failed, continue with fallback pipeline below

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
            self.tts.play_direct(fast_response)
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
            "Você é o Sirius, o assistente de voz pessoal do usuário. "
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
        llm_model_lower = llm_model.lower()
        
        # Models that support proper function calling
        supports_tools = any(model in llm_model_lower for model in [
            "qwen2.5", "qwen3.5", "llama3.2", "mistral", "llama-3.1"
        ])
        
        # Groq: llama-3.3-70b generates malformed XML tool calls, disable tools for it
        # Only use tools with Groq if explicitly using a compatible model
        groq_supports_tools = isinstance(self.llm, GroqClient) and "llama-3.1" in llm_model_lower
        
        model_supports_tools = supports_tools or groq_supports_tools

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

        # Check if response looks like an error message (contains technical terms)
        error_indicators = ['error:', 'error code:', 'exception', 'traceback', 'failed_generation', '400', '401', '403', '429', '500', '503']
        is_error_message = any(indicator in full_response.lower() for indicator in error_indicators)
        
        if is_error_message:
            print(f"[ERROR] Detected error in response, filtering: {full_response[:200]}...")
            full_response = "Desculpe, tive um problema técnico. Pode tentar de novo?"

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
        print("Ready! Hold Ctrl+Shift+Space to talk.")
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
        try:
            self.ui = VoiceAssistantUI(
                on_close=self.stop,
                on_push=self._on_push,
                on_release=self._on_release,
                on_live_toggle=self._on_live_mode_toggle,
                on_background_toggle=self._on_background_mode_toggle,
                on_settings=self._on_settings_click,
            )
            self.ui.build()
        except Exception as e:
            print(f"ERROR: Failed to create UI: {e}")
            import traceback
            traceback.print_exc()
            input("Press Enter to exit...")
            return

        # Schedule greeting after UI is shown (500ms delay)
        if self.ui._root:
            self.ui._root.after(500, self._play_greeting)

        try:
            self.ui.run()
        except Exception as e:
            print(f"ERROR: UI crashed: {e}")
            import traceback
            traceback.print_exc()
            input("Press Enter to exit...")

    def _play_greeting(self) -> None:
        """Play random greeting with time and day."""
        try:
            now = datetime.now()
            hour = now.hour

            # Determine time of day greeting
            if 5 <= hour < 12:
                time_greeting = "Bom dia"
            elif 12 <= hour < 18:
                time_greeting = "Boa tarde"
            else:
                time_greeting = "Boa noite"

            # Days of week in Portuguese
            days = ["segunda-feira", "terça-feira", "quarta-feira",
                    "quinta-feira", "sexta-feira", "sábado", "domingo"]
            day_name = days[now.weekday()]

            # Format time (HH:MM)
            time_str = now.strftime("%H:%M")

            # Random follow-up questions
            questions = [
                "O que temos para hoje?",
                "O que manda?",
                "O que você precisa?",
                "Como posso ajudar?",
                "No que posso ser útil?",
                "O que vamos fazer?",
                "Estou aqui. O que precisa?",
                "Pronto para começar. O que manda?",
                "O que você tem em mente?",
                "Estou ouvindo. O que precisa?",
            ]
            question = random.choice(questions)

            # Build greeting variations - include user name if available
            user_name = getattr(self, '_user_name', '')
            name_part = f" {user_name}" if user_name else ""
            
            if user_name:
                greetings = [
                    f"{time_greeting}{name_part}! São {time_str} de {day_name}. {question}",
                    f"{time_greeting}{name_part}! Agora são {time_str}, {day_name}. {question}",
                    f"Olá{name_part}! {time_greeting}. São {time_str} de {day_name}. {question}",
                    f"Oi{name_part}! {time_greeting}! São {time_str}, {day_name}. {question}",
                    f"{time_greeting}{name_part}! Hoje é {day_name}, {time_str}. {question}",
                    f"{time_greeting}{name_part}! {day_name.capitalize()}, {time_str}. {question}",
                ]
            else:
                greetings = [
                    f"{time_greeting}! São {time_str} de {day_name}. {question}",
                    f"{time_greeting}! Agora são {time_str}, {day_name}. {question}",
                    f"Olá! {time_greeting}. São {time_str} de {day_name}. {question}",
                    f"{time_greeting}! Hoje é {day_name}, {time_str}. {question}",
                    f"{time_greeting}! {day_name.capitalize()}, {time_str}. {question}",
                ]
            greeting = random.choice(greetings)

            print(f"[Greeting] {greeting}")

            # Update UI
            self._update_ui_response(greeting)

            # Play greeting audio using Gemini TTS if available (for voice consistency)
            def speak():
                try:
                    # Use Gemini native audio if available for consistent voice
                    if self._gemini_audio and self._gemini_audio.is_available():
                        print("[Greeting] Using Gemini native audio for greeting")
                        import asyncio
                        audio_bytes = asyncio.run(self._gemini_audio.speak_text(greeting))
                        if audio_bytes:
                            self._play_audio_bytes(audio_bytes)
                        else:
                            # Fallback to regular TTS
                            self.tts.play_direct(greeting)
                    else:
                        # Use regular TTS as fallback
                        self.tts.play_direct(greeting)
                except Exception as e:
                    print(f"[Greeting] Gemini TTS error: {e}, falling back to regular TTS")
                    try:
                        self.tts.play_direct(greeting)
                    except Exception as e2:
                        print(f"[Greeting] Fallback TTS error: {e2}")

            threading.Thread(target=speak, daemon=True).start()

        except Exception as e:
            print(f"[Greeting] Error: {e}")

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

    def _on_audio_level(self, level: float) -> None:
        """Update UI with audio level during push-to-talk recording."""
        if self.state == "recording":
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

        # --- Try Gemini native audio first ---
        if self._gemini_audio and self._gemini_audio.is_available():
            try:
                self._process_audio_gemini(audio_data)
                # After Gemini playback, go back to listening in live mode
                if self._live_mode and self.state == "idle":
                    self.state = "listening"
                    self._update_ui_state()
                return
            except QuotaExceededError:
                print("[Gemini] Quota exceeded, falling back to STT+LLM+TTS pipeline")
                self.ui.set_subtitle("Modo local...")
            except Exception as e:
                print(f"[Gemini] Error, falling back: {e}")
                self.ui.set_subtitle("Modo local...")
            # If Gemini failed, continue with fallback pipeline below

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

        llm_model_lower = self.llm.model.lower()
        supports_tools = any(model in llm_model_lower for model in [
            "qwen2.5", "qwen3.5", "llama3.2", "mistral", "llama-3.1"
        ])
        groq_supports_tools = isinstance(self.llm, GroqClient) and "llama-3.1" in llm_model_lower
        model_supports_tools = supports_tools or groq_supports_tools

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

        # Check if response looks like an error message
        error_indicators = ['error:', 'error code:', 'exception', 'traceback', 'failed_generation', '400', '401', '403', '429', '500', '503']
        is_error_message = any(indicator in full_response.lower() for indicator in error_indicators)
        
        if is_error_message:
            print(f"[ERROR] Detected error in response (live mode), filtering: {full_response[:200]}...")
            full_response = "Desculpe, tive um problema técnico. Pode tentar de novo?"

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
