"""Gemini Native Audio client using Live API for real-time voice conversation.

Uses the gemini-2.5-flash-native-audio-preview model with Live API (WebSockets)
to enable bidirectional streaming audio — no separate STT/TTS needed.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
import wave
from pathlib import Path
from typing import Optional, Callable

import numpy as np


class QuotaExceededError(Exception):
    """Raised when Gemini API quota is exhausted (HTTP 429)."""
    pass


class GeminiAudioClient:
    """Gemini Live API client — real-time bidirectional audio streaming.
    
    Uses WebSockets for persistent connection, enabling natural turn-taking
    and real-time voice conversation.

    Reads the API key from:
      1. os.environ (GEMINI_API_KEY or GOOGLE_API_KEY)
      2. ~/.openjarvis/cloud-keys.env
      3. ~/.openjarvis/credentials.toml (via inject_credentials)
    """

    MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
    VOICE = "Puck"
    COOLDOWN_SECONDS = 60
    SAMPLE_RATE = 16000

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or self._resolve_api_key()
        self._client = None
        self._cooldown_until = 0.0
        self._disabled = False
        self._tool_executor = None  # Will be set externally
        
        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
                print(f"[Gemini] Live API client ready for {self.MODEL}")
            except ImportError:
                print("[Gemini] google-genai not installed. Run: pip install google-genai")
            except Exception as e:
                print(f"[Gemini] Error creating client: {e}")
        else:
            print("[Gemini] No API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY.")

    def set_tool_executor(self, executor):
        """Set the tool executor for function calling."""
        self._tool_executor = executor

    @staticmethod
    def _resolve_api_key() -> Optional[str]:
        """Resolve API key from env vars and config files."""
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            return key

        cloud_env = Path.home() / ".openjarvis" / "cloud-keys.env"
        if cloud_env.exists():
            for raw in cloud_env.read_text().splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v:
                        return v

        cred_toml = Path.home() / ".openjarvis" / "credentials.toml"
        if cred_toml.exists():
            try:
                import tomllib
            except ModuleNotFoundError:
                try:
                    import tomli as tomllib
                except ImportError:
                    tomllib = None

            if tomllib:
                try:
                    with open(cred_toml, "rb") as f:
                        creds = tomllib.load(f)
                    google_section = creds.get("google", {})
                    key = google_section.get("GOOGLE_API_KEY")
                    if key:
                        return key
                except Exception:
                    pass

        return None

    def is_available(self) -> bool:
        """Check if Gemini Live API is available and not in cooldown."""
        if self._client is None or self._disabled:
            return False
        if time.time() < self._cooldown_until:
            remaining = int(self._cooldown_until - time.time())
            print(f"[Gemini] In cooldown for {remaining}s")
            return False
        return True

    def _create_session(self, tools: Optional[list] = None, system_instruction: Optional[str] = None):
        """Create a Live API session with audio configuration.
        
        Args:
            tools: Optional list of tool definitions for function calling
            system_instruction: Optional system prompt
            
        Returns:
            Async context manager for the session
        """
        from google.genai import types
        
        # Build tools config if provided
        gemini_tools = None
        if tools:
            gemini_tools = []
            for tool in tools:
                if isinstance(tool, dict):
                    func = tool.get('function', {})
                    gemini_tools.append(types.Tool(
                        function_declarations=[{
                            'name': func.get('name'),
                            'description': func.get('description'),
                            'parameters': func.get('parameters'),
                        }]
                    ))
                else:
                    gemini_tools.append(tool)
        
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.VOICE,
                    )
                )
            ),
            thinking_config=types.ThinkingConfig(
                thinking_budget=0,
            ),
            tools=gemini_tools,
            system_instruction=system_instruction if system_instruction else None,
        )
        
        return self._client.aio.live.connect(
            model=self.MODEL,
            config=config,
        )

    async def chat_audio(
        self,
        audio_data: bytes,
        system_prompt: Optional[str] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        tools: Optional[list] = None,
    ) -> tuple[bytes, str]:
        """Send audio to Gemini Live API and receive audio back.
        
        Args:
            audio_data: WAV or raw PCM audio bytes
            system_prompt: Optional system instructions
            on_audio_chunk: Optional callback for streaming audio chunks
            tools: Optional list of tool definitions for function calling
            
        Returns:
            (complete_audio_bytes, transcript_text)
            
        Raises:
            QuotaExceededError: on rate limit
            Exception: on other API errors
        """
        from google.genai import types
        import asyncio
        
        if not self.is_available():
            raise RuntimeError("Gemini Live API not available")

        print(f"[Gemini] Processing audio input: {len(audio_data)} bytes")
        pcm_data, sample_rate = self._extract_pcm(audio_data)
        print(f"[Gemini] PCM data: {len(pcm_data)} bytes, {sample_rate}Hz")
        
        audio_chunks = []
        transcript_parts = []
        response_received = False
        max_tool_iterations = 5
        
        try:
            # Create session with tools if provided
            session_cm = self._create_session(tools=tools, system_instruction=system_prompt)
            
            async with session_cm as session:
                print(f"[Gemini] Session started. Tools: {len(tools) if tools else 0}")
                
                # Send audio input
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_data,
                        mime_type=f"audio/pcm;rate={sample_rate}",
                    )
                )
                
                # Signal end of audio stream
                print("[Gemini] Sending audio_stream_end signal...")
                await session.send_realtime_input(audio_stream_end=True)
                
                # Collect responses with tool calling support
                max_wait = 60  # seconds (increased for tool execution)
                tool_iteration = 0
                
                async def _collect_and_process():
                    nonlocal response_received, audio_chunks, transcript_parts, tool_iteration
                    
                    while tool_iteration < max_tool_iterations:
                        try:
                            async for response in session.receive():
                                if not response.server_content:
                                    # Check for other response types
                                    if hasattr(response, 'tool_call') and response.tool_call:
                                        print(f"[Gemini] Tool call received: {response.tool_call}")
                                    continue
                                
                                server_content = response.server_content
                                
                                # Check for turn completion
                                if server_content.turn_complete:
                                    print(f"[Gemini] Turn complete. Chunks: {len(audio_chunks)}, Transcript: {transcript_parts}")
                                    response_received = True
                                    return
                                
                                # Check for interruption
                                if server_content.interrupted:
                                    print("[Gemini] Response interrupted by user")
                                    response_received = True
                                    return
                                
                                # Extract tool calls
                                model_turn = server_content.model_turn
                                if model_turn and model_turn.parts:
                                    has_tool_call = False
                                    tool_calls_data = []
                                    
                                    for part in model_turn.parts:
                                        # Audio data
                                        if part.inline_data and part.inline_data.data:
                                            chunk = part.inline_data.data
                                            if chunk:
                                                print(f"[Gemini] Received audio chunk: {len(chunk)} bytes")
                                                audio_chunks.append(chunk)
                                                response_received = True
                                                if on_audio_chunk:
                                                    on_audio_chunk(chunk)
                                        
                                        # Text transcript
                                        if part.text:
                                            print(f"[Gemini] Received text: {part.text[:80]}...")
                                            transcript_parts.append(part.text)
                                            response_received = True
                                        
                                        # Check for function call
                                        if part.function_call:
                                            has_tool_call = True
                                            call = part.function_call
                                            tool_calls_data.append({
                                                'name': call.name,
                                                'args': dict(call.args) if call.args else {}
                                            })
                                            print(f"[Gemini] Function call: {call.name}({call.args})")
                                    
                                    # Process tool calls
                                    if has_tool_call and self._tool_executor and tool_calls_data:
                                        tool_iteration += 1
                                        print(f"[Gemini] Processing {len(tool_calls_data)} tool call(s)...")
                                        
                                        for tool_call in tool_calls_data:
                                            try:
                                                result = self._tool_executor.execute(
                                                    tool_call['name'], 
                                                    tool_call['args']
                                                )
                                                print(f"[Gemini] Tool '{tool_call['name']}' result: {result.content[:100] if result.content else 'empty'}...")
                                                
                                                # Send tool response back - try with and without ID
                                                if hasattr(response.server_content, 'tool_call_id') and response.server_content.tool_call_id:
                                                    tool_response = types.FunctionResponse(
                                                        id=response.server_content.tool_call_id,
                                                        name=tool_call['name'],
                                                        response={"result": result.content, "success": result.success},
                                                    )
                                                else:
                                                    tool_response = types.FunctionResponse(
                                                        name=tool_call['name'],
                                                        response={"result": result.content, "success": result.success},
                                                    )
                                                
                                                await session.send(input=tool_response, end_of_turn=True)
                                                print(f"[Gemini] Tool response sent for: {tool_call['name']}")
                                                
                                            except Exception as e:
                                                print(f"[Gemini] Tool execution error: {e}")
                                                await session.send(
                                                    input=types.FunctionResponse(
                                                        name=tool_call['name'],
                                                        response={"error": str(e)},
                                                    ),
                                                    end_of_turn=True,
                                                )
                                        
                                        # Continue collecting responses after tool execution
                                        continue
                                    
                                    # If no tool calls, we're done
                                    if has_tool_call and not tool_calls_data:
                                        # Model wants to call tools but we don't have executor
                                        print("[Gemini] Tool call detected but no executor available")
                                        
                        except Exception as e:
                            print(f"[Gemini] Error in response loop: {e}")
                            break
                    
                    print(f"[Gemini] Max tool iterations reached or session ended")
                
                try:
                    await asyncio.wait_for(_collect_and_process(), timeout=max_wait)
                except asyncio.TimeoutError:
                    print(f"[Gemini] Timeout after {max_wait}s, returning what we have")
                    
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                print(f"[Gemini] Rate limit (429), entering cooldown: {e}")
                self._cooldown_until = time.time() + self.COOLDOWN_SECONDS
                raise QuotaExceededError(str(e)) from e
            if "401" in err_str or "403" in err_str:
                print(f"[Gemini] Auth error, disabling: {e}")
                self._disabled = True
                raise
            if "404" in err_str or "not found" in err_str.lower():
                print(f"[Gemini] Model not found (404), disabling: {e}")
                self._disabled = True
                raise RuntimeError(f"Model not found: {e}") from e
            print(f"[Gemini] Live API error: {e}")
            raise
        
        # Combine audio chunks
        if not audio_chunks:
            if response_received:
                print(f"[Gemini] Got text response but no audio. Text: {transcript_parts}")
            raise RuntimeError(f"No audio response received (got text: {bool(transcript_parts)})")
        
        # Audio from Live API is PCM, convert to WAV (24kHz is Gemini's output rate)
        raw_audio = b"".join(audio_chunks)
        wav_audio = self._pcm_to_wav(raw_audio, sample_rate=24000)
        
        transcript = " ".join(transcript_parts) if transcript_parts else ""
        
        print(f"[Gemini] Success: {len(wav_audio)} bytes WAV, transcript: {transcript[:50] if transcript else 'None'}...")
        return wav_audio, transcript

    async def speak_text(self, text: str) -> bytes:
        """Generate speech from text using Gemini's native audio output.
        
        Args:
            text: Text to speak
            
        Returns:
            WAV audio bytes
        """
        from google.genai import types
        
        if not self.is_available():
            raise RuntimeError("Gemini Live API not available")
        
        # Create a simple session for text-to-speech
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.VOICE,
                    )
                )
            ),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        
        audio_chunks = []
        transcript_parts = []
        
        try:
            session_cm = self._client.aio.live.connect(model=self.MODEL, config=config)
            
            async with session_cm as session:
                await session.send(input=text, end_of_turn=True)
                
                # Collect audio response
                async for response in session.receive():
                    if not response.server_content:
                        continue
                    
                    if response.server_content.turn_complete:
                        break
                    
                    model_turn = response.server_content.model_turn
                    if model_turn and model_turn.parts:
                        for part in model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                audio_chunks.append(part.inline_data.data)
                            if part.text:
                                transcript_parts.append(part.text)
                                
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower():
                self._cooldown_until = time.time() + self.COOLDOWN_SECONDS
                raise QuotaExceededError(str(e)) from e
            if "401" in err_str or "403" in err_str:
                self._disabled = True
            raise
        
        if not audio_chunks:
            raise RuntimeError("No audio generated from text")
        
        # Combine and convert to WAV
        raw_audio = b"".join(audio_chunks)
        wav_audio = self._pcm_to_wav(raw_audio, sample_rate=24000)
        
        # Log transcript for debugging - verify it matches what we sent
        transcript = " ".join(transcript_parts) if transcript_parts else ""
        if transcript and transcript.strip().lower() != text.strip().lower():
            print(f"[Gemini TTS] Warning: Transcript differs from input!")
            print(f"  Input: {text[:80]}...")
            print(f"  Got:   {transcript[:80]}...")
        
        print(f"[Gemini TTS] Generated {len(wav_audio)} bytes for: {text[:50]}...")
        return wav_audio

    @staticmethod
    def _extract_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
        """Extract raw PCM data and sample rate from WAV bytes."""
        try:
            buffer = io.BytesIO(wav_bytes)
            with wave.open(buffer, "rb") as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)

            # Convert to mono 16-bit if needed
            if n_channels > 1 or sample_width != 2:
                try:
                    import soundfile as sf
                    buffer.seek(0)
                    data, sr = sf.read(buffer, dtype="int16")
                    if data.ndim > 1:
                        data = data.mean(axis=1).astype(np.int16)
                    if sr != 16000:
                        try:
                            import librosa
                            data_float = data.astype(np.float32) / 32767.0
                            data_resampled = librosa.resample(data_float, orig_sr=sr, target_sr=16000)
                            data = (data_resampled * 32767).astype(np.int16)
                            sr = 16000
                        except ImportError:
                            pass
                    raw = data.tobytes()
                    framerate = sr
                except ImportError:
                    pass

            return raw, framerate
        except Exception as e:
            print(f"[Gemini] WAV parse error, using raw bytes: {e}")
            return wav_bytes, 16000

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
        """Convert raw PCM data to WAV bytes."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        buffer.seek(0)
        return buffer.read()

    def health(self) -> bool:
        """Check if the client is usable."""
        return self._client is not None and not self._disabled

    def clear_history(self) -> None:
        """Clear conversation history (sessions are stateless in Live API)."""
        pass
