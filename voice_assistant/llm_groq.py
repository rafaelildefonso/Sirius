"""Groq API client for fast LLM inference with tool calling."""

from __future__ import annotations

import os
from typing import Optional, Any
from dataclasses import dataclass
import sys

try:
    from voice_assistant.user_profile import get_profile_manager
except ImportError:
    get_profile_manager = None


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


def _load_groq_key_from_credentials() -> Optional[str]:
    """Load GROQ_API_KEY from centralized credentials.toml (set by frontend)."""
    try:
        # Add src to path if needed
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.normpath(os.path.join(script_dir, '..'))
        src_path = os.path.join(project_root, 'src')
        if src_path not in sys.path:
            sys.path.append(src_path)

        from openjarvis.core.credentials import get_tool_credential
        key = get_tool_credential("groq", "GROQ_API_KEY")
        if key:
            print(f"[Groq] Loaded API key from credentials.toml (frontend)")
            return key
    except Exception as e:
        print(f"[Groq] Could not load from credentials.toml: {e}")
    return None


class GroqClient:
    """Fast LLM client using Groq API with fallback to local Ollama."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "llama-3.1-70b-versatile",
        fallback_client: Optional[Any] = None,
    ):
        _load_env_file()

        # Try to get API key in order of priority:
        # 1. Explicitly passed api_key parameter
        # 2. Environment variable (from .env or system)
        # 3. Centralized credentials.toml (from frontend)
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            self.api_key = _load_groq_key_from_credentials()
            if self.api_key:
                # Set in env for future use
                os.environ["GROQ_API_KEY"] = self.api_key

        self.model = model
        self.fallback_client = fallback_client
        self._client = None
        self._cooldown_until = 0  # Timestamp until which we should avoid Groq

        if self.api_key:
            key_preview = self.api_key[:10] + "..." if len(self.api_key) > 10 else "..."
            print(f"[Groq] Using API key: {key_preview}")
        else:
            print("[Groq] No API key found. Add in Frontend Settings or set GROQ_API_KEY env var.")

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

    def _get_system_prompt(self, custom_prompt: Optional[str] = None) -> Optional[str]:
        """Get personalized system prompt based on user profile."""
        if custom_prompt:
            return custom_prompt
        
        if get_profile_manager:
            try:
                profile_manager = get_profile_manager()
                base_prompt = (
                    "REGRAS OBRIGATÓRIAS:\n"
                    "1. NUNCA use emojis - proibido completamente\n"
                    "2. NUNCA use formatação markdown - proibido: **, *, _, #, ##, ###, `, ```\n"
                    "3. NUNCA use listas com bullets ou números - proibido: -, *, 1., 2.\n"
                    "4. NUNCA use código ou blocos de código\n"
                    "5. SEMPRE responda em texto simples natural, como conversa\n"
                    "6. Responda como conversando com uma pessoa, não como máquina\n"
                    "\n"
                    "REGRA CRÍTICA - USE FERRAMENTAS:\n"
                    "Quando o usuário perguntar sobre FATOS, DADOS, ESTATÍSTICAS, ou informações que precisam de verificação "
                    "(como 'animais mais rápidos', 'capital da França', 'preço do dólar', etc), "
                    "VOCÊ DEVE usar a ferramenta 'search_web' para buscar a informação correta. "
                    "NUNCA invente respostas. Sempre use search_web para fatos.\n"
                    "\n"
                    "FERRAMENTAS disponíveis:\n"
                    "- search_web: OBRIGATÓRIO para pesquisar fatos e dados na internet\n"
                    "- open_url: abrir sites\n"
                    "- open_application: abrir apps\n"
                    "- get_current_time: saber hora atual\n"
                    "- set_system_volume: ajustar volume\n"
                    "- youtube_search_and_play: buscar e tocar no YouTube\n"
                    "- browser_search: pesquisar em sites específicos\n"
                    "- browser_search_and_click: pesquisar e clicar no primeiro resultado\n"
                    "- focus_window: trazer janela para frente\n"
                    "- close_window: fechar aplicativo\n"
                    "- minimize_window: minimizar janela\n"
                    "- maximize_window: maximizar janela\n"
                    "- list_running_apps: listar apps abertos\n"
                    "- send_hotkey: enviar atalhos de teclado\n"
                    "\n"
                    "EXEMPLOS:\n"
                    "- Usuário: 'Quais os animais mais rápidos?' → Use: search_web\n"
                    "- Usuário: 'Que horas são?' → Use: get_current_time\n"
                    "- Usuário: 'Abre o YouTube' → Use: open_application\n"
                    "- Usuário: 'Toca música' → Use: youtube_search_and_play"
                )
                return profile_manager.get_full_system_prompt(base_prompt)
            except Exception as e:
                print(f"[Groq] Error loading user profile: {e}")
        
        return None

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
            models = ["llama-3.1-70b-versatile", "llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"]
        
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

        # Get personalized system prompt from user profile if none provided
        active_system_prompt = system_prompt or self._get_system_prompt()
        
        messages = []
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})
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
        """Chat with tool calling support using Groq API.

        Tries Groq first, falls back to local Ollama only on errors.
        """
        if not self.is_available():
            # Groq not available, use fallback
            if self.fallback_client and hasattr(self.fallback_client, 'chat_with_tools'):
                print("[Groq] Not available, using Ollama local model...")
                return self.fallback_client.chat_with_tools(message, tools, history, system_prompt)
            return ChatResponse(
                text="Desculpe, não consegui processar agora.",
                tool_calls=[],
                model="none"
            )

        # Get personalized system prompt from user profile if none provided
        active_system_prompt = system_prompt or self._get_system_prompt()
        
        messages = []
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})
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
                temperature=0.7,
                max_tokens=1024,
            )

            print(f"[Groq] ✓ API request successful (model: {self.model})")
            msg = response.choices[0].message
            text = msg.content or ""

            # Extract tool calls
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        import json
                        args = tc.function.arguments
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                # Try to fix common encoding issues
                                args_str = args.encode('utf-8').decode('unicode_escape')
                                try:
                                    args = json.loads(args_str)
                                except:
                                    print(f"[Groq] Warning: Could not parse tool args: {args[:50]}...")
                                    continue
                        
                        # Validate arguments is a dict
                        if not isinstance(args, dict):
                            print(f"[Groq] Warning: Tool args not a dict: {type(args)}")
                            continue
                            
                        tool_calls.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": args,
                        })
                        print(f"[Groq] Parsed tool call: {tc.function.name}")
                    except Exception as e:
                        print(f"[Groq] Warning: Could not parse tool call arguments: {e}")
                        continue

            return ChatResponse(
                text=text,
                tool_calls=tool_calls,
                model=self.model,
            )

        except Exception as e:
            error_str = str(e).lower()
            # Only fallback on specific errors (rate limit, auth, server errors)
            is_recoverable_error = any([
                "429" in str(e),
                "rate limit" in error_str,
                "401" in str(e),
                "403" in str(e),
                "500" in str(e),
                "503" in str(e),
                "timeout" in error_str,
                "connection" in error_str,
            ])

            if is_recoverable_error and self.fallback_client:
                print(f"[Groq] API error ({e}), falling back to Ollama...")
                self._handle_error(e)
                return self.fallback_client.chat_with_tools(message, tools, history, system_prompt)
            else:
                # Non-recoverable error or no fallback
                error_msg = str(e)
                print(f"[Groq] Error: {error_msg}")
                
                # Check if it's a tool use error (model generated malformed tool call)
                if "tool_use_failed" in error_msg.lower() or "failed to call a function" in error_msg.lower():
                    print(f"[Groq] Tool call failed, attempting to parse from error...")
                    
                    # Try to extract tool call from failed_generation
                    import re
                    import json
                    match = re.search(r'<function=(\w+)\s*\{([^}]+)\}', error_msg)
                    if match:
                        tool_name = match.group(1)
                        raw_args = match.group(2)
                        try:
                            # Parse arguments intelligently
                            args = {}
                            
                            # Try full JSON parse first
                            try:
                                full_json = '{' + raw_args + '}'
                                args = json.loads(full_json)
                            except json.JSONDecodeError:
                                # Extract individual fields: "key": "value"
                                for field_match in re.finditer(r'"(\w+)":\s*"([^"]+)"', raw_args):
                                    args[field_match.group(1)] = field_match.group(2)
                                # Try integer values
                                for field_match in re.finditer(r'"(\w+)":\s*(\d+)', raw_args):
                                    args[field_match.group(1)] = int(field_match.group(2))
                                # Try boolean values
                                for field_match in re.finditer(r'"(\w+)":\s*(true|false)', raw_args, re.IGNORECASE):
                                    args[field_match.group(1)] = field_match.group(2).lower() == 'true'
                            
                            if not args:
                                args = {"raw": raw_args.strip()}
                            
                            print(f"[Groq] Extracted tool: {tool_name} with args: {args}")
                            
                            # Return a response with the tool call to be executed
                            return ChatResponse(
                                text=f"Executando {tool_name}...",
                                tool_calls=[{"id": "recovered", "name": tool_name, "arguments": args}],
                                model=self.model,
                            )
                        except Exception as parse_err:
                            print(f"[Groq] Could not parse tool from error: {parse_err}")
                    
                    # If we can't parse, return error response
                    return ChatResponse(
                        text="Desculpe, tive um problema técnico com as ferramentas. Pode tentar de novo?",
                        tool_calls=[],
                        model=self.model,
                    )
                
                return ChatResponse(
                    text="Desculpe, tive um problema técnico. Pode tentar de novo?",
                    tool_calls=[],
                    model=self.model,
                )

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

        # Get personalized system prompt from user profile if none provided
        active_system_prompt = system_prompt or self._get_system_prompt()
        
        messages = []
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})
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
