"""Groq API client for fast LLM inference with tool calling."""

from __future__ import annotations

import os
from typing import Optional, Any
from dataclasses import dataclass
import sys


def _load_env_file():
    """Load .env file from project root if exists."""
    try:
        # Find .env file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.normpath(os.path.join(script_dir, '..'))
        env_path = os.path.join(project_root, '.env')

        print(f"[Groq] Looking for .env at: {env_path}")

        if os.path.exists(env_path):
            print(f"[Groq] Found .env file")
            with open(env_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"[Groq] .env content length: {len(content)} chars")
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = val
                            if key == 'GROQ_API_KEY':
                                print(f"[Groq] Loaded GROQ_API_KEY: {val[:10]}...")
            print(f"[Groq] .env loaded successfully")
        else:
            print("[Groq] No .env file found at expected location")
            print(f"[Groq] Current working dir: {os.getcwd()}")
            print(f"[Groq] Tried path: {env_path}")
    except Exception as e:
        print(f"[Groq] Error loading .env: {e}")
        import traceback
        traceback.print_exc()


# Load .env on module import
_load_env_file()


@dataclass
class ChatResponse:
    """Response from LLM."""
    text: str
    tool_calls: list[dict]
    model: str

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class GroqClient:
    """Fast LLM client using Groq API with fallback to local Ollama."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.3-70b-versatile",
        fallback_client: Optional[Any] = None,
    ):
        _load_env_file()
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.fallback_client = fallback_client
        self._client = None
        self._cooldown_until = 0  # Timestamp until which we should avoid Groq
        
        if self.api_key:
            key_preview = self.api_key[:10] + "..." if len(self.api_key) > 10 else "..."
            print(f"[Groq] Using API key: {key_preview}")
        else:
            print("[Groq] No API key found. Set GROQ_API_KEY env var.")

        if self.api_key:
            try:
                # Calculate project root to find .venv
                script_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.normpath(os.path.join(script_dir, '..'))
                
                # Force local .venv path if it exists to find 'groq'
                # Check for both Lib/site-packages (Windows) and lib/python*/site-packages (Linux/Mac)
                venv_lib = os.path.join(project_root, ".venv", "Lib", "site-packages")
                if not os.path.exists(venv_lib):
                    # Try linux style
                    import glob
                    linux_site = glob.glob(os.path.join(project_root, ".venv", "lib", "python*", "site-packages"))
                    if linux_site:
                        venv_lib = linux_site[0]

                if os.path.exists(venv_lib) and venv_lib not in sys.path:
                    sys.path.insert(0, venv_lib)
                
                from groq import Groq
                self._client = Groq(api_key=self.api_key)
                print(f"[Groq] Client created successfully for model {model}")
            except ImportError:
                print("[Groq] ImportError: 'groq' package not found. Please ensure it is installed in .venv.")
                print(f"[Groq] sys.path: {sys.path[:3]}...")
            except Exception as e:
                print(f"[Groq] Unexpected error during client creation: {e}")
        else:
            print("[Groq] Cannot create client: GROQ_API_KEY is missing or empty.")

    def is_available(self) -> bool:
        """Check if Groq is available and not in cooldown."""
        import time
        if self._client is None:
            # Silently return False for main availability check
            return False
        if time.time() < self._cooldown_until:
            print(f"[Groq] In cooldown for {int(self._cooldown_until - time.time())}s")
            return False
        return True

    def health(self) -> bool:
        """Check health for startup dependency check."""
        # If Groq is available, it's healthy. 
        # If not, check if fallback is healthy.
        if self.is_available():
            return True
        if self.fallback_client and hasattr(self.fallback_client, 'health'):
            return self.fallback_client.health()
        return False

    def list_models(self) -> list[str]:
        """List available models. Returns Groq models if available, else Ollama models."""
        models = []
        if self.is_available():
            # For simplicity, return the main Groq models we support
            models = ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"]
        
        # Also include fallback models if available
        if self.fallback_client and hasattr(self.fallback_client, 'list_models'):
            fallback_models = self.fallback_client.list_models()
            models.extend([m for m in fallback_models if m not in models])
            
        return models

    def _clean_response(self, text: str) -> str:
        """Remove emojis and markdown formatting from response."""
        # Use fallback's cleaner if available
        if self.fallback_client and hasattr(self.fallback_client, '_clean_response'):
            return self.fallback_client._clean_response(text)
            
        import re
        # Remove emojis - comprehensive pattern
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "\U0001FA00-\U0001FA6F"  # chess symbols
            "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-a
            "\U00002600-\U000026FF"  # miscellaneous symbols
            "\U00002700-\U000027BF"  # dingbats
            "]+",
            flags=re.UNICODE,
        )
        text = emoji_pattern.sub("", text)

        # Remove markdown formatting
        text = re.sub(r"\*\*", "", text)  # bold
        text = re.sub(r"\*", "", text)    # italic
        text = re.sub(r"__", "", text)   # underline
        text = re.sub(r"_", "", text)    # italic underscore
        text = re.sub(r"`", "", text)    # inline code
        
        # Remove multiple spaces and newlines
        text = re.sub(r"\s+", " ", text)
        
        return text.strip()

    def _handle_error(self, e: Exception):
        """Analyze exception and set cooldown if it's a rate limit."""
        import time
        err_str = str(e).lower()
        if "429" in err_str or "rate limit" in err_str:
            print(f"[Groq] Rate limit reached! Cooling down for 60s. Error: {e}")
            self._cooldown_until = time.time() + 60
        else:
            print(f"[Groq] API Error: {e}")

    def chat(
        self,
        message: str,
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Simple chat without tools."""
        if not self.is_available():
            if self.fallback_client:
                print("[Groq] Falling back to local model (Ollama)...")
                return self.fallback_client.chat(message, history, system_prompt)
            return "Desculpe, não consegui processar agora."

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=512,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            self._handle_error(e)
            if self.fallback_client:
                return self.fallback_client.chat(message, history, system_prompt)
            return "Desculpe, não consegui processar agora."

    def chat_with_tools(
        self,
        message: str,
        tools: list[dict],
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ) -> ChatResponse:
        """Chat with tool calling support."""
        if not self.is_available():
            if self.fallback_client:
                print("[Groq] Falling back to local model (Ollama) for tool calling...")
                return self.fallback_client.chat_with_tools(message, tools, history, system_prompt)
            return ChatResponse(
                text="Desculpe, não consegui processar agora.",
                tool_calls=[],
                model="none"
            )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            # Convert tools to Groq format
            groq_tools = []
            for tool in tools:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["function"]["name"],
                        "description": tool["function"]["description"],
                        "parameters": tool["function"]["parameters"],
                    }
                })

            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=groq_tools if groq_tools else None,
                tool_choice="auto" if groq_tools else None,
                temperature=0.1, # Lower temperature for better tool calling
                max_tokens=1024,
            )

            print(f"[Groq] API request successful (model: {self.model})")
            msg = response.choices[0].message
            text = msg.content or ""

            # Extract tool calls
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    })

            return ChatResponse(
                text=text,
                tool_calls=tool_calls,
                model=self.model,
            )
        except Exception as e:
            print(f"[Groq] Error during chat_with_tools: {e}")
            self._handle_error(e)
            if self.fallback_client:
                print("[Groq] Falling back to local model (Ollama) due to API error...")
                return self.fallback_client.chat_with_tools(message, tools, history, system_prompt)
            raise e

    def chat_stream(
        self,
        message: str,
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ):
        """Stream response for faster perceived speed."""
        if not self.is_available():
            if self.fallback_client:
                print("[Groq] Falling back to local model (Ollama) stream...")
                yield from self.fallback_client.chat_stream(message, history, system_prompt)
            else:
                yield "Desculpe, não consegui processar agora."
            return

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=512,
                stream=True,
            )

            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

        except Exception as e:
            self._handle_error(e)
            if self.fallback_client:
                yield from self.fallback_client.chat_stream(message, history, system_prompt)
            else:
                yield "Desculpe, não consegui processar agora."
