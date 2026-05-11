"""LLM communication with Ollama (local)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import httpx

try:
    from voice_assistant.user_profile import get_profile_manager
except ImportError:
    get_profile_manager = None


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""

    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResponse:
    """Response from chat with optional tool calls."""

    text: str = ""
    tool_calls: List[ToolCall] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class OllamaClient:
    """Client for local Ollama API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3.5:2b",
        system_prompt: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        
        # Base prompt with rules
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
        
        # Load user profile and personalize prompt
        if system_prompt:
            self.system_prompt = system_prompt
        elif get_profile_manager:
            profile_manager = get_profile_manager()
            self.system_prompt = profile_manager.get_full_system_prompt(base_prompt)
        else:
            # Default fallback
            self.system_prompt = (
                "Você é Sirius, um assistente pessoal de IA com personalidade amigável e conversacional. "
                + base_prompt
            )
        
        # Longer timeout for slow models (qwen3.5 can take 30-60s on CPU)
        timeout = httpx.Timeout(90.0, connect=10.0)
        self._client = httpx.Client(timeout=timeout)

    def chat(self, message: str, history: Optional[list[dict]] = None, system_prompt: Optional[str] = None) -> str:
        """Send a message and get a complete response."""
        messages = []

        active_system_prompt = system_prompt or self.system_prompt
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        try:
            response = self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 256,  # Limit response length for voice
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            return self._clean_response(content)

        except httpx.ConnectError:
            return "Erro: Não foi possível conectar ao Ollama. Verifique se está rodando com 'ollama serve'."
        except Exception as e:
            return f"Erro ao gerar resposta: {e}"

    def chat_stream(self, message: str, history: Optional[list[dict]] = None, system_prompt: Optional[str] = None) -> Iterator[str]:
        """Stream response tokens as they're generated."""
        messages = []

        active_system_prompt = system_prompt or self.system_prompt
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 150,
                        "num_ctx": 1024,
                    },
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "message" in data:
                            content = data["message"].get("content", "")
                            if content:
                                # Don't clean individual tokens - clean full response at end
                                yield content
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

        except httpx.ConnectError:
            yield "Erro: Não foi possível conectar ao Ollama."
        except Exception as e:
            yield f"Erro: {e}"

    def chat_with_tools(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ) -> ChatResponse:
        """Send a message with tool definitions and get response with possible tool calls."""
        messages = []

        active_system_prompt = system_prompt or self.system_prompt
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        try:
            response = self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 200,
                        "num_ctx": 1024,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            message_data = data.get("message", {})

            # Check for tool calls
            tool_calls = []
            if "tool_calls" in message_data:
                for call in message_data["tool_calls"]:
                    func = call.get("function", {})
                    if func:
                        # arguments may be dict or JSON string
                        args = func.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        tool_calls.append(
                            ToolCall(
                                name=func.get("name", ""),
                                arguments=args,
                            )
                        )

            raw_content = message_data.get("content", "")
            thinking = message_data.get("thinking", "")
            if thinking:
                print(f"[Thinking] {thinking[:200]}...")
            content = raw_content.strip() if raw_content else ""
            content = self._clean_response(content)
            
            # Only use fallback if content is empty AND there are no tool calls
            # If there are tool calls, let main.py handle the execution
            if not content and not tool_calls:
                content = "Desculpe, não consegui processar essa pergunta. Pode repetir?"
                print(f"[DEBUG LLM] Response was empty, using fallback")

            return ChatResponse(text=content, tool_calls=tool_calls)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                # Model doesn't support tools - return special error for fallback
                return ChatResponse(
                    text="__TOOLS_NOT_SUPPORTED__",
                    tool_calls=[],
                )
            return ChatResponse(
                text=f"Erro HTTP {e.response.status_code}: {e.response.text[:100]}",
                tool_calls=[],
            )
        except httpx.ConnectError:
            return ChatResponse(
                text="Erro: Não foi possível conectar ao Ollama. Verifique se está rodando.",
                tool_calls=[],
            )
        except httpx.TimeoutException:
            return ChatResponse(
                text="Erro: O modelo demorou muito para responder. Tente uma pergunta mais simples.",
                tool_calls=[],
            )
        except Exception as e:
            return ChatResponse(
                text=f"Erro ao gerar resposta: {e}",
                tool_calls=[],
            )

    def chat_with_tools_stream(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
    ) -> Iterator[ChatResponse]:
        """Stream response with tool support - yields partial ChatResponse."""
        messages = []

        active_system_prompt = system_prompt or self.system_prompt
        if active_system_prompt:
            messages.append({"role": "system", "content": active_system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "stream": True,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 150,
                        "num_ctx": 1024,
                    },
                },
            ) as response:
                response.raise_for_status()

                accumulated_content = []
                tool_calls = []
                done = False

                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)

                        # Accumulate content
                        if "message" in data:
                            msg = data["message"]
                            if msg.get("content"):
                                accumulated_content.append(msg["content"])

                            # Check for tool calls in this chunk
                            if "tool_calls" in msg:
                                for call in msg["tool_calls"]:
                                    if call.get("type") == "function":
                                        func = call.get("function", {})
                                        tool_calls.append(
                                            ToolCall(
                                                name=func.get("name", ""),
                                                arguments=func.get("arguments", {}),
                                            )
                                        )

                        if data.get("done", False):
                            done = True
                            break

                        # Yield intermediate response
                        if accumulated_content:
                            partial_text = "".join(accumulated_content)
                            yield ChatResponse(
                                text=partial_text,
                                tool_calls=tool_calls,
                            )

                    except json.JSONDecodeError:
                        continue

                # Yield final response
                final_text = "".join(accumulated_content)
                final_text = self._clean_response(final_text)
                yield ChatResponse(text=final_text, tool_calls=tool_calls)

        except httpx.ConnectError:
            yield ChatResponse(
                text="Erro: Não foi possível conectar ao Ollama.",
                tool_calls=[],
            )
        except Exception as e:
            yield ChatResponse(
                text=f"Erro: {e}",
                tool_calls=[],
            )

    def _clean_response(self, text: str) -> str:
        """Remove emojis and markdown formatting from response."""
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
        text = re.sub(r"_", "", text)   # italic underscore
        text = re.sub(r"`", "", text)    # inline code
        text = re.sub(r"#+", "", text)   # headers
        text = re.sub(r"^-+\s*", "", text, flags=re.MULTILINE)  # bullet lists
        text = re.sub(r"^\*+\s*", "", text, flags=re.MULTILINE)  # asterisk lists
        text = re.sub(r"^\d+\.[\s]+", "", text, flags=re.MULTILINE)  # numbered lists

        # Normalize whitespace: multiple spaces -> single space, but preserve single spaces
        text = re.sub(r"  +", " ", text)  # 2+ spaces -> 1 space
        text = re.sub(r"\t", " ", text)  # tabs -> space
        text = re.sub(r"\n\s*\n", "\n", text)  # empty lines
        text = text.strip()

        return text

    def health(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available models in Ollama."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return [m.get("name", m.get("model", "")) for m in data.get("models", [])]
        except Exception:
            return []

    def __del__(self):
        """Cleanup."""
        try:
            self._client.close()
        except Exception:
            pass
