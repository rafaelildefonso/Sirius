"""LLM communication with Ollama (local)."""

from __future__ import annotations

import json
import time
from typing import Iterator, Optional

import httpx


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
        self.system_prompt = system_prompt or (
            "Você é Jarvis, um assistente de IA útil e conciso para conversa por voz. "
            "REGRAS ABSOLUTAS que você DEVE seguir:\n"
            "1. NUNCA use emojis - proibido completamente\n"
            "2. NUNCA use formatação markdown - proibido: **, *, _, #, ##, ###, `, ```\n"
            "3. NUNCA use listas com bullets ou números - proibido: -, *, 1., 2.\n"
            "4. NUNCA use código ou blocos de código\n"
            "5. SEMPRE responda em texto simples e contínuo\n"
            "6. Responda como em uma conversa natural de voz, em uma ou duas frases curtas\n"
            "Se você usar qualquer emoji ou formatação, sua resposta será rejeitada."
        )
        self._client = httpx.Client(timeout=60.0)

    def chat(self, message: str, history: Optional[list[dict]] = None) -> str:
        """Send a message and get a complete response."""
        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

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

    def chat_stream(self, message: str, history: Optional[list[dict]] = None) -> Iterator[str]:
        """Stream response tokens as they're generated."""
        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

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
                        "num_predict": 256,
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
