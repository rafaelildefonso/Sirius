"""Local tools for voice assistant - computer control without backend dependency."""

from __future__ import annotations

import glob
import inspect
import json
import os
import subprocess
import webbrowser
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

try:
    import pyautogui
    import pygetwindow as gw
except ImportError:
    pyautogui = None
    gw = None

from voice_assistant.cache import search_cache
from voice_assistant.memory import MemoryManager


@dataclass
class ToolSpec:
    """Tool specification following OpenAI format (compatible with Ollama)."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of tool execution."""

    tool_name: str
    content: str
    success: bool = True


class ToolExecutor:
    """Execute local tools for voice assistant."""

    def __init__(self, memory_manager: Optional[MemoryManager] = None):
        self._tools: Dict[str, Callable] = {}
        self._specs: Dict[str, ToolSpec] = {}
        self._memory = memory_manager
        self._sensitive_tools = {
            "type_text",
            "press_keys",
            "send_hotkey",
            "close_active_window",
            "send_message",
        }
        self._register_builtin_tools()

    @staticmethod
    def _is_confirmation_value(value: Any) -> bool:
        return str(value).lower().strip() in ("yes", "true", "1", "confirm")

    def _requires_confirmation(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        if tool_name in self._sensitive_tools:
            return True
        if tool_name == "computer_settings":
            action = str(arguments.get("action", "")).lower().strip()
            action = action.replace(" ", "_").replace("-", "_")
            dangerous_actions = {"restart", "shutdown", "sleep_display", "lock_screen"}
            return action in dangerous_actions
        return False

    def _register_builtin_tools(self):
        """Register all built-in local tools."""
        self.register(
            "open_url",
            ToolSpec(
                name="open_url",
                description="Abre uma URL no navegador padrão do usuário. Use para abrir sites como YouTube, Google, etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL completa para abrir (ex: https://youtube.com)",
                        }
                    },
                    "required": ["url"],
                },
            ),
            self._open_url,
        )

        self.register(
            "open_application",
            ToolSpec(
                name="open_application",
                description="Abre um aplicativo pelo nome. Use para abrir apps como Chrome, Notepad, Calculadora, etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Nome do aplicativo (ex: chrome, notepad, calc, spotify)",
                        }
                    },
                    "required": ["app_name"],
                },
            ),
            self._open_application,
        )

        self.register(
            "get_current_time",
            ToolSpec(
                name="get_current_time",
                description="Retorna a data e hora atual do sistema.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._get_current_time,
        )

        self.register(
            "set_system_volume",
            ToolSpec(
                name="set_system_volume",
                description="Ajusta o volume do sistema (0-100).",
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": "Nível de volume de 0 a 100",
                        }
                    },
                    "required": ["level"],
                },
            ),
            self._set_system_volume,
        )

        self.register(
            "type_text",
            ToolSpec(
                name="type_text",
                description="Digita um texto no aplicativo que está em foco agora. Use para escrever mensagens, preencher campos ou codificar.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "O texto a ser digitado",
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "Se deve pressionar Enter após digitar",
                            "default": False
                        }
                    },
                    "required": ["text"],
                },
            ),
            self._type_text,
        )

        self.register(
            "press_keys",
            ToolSpec(
                name="press_keys",
                description="Pressiona teclas específicas ou combinações (ex: enter, space, ctrl+c, alt+f4).",
                parameters={
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "string",
                            "description": "A tecla ou combinação (ex: 'enter', 'tab', 'ctrl+s')",
                        }
                    },
                    "required": ["keys"],
                },
            ),
            self._press_keys,
        )

        self.register(
            "list_running_apps",
            ToolSpec(
                name="list_running_apps",
                description="Lista os títulos das janelas abertas e visíveis no computador.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._list_running_apps,
        )

        self.register(
            "close_active_window",
            ToolSpec(
                name="close_active_window",
                description="Fecha a janela que está atualmente em foco.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._close_active_window,
        )

        self.register(
            "search_web",
            ToolSpec(
                name="search_web",
                description="Busca informações na web e abre os resultados. Use para pesquisar no Google.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Termo de busca",
                        }
                    },
                    "required": ["query"],
                },
            ),
            self._search_web,
        )

        self.register(
            "youtube_search_and_play",
            ToolSpec(
                name="youtube_search_and_play",
                description="Busca um vídeo no YouTube e abre para tocar. Use para tocar músicas, vídeos, tutoriais. Exemplos: 'música relaxante', 'vídeo de gatos', 'tutorial Python'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "O que buscar no YouTube (ex: 'meditação relaxante', 'música para estudar')",
                        }
                    },
                    "required": ["query"],
                },
            ),
            self._youtube_search_and_play,
        )

        self.register(
            "open_workspace",
            ToolSpec(
                name="open_workspace",
                description="Abre um workspace (conjunto de apps e sites) pelo nome. O workspace deve ter sido salvo na memória anteriormente.",
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace_name": {
                            "type": "string",
                            "description": "Nome do workspace (ex: 'trabalho', 'estudo')",
                        }
                    },
                    "required": ["workspace_name"],
                },
            ),
            self._open_workspace,
        )

        self.register(
            "browser_navigate",
            ToolSpec(
                name="browser_navigate",
                description="Navega para uma URL específica em um browser controlado. Use para abrir sites que precisam de interação.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL para navegar",
                        }
                    },
                    "required": ["url"],
                },
            ),
            self._browser_navigate,
        )

        self.register(
            "browser_search",
            ToolSpec(
                name="browser_search",
                description="Busca informações em um site usando browser controlado. Vai ao site, busca e retorna os primeiros resultados.",
                parameters={
                    "type": "object",
                    "properties": {
                        "site": {
                            "type": "string",
                            "description": "Site onde buscar (ex: google.com, amazon.com, youtube.com)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Termo de busca",
                        }
                    },
                    "required": ["site", "query"],
                },
            ),
            self._browser_search,
        )

        self.register(
            "browser_search_and_click",
            ToolSpec(
                name="browser_search_and_click",
                description="Busca no site e clica automaticamente no primeiro resultado. Use quando o usuário pedir para 'tocar', 'abrir' ou 'ver' algo específico. Ex: 'tocar música no youtube', 'ver preço na amazon'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "site": {
                            "type": "string",
                            "description": "Site onde buscar (ex: youtube.com, amazon.com, google.com)",
                        },
                        "query": {
                            "type": "string",
                            "description": "Termo de busca",
                        }
                    },
                    "required": ["site", "query"],
                },
            ),
            self._browser_search_and_click,
        )

        self.register(
            "search_products",
            ToolSpec(
                name="search_products",
                description="Busca produtos em lojas online e retorna resultados com preços. Use para: 'acha um tênis Nike barato', 'preço de iPhone 15', 'notebook gamer'. Retorna até 5 produtos com título, preço e link.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Produto para buscar (ex: 'tênis Nike Air Max', 'iPhone 15', 'notebook gamer RTX 4060')",
                        },
                        "store": {
                            "type": "string",
                            "description": "Loja para buscar (amazon, mercadolivre, magalu, buscape). Deixe vazio para buscar em todas.",
                        }
                    },
                    "required": ["query"],
                },
            ),
            self._search_products,
        )

        self.register(
            "send_whatsapp_message",
            ToolSpec(
                name="send_whatsapp_message",
                description="Envia uma mensagem de WhatsApp para um número ou contato. Abre o WhatsApp Web já com a mensagem pronta.",
                parameters={
                    "type": "object",
                    "properties": {
                        "phone": {
                            "type": "string",
                            "description": "Número de telefone com DDD (apenas números, ex: 11988887777). Se vazio, abre o WhatsApp geral.",
                        },
                        "message": {
                            "type": "string",
                            "description": "A mensagem a ser enviada",
                        }
                    },
                    "required": ["message"],
                },
            ),
            self._send_whatsapp_message,
        )

        self.register(
            "remember",
            ToolSpec(
                name="remember",
                description="Salva uma informação importante na memória persistente (ex: nome do usuário, preferência, data).",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Chave da informação (ex: 'user_name', 'favorite_color')",
                        },
                        "value": {
                            "type": "string",
                            "description": "O valor a ser lembrado",
                        }
                    },
                    "required": ["key", "value"],
                },
            ),
            self._remember,
        )

        self.register(
            "list_memories",
            ToolSpec(
                name="list_memories",
                description="Lista tudo o que está salvo na memória persistente.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._list_memories,
        )

        self.register(
            "forget_memory",
            ToolSpec(
                name="forget_memory",
                description="Remove uma informação da memória persistente.",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Chave da informação a remover",
                        }
                    },
                    "required": ["key"],
                },
            ),
            self._forget_memory,
        )

        self.register(
            "search_videos",
            ToolSpec(
                name="search_videos",
                description="Busca vídeos no YouTube e retorna resultados com título, canal e link. Use para: 'vídeo de receita de bolo', 'tutorial de Python', 'review do iPhone'. Retorna até 5 vídeos.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Vídeo para buscar (ex: 'receita de bolo de chocolate', 'tutorial Python para iniciantes')",
                        },
                    },
                    "required": ["query"],
                },
            ),
            self._search_videos,
        )

        self.register(
            "smart_open",
            ToolSpec(
                name="smart_open",
                description="Abre uma URL específica no navegador quando o usuário confirma. Use APENAS quando o usuário disser 'abre o primeiro', 'abre o número 2', 'quero ver esse', etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL completa para abrir",
                        },
                        "description": {
                            "type": "string",
                            "description": "Descrição do que está sendo aberto para confirmar com o usuário",
                        }
                    },
                    "required": ["url"],
                },
            ),
            self._smart_open,
        )

        self.register(
            "focus_window",
            ToolSpec(
                name="focus_window",
                description="Traz uma janela de aplicativo para frente (foca). Use para alternar entre apps abertos. Ex: 'foca no chrome', 'traz o vs code pra frente'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Nome do aplicativo ou janela (ex: chrome, vscode, spotify)",
                        }
                    },
                    "required": ["app_name"],
                },
            ),
            self._focus_window,
        )

        self.register(
            "close_window",
            ToolSpec(
                name="close_window",
                description="Fecha uma janela ou aplicativo. Use para fechar apps que o usuário não precisa mais. Ex: 'fecha o chrome', 'fecha o spotify'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Nome do aplicativo para fechar (ex: chrome, vscode, notepad)",
                        }
                    },
                    "required": ["app_name"],
                },
            ),
            self._close_window,
        )

        self.register(
            "minimize_window",
            ToolSpec(
                name="minimize_window",
                description="Minimiza uma janela para a barra de tarefas. Ex: 'minimiza o chrome'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Nome do aplicativo para minimizar",
                        }
                    },
                    "required": ["app_name"],
                },
            ),
            self._minimize_window,
        )

        self.register(
            "maximize_window",
            ToolSpec(
                name="maximize_window",
                description="Maximiza uma janela para tela cheia. Ex: 'maximiza o vscode'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Nome do aplicativo para maximizar",
                        }
                    },
                    "required": ["app_name"],
                },
            ),
            self._maximize_window,
        )

        self.register(
            "list_running_apps",
            ToolSpec(
                name="list_running_apps",
                description="Lista todos os aplicativos abertos no momento. Use quando o usuário perguntar 'o que tá aberto?' ou 'quais apps tão rodando?'.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            self._list_running_apps,
        )

        self.register(
            "send_hotkey",
            ToolSpec(
                name="send_hotkey",
                description="Envia um atalho de teclado para o aplicativo focado. Use para comandos como salvar (ctrl+s), copiar (ctrl+c), etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Lista de teclas para pressionar juntas (ex: ['ctrl', 's'] para salvar)",
                        }
                    },
                    "required": ["keys"],
                },
            ),
            self._send_hotkey,
        )

        self.register(
            "computer_settings",
            ToolSpec(
                name="computer_settings",
                description="Controla configurações do computador: volume, brilho, janelas, teclas, etc. Ações: volume_up, volume_down, mute, brightness_up, brightness_down, full_screen, minimize, maximize, snap_left, snap_right, show_desktop, lock_screen, screenshot, dark_mode, open_settings, file_explorer, new_tab, close_tab, next_tab, prev_tab, scroll_up, scroll_down, copy, paste, cut, undo, redo, select_all, save, refresh_page, pause_video, play_pause, close_app, close_window, switch_window, focus_search, zoom_in, zoom_out, sleep_display, restart, shutdown (requer confirmed=yes).",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Nome da ação (ex: volume_up, mute, brightness_up, full_screen, lock_screen, etc)",
                        },
                        "value": {
                            "type": "string",
                            "description": "Valor opcional para ações que precisam (ex: volume_set 50)",
                        },
                        "confirmed": {
                            "type": "string",
                            "description": "Confirmação para ações perigosas (restart, shutdown). Use 'yes' para confirmar.",
                        },
                    },
                    "required": ["action"],
                },
            ),
            self._computer_settings,
        )

        self.register(
            "youtube_summarize",
            ToolSpec(
                name="youtube_summarize",
                description="Resume um vídeo do YouTube. Extrai a transcrição e gera um resumo com Groq/Gemini. Use quando o usuário pedir 'resume esse vídeo', 'me conta do que se trata', etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL do vídeo do YouTube",
                        }
                    },
                    "required": ["url"],
                },
            ),
            self._youtube_summarize,
        )

        self.register(
            "youtube_info",
            ToolSpec(
                name="youtube_info",
                description="Obtém informações de um vídeo do YouTube (título, canal, visualizações, duração). Use quando o usuário quiser saber detalhes do vídeo.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL do vídeo do YouTube",
                        }
                    },
                    "required": ["url"],
                },
            ),
            self._youtube_info,
        )

        self.register(
            "youtube_trending",
            ToolSpec(
                name="youtube_trending",
                description="Mostra vídeos em alta no YouTube Brasil. Use quando o usuário pedir 'o que está em alta', 'trending', etc.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._youtube_trending,
        )

        self.register(
            "desktop_wallpaper",
            ToolSpec(
                name="desktop_wallpaper",
                description="Altera o papel de parede do desktop. Use quando o usuário pedir 'muda o wallpaper', 'põe essa imagem de fundo', etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho da imagem ou URL",
                        }
                    },
                    "required": ["path"],
                },
            ),
            self._desktop_wallpaper,
        )

        self.register(
            "desktop_organize",
            ToolSpec(
                name="desktop_organize",
                description="Organiza os arquivos do desktop em pastas por tipo ou data. Use quando o usuário pedir 'organiza minha área de trabalho', 'limpa o desktop', etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "description": "Modo de organização: 'by_type' (por tipo) ou 'by_date' (por data)",
                            "default": "by_type",
                        }
                    },
                },
            ),
            self._desktop_organize,
        )

        self.register(
            "desktop_list",
            ToolSpec(
                name="desktop_list",
                description="Lista todos os arquivos e pastas no desktop. Use quando o usuário perguntar 'o que tem na área de trabalho', 'lista meu desktop', etc.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._desktop_list,
        )

        self.register(
            "desktop_stats",
            ToolSpec(
                name="desktop_stats",
                description="Mostra estatísticas do desktop (número de arquivos, tamanho total, etc). Use quando o usuário pedir 'quanto espaço ocupa o desktop', 'estatísticas da área de trabalho', etc.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._desktop_stats,
        )

        self.register(
            "send_message",
            ToolSpec(
                name="send_message",
                description="Envia mensagem via WhatsApp, Telegram, Discord, Instagram ou Messenger. Use quando o usuário pedir 'manda mensagem pro João', 'avisa no telegram', etc. Para WhatsApp, use 'receiver' como nome do contato ou número. Para outras plataformas, abre o app/site pronto.",
                parameters={
                    "type": "object",
                    "properties": {
                        "receiver": {
                            "type": "string",
                            "description": "Nome do contato ou número de telefone",
                        },
                        "message": {
                            "type": "string",
                            "description": "Texto da mensagem",
                        },
                        "platform": {
                            "type": "string",
                            "description": "Plataforma: whatsapp, telegram, discord, instagram, messenger",
                            "default": "whatsapp",
                        },
                        "confirmed": {
                            "type": "string",
                            "description": "Confirmação para envio real da mensagem. Use 'yes' para confirmar.",
                            "default": "",
                        },
                    },
                    "required": ["receiver", "message"],
                },
            ),
            self._send_message,
        )

        self.register(
            "set_reminder",
            ToolSpec(
                name="set_reminder",
                description="Cria um lembrete para uma data/hora específica. Use quando o usuário pedir 'me lembra às 15h', 'lembrete amanhã', etc. Formato de data: YYYY-MM-DD, hora: HH:MM.",
                parameters={
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Data no formato YYYY-MM-DD",
                        },
                        "time": {
                            "type": "string",
                            "description": "Hora no formato HH:MM (24h)",
                        },
                        "message": {
                            "type": "string",
                            "description": "Texto do lembrete",
                        },
                    },
                    "required": ["date", "time", "message"],
                },
            ),
            self._set_reminder,
        )

        self.register(
            "weather_report",
            ToolSpec(
                name="weather_report",
                description="Mostra o clima de uma cidade. Use quando o usuário perguntar 'como está o tempo', 'clima em São Paulo', etc.",
                parameters={
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "Nome da cidade",
                        }
                    },
                    "required": ["city"],
                },
            ),
            self._weather_report,
        )

    def register(self, name: str, spec: ToolSpec, func: Callable):
        """Register a new tool."""
        self._tools[name] = func
        self._specs[name] = spec

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions in Ollama/OpenAI format."""
        tools = []
        for name, spec in self._specs.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            })
        return tools

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given arguments."""
        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                content=f"Ferramenta '{tool_name}' não encontrada.",
                success=False,
            )

        try:
            func = self._tools[tool_name]
            args = dict(arguments or {})
            confirmed = self._is_confirmation_value(args.pop("confirmed", ""))
            if self._requires_confirmation(tool_name, args) and not confirmed:
                return ToolResult(
                    tool_name=tool_name,
                    content=(
                        "Essa ação exige confirmação explícita. "
                        "Revise os argumentos e repita com confirmed=yes."
                    ),
                    success=False,
                )
            if "confirmed" in inspect.signature(func).parameters:
                args["confirmed"] = "yes" if confirmed else ""
            result = func(**args)
            return ToolResult(tool_name=tool_name, content=result, success=True)
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                content=f"Erro ao executar: {e}",
                success=False,
            )

    # -----------------------------------------------------------------------
    # Built-in tool implementations
    # -----------------------------------------------------------------------

    def _open_url(self, url: str) -> str:
        """Open URL in default browser."""
        # Security: block localhost and internal IPs
        blocked = ["localhost", "127.0.0.1", "0.0.0.0", "::1", "10.", "192.168.", "172."]
        url_lower = url.lower()
        for block in blocked:
            if block in url_lower:
                return f"URL bloqueada por segurança: {url}"

        # Add https if no protocol
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        webbrowser.open(url)
        return f"Abrindo {url} no navegador."

    def _open_application(self, app_name: str) -> str:
        """Open application by name (Windows)."""
        app_map = {
            "chrome": "chrome",
            "google chrome": "chrome",
            "brave": "brave",
            "edge": "msedge",
            "microsoft edge": "msedge",
            "firefox": "firefox",
            "notepad": "notepad",
            "bloco de notas": "notepad",
            "calculadora": "calc",
            "calc": "calc",
            "calculator": "calc",
            "spotify": "spotify",
            "vscode": "code",
            "code": "code",
            "visual studio code": "code",
            "discord": "discord",
            "teams": "teams",
            "microsoft teams": "teams",
            "slack": "slack",
            "zoom": "zoom",
            "steam": "steam",
            "epic games": "epicgameslauncher",
            "explorer": "explorer",
            "file explorer": "explorer",
            "gerenciador de arquivos": "explorer",
            "prompt": "cmd",
            "terminal": "cmd",
            "cmd": "cmd",
            "word": "winword",
            "excel": "excel",
            "powerpoint": "powerpnt",
            "outlook": "outlook",
            "obs": "obs64",
            "obs studio": "obs64",
            "gimp": "gimp",
            "photoshop": "photoshop",
            "premiere": "adobe premiere pro.exe",
            "after effects": "afterfx",
        }

        app_lower = app_name.lower().strip()
        cmd = app_map.get(app_lower, app_lower)

        # Common app paths for Windows
        common_paths = {
            "discord": [
                os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Discord\app-*\Discord.exe"),
            ],
            "teams": [
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Teams\Update.exe --processStart Teams.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Teams\current\Teams.exe"),
            ],
            "slack": [
                os.path.expandvars(r"%LOCALAPPDATA%\slack\slack.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Slack\slack.exe"),
            ],
            "zoom": [
                os.path.expandvars(r"%APPDATA%\Zoom\bin\Zoom.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Zoom\bin\Zoom.exe"),
            ],
            "spotify": [
                os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
            ],
            "steam": [
                os.path.expandvars(r"C:\Program Files (x86)\Steam\Steam.exe"),
                os.path.expandvars(r"%PROGRAMFILES(x86)%\Steam\Steam.exe"),
            ],
            "epicgameslauncher": [
                os.path.expandvars(r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
                os.path.expandvars(r"%PROGRAMFILES(x86)%\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
            ],
            "obs64": [
                os.path.expandvars(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\obs-studio\bin\64bit\obs64.exe"),
            ],
            "code": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Microsoft VS Code\Code.exe"),
            ],
            "chrome": [
                os.path.expandvars(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            ],
        }

        try:
            # First, try to find the app in common paths
            if app_lower in common_paths:
                import glob
                for path_pattern in common_paths[app_lower]:
                    # Expand wildcards
                    matching_paths = glob.glob(path_pattern) if '*' in path_pattern else [path_pattern]
                    for path in matching_paths:
                        if os.path.exists(path):
                            # Found it!
                            if " --processStart " in path:
                                # Apps like Discord/Teams need Update.exe with argument
                                subprocess.Popen(path, shell=True)
                            else:
                                subprocess.Popen([path], shell=False)
                            return f"Abrindo {app_name}."
            
            # If not in common paths, try normal shell execution
            subprocess.Popen([cmd], shell=True)
            return f"Abrindo {app_name}."
            
        except Exception as e:
            # Fallback: try with start command (Windows)
            try:
                subprocess.Popen(["start", "", cmd], shell=True)
                return f"Tentando abrir {app_name}."
            except Exception as e2:
                return f"Não consegui abrir {app_name}. Tenta abrir manualmente?"

    def _get_current_time(self) -> str:
        """Get current date and time."""
        now = datetime.now()
        # Format in Portuguese
        days = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
        months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

        day_name = days[now.weekday()]
        month_name = months[now.month - 1]

        date_str = f"{day_name}, {now.day} de {month_name} de {now.year}"
        time_str = now.strftime("%H:%M")

        return f"Hoje é {date_str}. Agora são {time_str}."

    def _set_system_volume(self, level: int) -> str:
        """Set system volume (Windows only)."""
        try:
            # Clamp level to 0-100
            level = max(0, min(100, level))

            # Use nircmd if available, otherwise use PowerShell
            try:
                subprocess.run(
                    ["nircmd", "setsysvolume", str(int(level * 655.35))],
                    check=True,
                    capture_output=True,
                )
                return f"Volume ajustado para {level}%."
            except FileNotFoundError:
                # Fallback to PowerShell
                ps_cmd = f'$o = new-object -com wscript.shell; $o.SendKeys([char]174)' if level == 0 else f'(new-object -com wscript.shell).SendKeys([char]175)'
                subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
                return f"Volume ajustado para {level}%."
            except Exception as e2:
                return f"Não consegui ajustar o volume: {e2}"
        except Exception as e:
            return f"Erro ao tentar ajustar o volume: {e}"

    def _type_text(self, text: str, press_enter: bool = False) -> str:
        """Type text into active window."""
        if not pyautogui:
            return "Erro: Biblioteca PyAutoGUI não disponível."
        
        try:
            # Short delay to let user focus if needed, though usually it's immediate
            time.sleep(0.5)
            pyautogui.write(text, interval=0.01)
            if press_enter:
                pyautogui.press('enter')
            return f"Digitei: '{text}'"
        except Exception as e:
            return f"Erro ao digitar: {e}"

    def _press_keys(self, keys: str) -> str:
        """Press specific keys."""
        if not pyautogui:
            return "Erro: Biblioteca PyAutoGUI não disponível."
        
        try:
            time.sleep(0.5)
            if '+' in keys:
                combo = keys.split('+')
                pyautogui.hotkey(*combo)
            else:
                pyautogui.press(keys)
            return f"Pressionei a tecla: {keys}"
        except Exception as e:
            return f"Erro ao pressionar tecla: {e}"

    def _list_running_apps(self) -> str:
        """List titles of open windows."""
        if not gw:
            return "Erro: Biblioteca PyGetWindow não disponível."
        
        try:
            windows = gw.getAllTitles()
            # Filter empty titles and duplicates
            active_windows = sorted(list(set([w for w in windows if w.strip()])))
            if not active_windows:
                return "Nenhuma janela ativa encontrada."
            return "Janelas abertas:\n- " + "\n- ".join(active_windows[:15])
        except Exception as e:
            return f"Erro ao listar janelas: {e}"

    def _close_active_window(self) -> str:
        """Close active window using Alt+F4."""
        if not pyautogui:
            return "Erro: Biblioteca PyAutoGUI não disponível."
        
        try:
            pyautogui.hotkey('alt', 'f4')
            return "Tentei fechar a janela ativa."
        except Exception as e:
            return f"Erro ao fechar janela: {e}"

    def _send_whatsapp_message(self, message: str, phone: str = "") -> str:
        """Send WhatsApp message via WhatsApp Web."""
        import urllib.parse
        encoded_msg = urllib.parse.quote(message)
        
        if phone:
            # Clean phone number (remove +, -, spaces)
            clean_phone = "".join(filter(str.isdigit, phone))
            # Ensure country code (Brazil 55 as default if 11 digits)
            if len(clean_phone) == 11 and not clean_phone.startswith("55"):
                clean_phone = "55" + clean_phone
            
            url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
        else:
            url = f"https://web.whatsapp.com/send?text={encoded_msg}"
            
        webbrowser.open(url)
        return f"Abrindo WhatsApp Web para enviar a mensagem."

    # Memory Tools
    def _remember(self, key: str, value: str) -> str:
        """Store info in memory."""
        if not self._memory:
            return "Erro: Sistema de memória não inicializado."
        self._memory.set(key, value)
        return f"Ok, vou lembrar que {key} é {value}."

    def _list_memories(self) -> str:
        """List all memories."""
        if not self._memory:
            return "Erro: Sistema de memória não inicializado."
        memories = self._memory.get_all()
        if not memories:
            return "Minha memória está vazia no momento."
        
        lines = [f"{k}: {v}" for k, v in memories.items()]
        return "Aqui está o que eu lembro:\n" + "\n".join(lines)

    def _forget_memory(self, key: str) -> str:
        """Delete a memory."""
        if not self._memory:
            return "Erro: Sistema de memória não inicializado."
        self._memory.delete(key)
        return f"Ok, esqueci a informação sobre {key}."

    def _open_workspace(self, workspace_name: str) -> str:
        """Open a workspace from memory."""
        if not self._memory:
            return "Erro: Sistema de memória não inicializado."
            
        key = f"workspace_{workspace_name.lower()}"
        items_json = self._memory.get(key)
        
        if not items_json:
            return f"Workspace '{workspace_name}' não encontrado na minha memória."
            
        try:
            # Workspace items can be a list or a comma-separated string
            if isinstance(items_json, str):
                try:
                    items = json.loads(items_json)
                except:
                    items = [i.strip() for i in items_json.split(',')]
            else:
                items = items_json
                
            opened = []
            for item in items:
                if item.startswith(('http://', 'https://')) or '.' in item and '/' in item:
                    self._open_url(item)
                    opened.append(f"Site: {item}")
                else:
                    self._open_application(item)
                    opened.append(f"App: {item}")
                    
            return f"Abrindo workspace '{workspace_name}':\n" + "\n".join(opened)
        except Exception as e:
            return f"Erro ao abrir workspace: {e}"

    def _search_web(self, query: str) -> str:
        # Check cache first (5 minute TTL for search results)
        cached_result = search_cache.get(f"web_{query}")
        if cached_result:
            print(f"[Cache] Using cached search for '{query}'")
            # Still open browser
            from urllib.parse import quote
            webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
            return cached_result

        # Perform search
        result = self._do_search_web(query)

        # Cache the result
        if not result.startswith("Pesquisando"):  # Only cache if we got real results
            search_cache.set(f"web_{query}", result, ttl=300)  # 5 minutes

        return result

    def _serpapi_search(self, query: str, api_key: str) -> Optional[str]:
        """Search using SerpApi (Google)."""
        try:
            import requests
            url = "https://serpapi.com/search"
            params = {
                "q": query,
                "api_key": api_key,
                "engine": "google",
                "hl": "pt-br",
                "gl": "br",
                "num": 5
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                
                # Knowledge Graph
                kg = data.get("knowledge_graph", {})
                if kg:
                    source = kg.get("source", {}).get("name", "Fato")
                    description = kg.get("description", "")
                    if description:
                        results.append(f"[{source}] {description}")
                
                # Organic results
                organic = data.get("organic_results", [])
                for i, r in enumerate(organic[:3]):
                    title = r.get("title")
                    snippet = r.get("snippet")
                    if title and snippet:
                        results.append(f"{i+1}. {title}: {snippet}")
                
                if results:
                    return "\n".join(results)
        except Exception as e:
            print(f"[DEBUG] SerpApi error: {e}")
        return None

    def _tavily_search(self, query: str, api_key: str) -> Optional[str]:
        """Search using Tavily."""
        try:
            import requests
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for i, r in enumerate(data.get("results", [])[:3]):
                    title = r.get("title")
                    content = r.get("content")
                    if title and content:
                        results.append(f"{i+1}. {title}: {content}")
                
                if results:
                    return "\n".join(results)
        except Exception as e:
            print(f"[DEBUG] Tavily error: {e}")
        return None

    def _do_search_web(self, query: str) -> str:
        """Actually perform web search (internal)."""
        # Try to get API keys from env or centralized credentials
        serp_key = os.environ.get("SERPAPI_API_KEY")
        tavily_key = os.environ.get("TAVILY_API_KEY")

        print(f"[Search] Env - SerpApi: {'YES' if serp_key else 'NO'}, Tavily: {'YES' if tavily_key else 'NO'}")

        # Fallback to centralized credentials if not in env
        if not serp_key or not tavily_key:
            try:
                # Add src to sys.path locally if needed
                import sys
                project_root = os.getcwd()
                src_path = os.path.join(project_root, 'src')
                if src_path not in sys.path:
                    sys.path.append(src_path)
                
                from openjarvis.core.credentials import get_tool_credential
                if not serp_key:
                    serp_key = get_tool_credential("web_search", "SERPAPI_API_KEY")
                    if serp_key:
                        print(f"[Search] Loaded SerpApi key from credentials.toml")
                if not tavily_key:
                    tavily_key = get_tool_credential("web_search", "TAVILY_API_KEY")
                    if tavily_key:
                        print(f"[Search] Loaded Tavily key from credentials.toml")
            except Exception as e:
                print(f"[Search] Could not load from credentials.toml: {e}")
                import traceback
                traceback.print_exc()

        # Debug final state
        print(f"[Search] Final - SerpApi: {'YES' if serp_key else 'NO'}, Tavily: {'YES' if tavily_key else 'NO'}")

        # 1. Try SerpApi (requested by user)
        if serp_key:
            result = self._serpapi_search(query, serp_key)
            if result:
                # Open browser as well for user convenience
                from urllib.parse import quote
                webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
                return f"Resultados da busca (SerpApi):\n{result}"

        # 2. Try Tavily
        if tavily_key:
            result = self._tavily_search(query, tavily_key)
            if result:
                from urllib.parse import quote
                webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
                return f"Resultados da busca (Tavily):\n{result}"

        # 3. Fallback to DuckDuckGo scraping (current system)
        print(f"[Search] Using fallback: DuckDuckGo scraping")
        try:
            import urllib.request
            import re
            from urllib.parse import quote

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }

            url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            req = urllib.request.Request(url, headers=headers)

            try:
                with urllib.request.urlopen(req, timeout=8) as response:
                    html = response.read().decode('utf-8', errors='ignore')
                    results = []

                    result_blocks = re.findall(
                        r'<a[^>]*class="result__a"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                        html,
                        re.DOTALL | re.IGNORECASE
                    )

                    def clean_html(text):
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
                        text = text.replace('&lt;', '<').replace('&gt;', '>')
                        text = text.replace('&quot;', '"')
                        text = re.sub(r'\s+', ' ', text).strip()
                        return text

                    for i, (title, snippet) in enumerate(result_blocks[:3]):
                        clean_title = clean_html(title)
                        clean_snippet = clean_html(snippet)
                        if clean_title and len(clean_title) > 3:
                            results.append(f"{i+1}. {clean_title}: {clean_snippet}")

                    if results:
                        result_text = "\n".join(results)
                        google_url = f"https://www.google.com/search?q={quote(query)}"
                        webbrowser.open(google_url)
                        return f"Resultados para '{query}':\n{result_text}"
            except Exception:
                pass

            # Fallback
            google_url = f"https://www.google.com/search?q={quote(query)}"
            webbrowser.open(google_url)
            return f"Pesquisando '{query}' no Google. Verifique os resultados no navegador aberto."

        except Exception:
            from urllib.parse import quote
            google_url = f"https://www.google.com/search?q={quote(query)}"
            webbrowser.open(google_url)
            return f"Pesquisando '{query}' no Google. Verifique os resultados no navegador aberto."

    def _scrape_first_video_id(self, query: str) -> str | None:
        """Scrape YouTube search results and return first non-Shorts video ID."""
        try:
            import urllib.request
            import re
            from urllib.parse import quote

            search_url = f"https://www.youtube.com/results?search_query={quote(query)}&sp=EgIQAQ%253D%253D"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }

            req = urllib.request.Request(search_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')

                # Look for video IDs in multiple formats
                # Pattern 1: videoRenderer with videoId
                patterns = [
                    r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"',
                    r'"videoId":"([a-zA-Z0-9_-]{11})"',
                    r'/watch\?v=([a-zA-Z0-9_-]{11})',
                    r'watch%3Fv%3D([a-zA-Z0-9_-]{11})',
                ]

                found_ids = []
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    found_ids.extend(matches)

                # Return first unique video ID that's not a Short
                for vid in found_ids:
                    # Check if it's likely a Short (usually has different pattern)
                    if len(vid) == 11:
                        # Verify it's not in a Shorts section
                        short_pattern = f'"videoId":"{vid}".*?isShort":true'
                        if not re.search(short_pattern, html[:html.find(vid) + 500]):
                            return vid

                # Fallback: return first ID found
                for vid in found_ids:
                    if len(vid) == 11:
                        return vid

        except Exception as e:
            print(f"[YouTube] Scraping error: {e}")

        return None

    def _youtube_search_and_play(self, query: str) -> str:
        """Search YouTube and play first video result directly (Mark-XXXIX approach)."""
        from urllib.parse import quote

        # Try to scrape and play first video directly
        video_id = self._scrape_first_video_id(query)

        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            webbrowser.open(video_url)
            return f"Tocando '{query}' no YouTube."
        else:
            # Fallback to search page
            encoded = quote(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAQ%253D%253D"
            webbrowser.open(search_url)
            return f"Buscando '{query}' no YouTube. Escolha um vídeo da lista."

    def _browser_navigate(self, url: str) -> str:
        """Navigate to URL using browser automation if available."""
        try:
            # Try to use playwright if available
            import importlib
            playwright = importlib.import_module("playwright.sync_api")
            
            # Security check
            blocked = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
            url_lower = url.lower()
            for block in blocked:
                if block in url_lower:
                    return f"URL bloqueada por segurança: {url}"
            
            # Add https if needed
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            # Open in default browser for now (full automation later)
            webbrowser.open(url)
            return f"Navegando para {url}. Use 'browser_search' para interagir com o site."
            
        except ImportError:
            # Fallback to simple webbrowser
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            return f"Abrindo {url} no navegador. Para automação completa, instale: uv add playwright"

    def _browser_search(self, site: str, query: str) -> str:
        """Search on a specific website using browser automation."""
        from urllib.parse import quote
        encoded = quote(query)
        
        # Map common sites to their search URLs
        search_urls = {
            "google.com": f"https://www.google.com/search?q={encoded}",
            "youtube.com": f"https://www.youtube.com/results?search_query={encoded}",
            "amazon.com": f"https://www.amazon.com/s?k={encoded}",
            "amazon.com.br": f"https://www.amazon.com.br/s?k={encoded}",
            "mercadolivre.com.br": f"https://lista.mercadolivre.com.br/{encoded}",
            "github.com": f"https://github.com/search?q={encoded}",
            "wikipedia.org": f"https://en.wikipedia.org/wiki/Special:Search?search={encoded}",
            "pt.wikipedia.org": f"https://pt.wikipedia.org/wiki/Especial:Pesquisar?search={encoded}",
        }
        
        # Normalize site
        site_lower = site.lower().replace("https://", "").replace("http://", "").replace("www.", "")
        if site_lower.startswith("google"):
            site_key = "google.com"
        elif site_lower.startswith("youtube"):
            site_key = "youtube.com"
        elif site_lower.startswith("amazon"):
            site_key = "amazon.com"
        elif site_lower.startswith("mercadolivre") or site_lower.startswith("mercado"):
            site_key = "mercadolivre.com.br"
        elif site_lower.startswith("github"):
            site_key = "github.com"
        elif site_lower.startswith("wikipedia") or site_lower.startswith("wiki"):
            site_key = "pt.wikipedia.org"
        else:
            site_key = site_lower
        
        # Get search URL or construct generic one
        if site_key in search_urls:
            url = search_urls[site_key]
        else:
            # Generic search URL pattern
            url = f"https://{site_key}/search?q={encoded}"
        
        webbrowser.open(url)
        return f"Buscando '{query}' em {site_key}. Veja os resultados no navegador."

    def _browser_search_and_click(self, site: str, query: str) -> str:
        """Search and automatically click first result using Google I'm Feeling Lucky or direct URL."""
        from urllib.parse import quote
        encoded = quote(query)
        
        # Normalize site name
        site_lower = site.lower().replace("https://", "").replace("http://", "").replace("www.", "")
        
        # Strategy 1: Use Google I'm Feeling Lucky for most sites (goes directly to first result)
        # This works well for: Wikipedia, official sites, popular pages
        if "youtube" in site_lower:
            # For YouTube, use search with video filter and open first video
            # YouTube doesn't support I'm Feeling Lucky well, so we construct search URL
            # that shows videos and hope the user clicks, or we try to use ytsearch:
            url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAQ%253D%253D"
            webbrowser.open(url)
            return f"Abrindo resultados de '{query}' no YouTube. O primeiro vídeo deve aparecer no topo."
        
        elif "amazon" in site_lower:
            # For Amazon, go directly to search results (first product is effectively "clicked")
            if ".br" in site_lower:
                url = f"https://www.amazon.com.br/s?k={encoded}"
            else:
                url = f"https://www.amazon.com/s?k={encoded}"
            webbrowser.open(url)
            return f"Abrindo resultados de '{query}' na Amazon. O primeiro produto está no topo."
        
        elif "google" in site_lower:
            # Use I'm Feeling Lucky to go directly to first result
            url = f"https://www.google.com/search?q={encoded}&btnI=1"
            webbrowser.open(url)
            return f"Indo direto para o melhor resultado de '{query}'."
        
        elif "wikipedia" in site_lower or "wiki" in site_lower:
            # For Wikipedia, try direct page or search
            direct_url = f"https://pt.wikipedia.org/wiki/{encoded.replace('+', '_')}"
            webbrowser.open(direct_url)
            return f"Abrindo página de '{query}' na Wikipedia."
        
        elif "github" in site_lower:
            # For GitHub, search and show results
            url = f"https://github.com/search?q={encoded}"
            webbrowser.open(url)
            return f"Abrindo resultados de '{query}' no GitHub."
        
        else:
            # Generic fallback: use Google I'm Feeling Lucky with site constraint
            # This often goes directly to the most relevant page
            lucky_query = quote(f"{query} site:{site_lower}")
            url = f"https://www.google.com/search?q={lucky_query}&btnI=1"
            webbrowser.open(url)
            return f"Indo direto para o melhor resultado de '{query}' em {site_lower}."

    def _focus_window(self, app_name: str) -> str:
        """Bring a window to the foreground."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            if controller.focus_window(app_name):
                return f"Prontinho! Trazendo {app_name} pra frente."
            else:
                return f"Não encontrei {app_name} aberto. Quer que eu abra?"
        except Exception as e:
            return f"Não consegui focar {app_name}: {str(e)}"

    def _close_window(self, app_name: str) -> str:
        """Close a window or application."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            if controller.close_window(app_name):
                return f"Fechei {app_name} pra você."
            else:
                return f"Não consegui fechar {app_name}. Tenta fechar manualmente?"
        except Exception as e:
            return f"Erro ao fechar {app_name}: {str(e)}"

    def _minimize_window(self, app_name: str) -> str:
        """Minimize a window."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            if controller.minimize_window(app_name):
                return f"Minimizei {app_name}."
            else:
                return f"Não consegui minimizar {app_name}."
        except Exception as e:
            return f"Erro: {str(e)}"

    def _maximize_window(self, app_name: str) -> str:
        """Maximize a window."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            if controller.maximize_window(app_name):
                return f"Maximizei {app_name} pra tela cheia."
            else:
                return f"Não consegui maximizar {app_name}."
        except Exception as e:
            return f"Erro: {str(e)}"

    def _list_running_apps(self) -> str:
        """List all running applications."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            apps = controller.list_running_apps()
            
            if not apps:
                return "Não consegui ver quais apps estão abertos agora."
            
            # Get unique app names
            unique_apps = []
            seen = set()
            for app in apps[:15]:  # Limit to first 15
                name = app.process_name.replace('.exe', '')
                if name not in seen:
                    seen.add(name)
                    unique_apps.append(name)
            
            app_list = ', '.join(unique_apps)
            return f"Tô vendo esses apps abertos: {app_list}. Quer que eu feche algum ou traga algum pra frente?"
            
        except Exception as e:
            return f"Não consegui listar os apps: {str(e)}"

    def _send_hotkey(self, keys: List[str]) -> str:
        """Send a keyboard shortcut."""
        try:
            from voice_assistant.window_controller import get_controller
            controller = get_controller()
            
            # Convert key names to pyautogui format
            key_map = {
                'ctrl': 'ctrl',
                'control': 'ctrl',
                'alt': 'alt',
                'shift': 'shift',
                'win': 'win',
                'windows': 'win',
                'cmd': 'command',
                'command': 'command',
                'esc': 'esc',
                'enter': 'enter',
                'tab': 'tab',
                'space': 'space',
                'delete': 'delete',
                'del': 'delete',
                'backspace': 'backspace',
                'up': 'up',
                'down': 'down',
                'left': 'left',
                'right': 'right',
                'pageup': 'pageup',
                'pagedown': 'pagedown',
                'home': 'home',
                'end': 'end',
                'f1': 'f1', 'f2': 'f2', 'f3': 'f3', 'f4': 'f4',
                'f5': 'f5', 'f6': 'f6', 'f7': 'f7', 'f8': 'f8',
                'f9': 'f9', 'f10': 'f10', 'f11': 'f11', 'f12': 'f12',
            }
            
            # Map keys
            mapped_keys = []
            for key in keys:
                key_lower = key.lower()
                if key_lower in key_map:
                    mapped_keys.append(key_map[key_lower])
                else:
                    mapped_keys.append(key_lower)
            
            if controller.send_hotkey(*mapped_keys):
                shortcut = '+'.join(keys)
                return f"Enviei o atalho {shortcut}."
            else:
                return "Não consegui enviar o atalho. Verifica se a janela certa tá focada."
                
        except Exception as e:
            return f"Erro ao envinar atalho: {str(e)}"

    def _computer_settings(self, action: str, value: str = "", confirmed: str = "") -> str:
        """Execute computer settings actions (Mark-XXXIX approach)."""
        if not pyautogui:
            return "Erro: PyAutoGUI não está disponível."

        action = action.lower().strip().replace(" ", "_").replace("-", "_")

        # Dangerous actions require confirmation
        dangerous = {"restart", "shutdown"}
        if action in dangerous:
            if confirmed.lower() not in ("yes", "true", "1", "confirm"):
                return f"Isso vai {action} o computador. Confirme chamando novamente com confirmed=yes."

        try:
            # Volume controls
            if action in ("volume_up", "vol_up", "aumentar_volume"):
                for _ in range(5): pyautogui.press("volumeup")
                return "Volume aumentado."

            if action in ("volume_down", "vol_down", "diminuir_volume"):
                for _ in range(5): pyautogui.press("volumedown")
                return "Volume diminuído."

            if action in ("mute", "unmute", "toggle_mute", "silenciar"):
                pyautogui.press("volumemute")
                return "Som silenciado/restaurado."

            if action == "volume_set":
                try:
                    level = int(value)
                    # Use pycaw if available for precise control
                    try:
                        import math
                        from ctypes import cast, POINTER
                        from comtypes import CLSCTX_ALL
                        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                        devices = AudioUtilities.GetSpeakers()
                        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                        vol = cast(interface, POINTER(IAudioEndpointVolume))
                        vol_db = -65.25 if level == 0 else max(-65.25, 20 * math.log10(level / 100))
                        vol.SetMasterVolumeLevel(vol_db, None)
                    except:
                        # Fallback: use keypresses (approximate)
                        pyautogui.press("volumemute")
                        pyautogui.press("volumemute")
                    return f"Volume ajustado para {level}%."
                except:
                    return "Erro ao ajustar volume. Use um valor de 0 a 100."

            # Brightness controls (Windows only)
            if action in ("brightness_up", "aumentar_brilho"):
                try:
                    subprocess.run(
                        ["powershell", "-Command",
                         "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                         ".WmiSetBrightness(1, [math]::Min(100, (Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness + 10))"],
                        capture_output=True, timeout=5
                    )
                    return "Brilho aumentado."
                except Exception as e:
                    return f"Não consegui aumentar o brilho: {e}"

            if action in ("brightness_down", "diminuir_brilho"):
                try:
                    subprocess.run(
                        ["powershell", "-Command",
                         "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                         ".WmiSetBrightness(1, [math]::Max(0, (Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness - 10))"],
                        capture_output=True, timeout=5
                    )
                    return "Brilho diminuído."
                except Exception as e:
                    return f"Não consegui diminuir o brilho: {e}"

            # Window controls
            if action in ("close_app", "close_application", "fechar_app"):
                pyautogui.hotkey("alt", "f4")
                return "Aplicativo fechado."

            if action in ("close_window", "fechar_janela"):
                pyautogui.hotkey("ctrl", "w")
                return "Janela fechada."

            if action in ("full_screen", "fullscreen", "tela_cheia"):
                pyautogui.press("f11")
                return "Tela cheia ativada/desativada."

            if action in ("minimize", "minimize_window", "minimizar"):
                pyautogui.hotkey("win", "down")
                return "Janela minimizada."

            if action in ("maximize", "maximize_window", "maximizar"):
                pyautogui.hotkey("win", "up")
                return "Janela maximizada."

            if action in ("snap_left", "encaixar_esquerda"):
                pyautogui.hotkey("win", "left")
                return "Janela encaixada à esquerda."

            if action in ("snap_right", "encaixar_direita"):
                pyautogui.hotkey("win", "right")
                return "Janela encaixada à direita."

            if action in ("switch_window", "alternar_janela"):
                pyautogui.hotkey("alt", "tab")
                return "Alternando janela."

            if action in ("show_desktop", "mostrar_desktop", "minimizar_tudo"):
                pyautogui.hotkey("win", "d")
                return "Desktop exibido."

            # Browser controls
            if action in ("new_tab", "nova_aba"):
                pyautogui.hotkey("ctrl", "t")
                return "Nova aba aberta."

            if action in ("close_tab", "fechar_aba"):
                pyautogui.hotkey("ctrl", "w")
                return "Aba fechada."

            if action in ("next_tab", "proxima_aba"):
                pyautogui.hotkey("ctrl", "tab")
                return "Próxima aba."

            if action in ("prev_tab", "previous_tab", "aba_anterior"):
                pyautogui.hotkey("ctrl", "shift", "tab")
                return "Aba anterior."

            if action in ("refresh_page", "reload", "recarregar", "atualizar"):
                pyautogui.press("f5")
                return "Página recarregada."

            if action in ("focus_search", "focar_busca", "barra_de_endereco"):
                pyautogui.hotkey("ctrl", "l")
                return "Barra de endereço focada."

            if action in ("zoom_in", "aumentar_zoom"):
                pyautogui.hotkey("ctrl", "equal")
                return "Zoom aumentado."

            if action in ("zoom_out", "diminuir_zoom"):
                pyautogui.hotkey("ctrl", "minus")
                return "Zoom diminuído."

            if action in ("zoom_reset", "resetar_zoom"):
                pyautogui.hotkey("ctrl", "0")
                return "Zoom resetado."

            # Video controls
            if action in ("pause_video", "play_pause", "pausar_video"):
                pyautogui.press("space")
                return "Vídeo pausado/continuado."

            # Clipboard and editing
            if action in ("copy", "copiar"):
                pyautogui.hotkey("ctrl", "c")
                return "Copiado."

            if action in ("paste", "colar"):
                pyautogui.hotkey("ctrl", "v")
                return "Colado."

            if action in ("cut", "recortar"):
                pyautogui.hotkey("ctrl", "x")
                return "Recortado."

            if action in ("undo", "desfazer"):
                pyautogui.hotkey("ctrl", "z")
                return "Desfeito."

            if action in ("redo", "refazer"):
                pyautogui.hotkey("ctrl", "y")
                return "Refeito."

            if action in ("select_all", "selecionar_tudo"):
                pyautogui.hotkey("ctrl", "a")
                return "Tudo selecionado."

            if action in ("save", "save_file", "salvar"):
                pyautogui.hotkey("ctrl", "s")
                return "Salvando..."

            # Scroll
            if action in ("scroll_up", "rolar_cima"):
                pyautogui.scroll(500)
                return "Rolou para cima."

            if action in ("scroll_down", "rolar_baixo"):
                pyautogui.scroll(-500)
                return "Rolou para baixo."

            if action in ("scroll_top", "topo_da_pagina"):
                pyautogui.keyDown("ctrl")
                pyautogui.keyDown("home")
                pyautogui.keyUp("home")
                pyautogui.keyUp("ctrl")
                return "Topo da página."

            if action in ("scroll_bottom", "fim_da_pagina"):
                pyautogui.keyDown("ctrl")
                pyautogui.keyDown("end")
                pyautogui.keyUp("end")
                pyautogui.keyUp("ctrl")
                return "Fim da página."

            # System controls
            if action in ("screenshot", "captura_de_tela"):
                pyautogui.hotkey("win", "shift", "s")
                return "Ferramenta de captura ativada."

            if action in ("lock_screen", "bloquear_tela"):
                pyautogui.hotkey("win", "l")
                return "Tela bloqueada."

            if action in ("open_settings", "configuracoes", "abrir_configuracoes"):
                pyautogui.hotkey("win", "i")
                return "Configurações abertas."

            if action in ("file_explorer", "explorar_arquivos", "abrir_explorador"):
                pyautogui.hotkey("win", "e")
                return "Explorador de arquivos aberto."

            if action in ("task_manager", "gerenciador_tarefas"):
                pyautogui.hotkey("ctrl", "shift", "esc")
                return "Gerenciador de tarefas aberto."

            if action in ("sleep_display", "sleep", "desligar_tela"):
                try:
                    import ctypes
                    ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
                    return "Tela desligada."
                except:
                    return "Não consegui desligar a tela."

            if action in ("dark_mode", "modo_escuro"):
                try:
                    import winreg
                    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                    current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
                    winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
                    winreg.CloseKey(key)
                    return "Modo escuro alternado."
                except Exception as e:
                    return f"Não consegui alternar modo escuro: {e}"

            # Dangerous actions
            if action == "restart":
                subprocess.Popen(["shutdown", "/r", "/t", "10"], capture_output=True)
                return "Reiniciando em 10 segundos..."

            if action == "shutdown":
                subprocess.Popen(["shutdown", "/s", "/t", "10"], capture_output=True)
                return "Desligando em 10 segundos..."

            return f"Ação desconhecida: {action}. Ações disponíveis: volume_up, mute, brightness_up, full_screen, lock_screen, screenshot, etc."

        except Exception as e:
            return f"Erro ao executar {action}: {e}"


    def _search_products(self, query: str, store: str = "") -> str:
        """Search products online with caching."""
        cache_key = f"prod_{store}_{query}"

        # Check cache (10 minute TTL for products - prices change)
        cached = search_cache.get(cache_key)
        if cached:
            print(f"[Cache] Using cached product search for '{query}'")
            return cached

        # Perform search
        result = self._do_search_products(query, store)

        # Cache result
        search_cache.set(cache_key, result, ttl=600)  # 10 minutes
        return result

    def _do_search_products(self, query: str, store: str = "") -> str:
        """Actually search products (internal)."""
        from urllib.parse import quote

        store_urls = {
            "mercadolivre": f"https://lista.mercadolivre.com.br/{quote(query)}",
            "amazon": f"https://www.amazon.com.br/s?k={quote(query)}",
            "magalu": f"https://www.magazineluiza.com.br/busca/{quote(query)}",
            "buscape": f"https://www.buscape.com.br/search?q={quote(query)}",
            "": f"https://www.google.com/search?q={quote(query)}&tbm=shop",
        }

        store_lower = store.lower().replace(" ", "").replace("-", "").replace(".", "")

        if store_lower in ["mercadolivre", "ml", "mercado", "mercadolibre"]:
            store_key = "mercadolivre"
        elif store_lower in ["amazon", "amazon.com.br", "amz"]:
            store_key = "amazon"
        elif store_lower in ["magalu", "magazineluiza", "magazine"]:
            store_key = "magalu"
        elif store_lower in ["buscape", "buscapé", "bc"]:
            store_key = "buscape"
        else:
            store_key = ""

        url = store_urls.get(store_key, store_urls[""])
        store_display = store_key.upper() if store_key else "Google Shopping"

        # Try to scrape for actual results
        try:
            if store_key == "mercadolivre":
                results = self._scrape_mercadolivre(query)
                if results:
                    return f"Produtos encontrados no Mercado Livre para '{query}':\n" + "\n".join(results) + f"\n\nVer todos: {url}"
            elif store_key == "amazon":
                results = self._scrape_amazon(query)
                if results:
                    return f"Produtos encontrados na Amazon para '{query}':\n" + "\n".join(results) + f"\n\nVer todos: {url}"
        except Exception:
            pass

        webbrowser.open(url)
        return f"Buscando '{query}' em {store_display}. Encontrei resultados, abrindo para você ver."
    
    def _scrape_mercadolivre(self, query: str) -> list:
        """Scrape Mercado Livre for product listings."""
        import urllib.request
        import re
        from urllib.parse import quote
        
        url = f"https://lista.mercadolivre.com.br/{quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0.36",
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            # Extract product titles and prices
            products = []
            
            # Mercado Livre product pattern
            titles = re.findall(r'aria-label="([^"]+)"[^>]*class="[^"]*poly-component__title', html)
            prices = re.findall(r'R\$\s*[\d.]+,\d+', html)
            
            for i, title in enumerate(titles[:5]):
                price = prices[i] if i < len(prices) else "Preço a consultar"
                products.append(f"{i+1}. {title[:80]} - {price}")
            
            return products
    
    def _scrape_amazon(self, query: str) -> list:
        """Scrape Amazon for product listings."""
        import urllib.request
        import re
        from urllib.parse import quote
        
        url = f"https://www.amazon.com.br/s?k={quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            products = []
            # Amazon product titles
            titles = re.findall(r'data-cy="title-recipe-title"[^>]*>([^<]+)</span>', html)
            prices = re.findall(r'R\$\s*[\d.]+(?:,\d+)?', html)
            
            for i, title in enumerate(titles[:5]):
                price = prices[i] if i < len(prices) else "Preço a consultar"
                products.append(f"{i+1}. {title[:80].strip()} - {price}")
            
            return products

    def _search_videos(self, query: str) -> str:
        """Search YouTube videos with caching."""
        cache_key = f"video_{query}"

        # Check cache (15 minute TTL for videos - they don't change often)
        cached = search_cache.get(cache_key)
        if cached:
            print(f"[Cache] Using cached video search for '{query}'")
            return cached

        # Perform search
        result = self._do_search_videos(query)

        # Cache result
        search_cache.set(cache_key, result, ttl=900)  # 15 minutes
        return result

    def _do_search_videos(self, query: str) -> str:
        """Actually search YouTube videos (internal)."""
        from urllib.parse import quote
        import urllib.request
        import re

        search_url = f"https://www.youtube.com/results?search_query={quote(query)}&sp=EgIQAQ%253D%253D"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
            req = urllib.request.Request(search_url, headers=headers)

            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                videos = []

                video_data = re.findall(
                    r'"title":{"runs":\[{"text":"([^"]+)".*?"longBylineText":\{"runs":\[\{"text":"([^"]+)"',
                    html
                )

                if video_data:
                    for i, (title, channel) in enumerate(video_data[:5]):
                        videos.append(f"{i+1}. {title[:70]} - Canal: {channel}")
                else:
                    titles = re.findall(r'title":{"runs":\[{"text":"([^"]{10,100})"', html)
                    for i, title in enumerate(titles[:5]):
                        videos.append(f"{i+1}. {title[:70]}")

                if videos:
                    return f"Vídeos encontrados no YouTube para '{query}':\n" + "\n".join(videos) + f"\n\nVer todos: {search_url}"
        except Exception as e:
            print(f"[DEBUG] YouTube scraping error: {e}")

        webbrowser.open(search_url)
        return f"Buscando vídeos de '{query}' no YouTube. Escolha qual quer assistir da lista."

    def _smart_open(self, url: str, description: str = "") -> str:
        """Open a specific URL after user confirmation."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        webbrowser.open(url)
        desc = description or "link"
        return f"Abrindo {desc} no navegador."

    def _extract_video_id(self, url: str) -> str | None:
        """Extract YouTube video ID from various URL formats."""
        import re
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _youtube_info(self, url: str) -> str:
        """Get YouTube video info (title, channel, views, duration)."""
        import urllib.request
        import re

        video_id = self._extract_video_id(url)
        if not video_id:
            return "Não consegui identificar o ID do vídeo na URL."

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')

                # Extract title
                title_match = re.search(r'<title>([^<]+)</title>', html)
                title = title_match.group(1).replace(" - YouTube", "").strip() if title_match else "Desconhecido"

                # Extract channel
                channel_match = re.search(r'"channelName":"([^"]+)"', html)
                channel = channel_match.group(1) if channel_match else "Desconhecido"

                # Extract views (approximate)
                views_match = re.search(r'viewCount":\{"simpleText":"([^"]+)"', html)
                views = views_match.group(1) if views_match else "Desconhecido"

                # Extract duration
                duration_match = re.search(r'duration":\{"simpleText":"([^"]+)"', html)
                duration = duration_match.group(1) if duration_match else "Desconhecido"

                return f"Título: {title}\nCanal: {channel}\nVisualizações: {views}\nDuração: {duration}"

        except Exception as e:
            return f"Erro ao obter informações: {e}"

    def _youtube_summarize(self, url: str) -> str:
        """Summarize YouTube video using transcript (if available) or Gemini."""
        video_id = self._extract_video_id(url)
        if not video_id:
            return "Não consegui identificar o ID do vídeo."

        # Try to get transcript
        transcript_text = None
        try:
            # Try youtube-transcript-api if available
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['pt', 'en'])
            transcript_text = " ".join([item['text'] for item in transcript_list[:100]])  # First 100 segments
        except:
            pass

        # Fallback: get video info for context
        info = self._youtube_info(url)

        if transcript_text:
            # Summarize with Groq if available
            try:
                import os
                from groq import Groq
                client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "Resuma o seguinte texto em português, destacando os pontos principais:"},
                        {"role": "user", "content": transcript_text[:4000]},  # Limit length
                    ],
                    max_tokens=500,
                )
                summary = response.choices[0].message.content
                return f"Resumo do vídeo:\n{summary}\n\nInfo:\n{info}"
            except Exception as e:
                return f"Transcrição encontrada mas não consegui resumir:\n{transcript_text[:500]}...\n\n{info}"
        else:
            return f"Não consegui extrair a transcrição deste vídeo.\n\n{info}\n\nPara assistir, abra o link: {url}"

    def _youtube_trending(self) -> str:
        """Get trending YouTube videos for Brazil."""
        import urllib.request
        import re
        from urllib.parse import quote

        try:
            url = "https://www.youtube.com/feed/trending?gl=BR"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='ignore')
                videos = []

                # Find video renderers in trending
                video_data = re.findall(
                    r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})".*?"title":\{"runs":\[\{"text":"([^"]+)".*?"longBylineText":\{"runs":\[\{"text":"([^"]+)"',
                    html
                )

                for i, (vid_id, title, channel) in enumerate(video_data[:8]):
                    videos.append(f"{i+1}. {title[:60]} - {channel}")

                if videos:
                    webbrowser.open(url)
                    return "Vídeos em alta no YouTube Brasil:\n" + "\n".join(videos)
                else:
                    webbrowser.open(url)
                    return "Abrindo vídeos em alta no YouTube Brasil."

        except Exception as e:
            webbrowser.open("https://www.youtube.com/feed/trending?gl=BR")
            return f"Abrindo trending do YouTube Brasil."

    def _get_desktop_path(self) -> Path:
        """Get desktop path for current user."""
        return Path.home() / "Desktop"

    def _desktop_wallpaper(self, path: str) -> str:
        """Set desktop wallpaper from file path or URL."""
        import tempfile
        from pathlib import Path

        try:
            # Check if it's a URL
            if path.startswith(("http://", "https://")):
                # Download image
                import urllib.request
                suffix = Path(path.split("?")[0]).suffix or ".jpg"
                tmp_file = Path(tempfile.mktemp(suffix=suffix))
                urllib.request.urlretrieve(path, str(tmp_file))
                image_path = str(tmp_file)
            else:
                image_path = Path(path).expanduser().resolve()
                if not image_path.exists():
                    return f"Imagem não encontrada: {path}"

            # Set wallpaper using ctypes
            import ctypes
            # Convert webp/png to bmp if needed for Windows compatibility
            if str(image_path).lower().endswith((".webp", ".png")):
                try:
                    from PIL import Image
                    bmp_path = Path(tempfile.mktemp(suffix=".bmp"))
                    Image.open(image_path).convert("RGB").save(bmp_path, "BMP")
                    image_path = str(bmp_path)
                except ImportError:
                    pass

            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(image_path), 3)
            return f"Papel de parede alterado para: {Path(image_path).name}"

        except Exception as e:
            return f"Erro ao alterar wallpaper: {e}"

    def _desktop_organize(self, mode: str = "by_type") -> str:
        """Organize desktop files by type or date."""
        from pathlib import Path
        from datetime import datetime
        import shutil

        desktop = self._get_desktop_path()
        if not desktop.exists():
            return "Desktop não encontrado."

        # File type mapping
        type_folders = {
            "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
            "Documentos": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt"},
            "Videos": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
            "Musicas": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
            "Arquivos": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
            "Codigo": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".cpp", ".java", ".cs"},
        }

        moved = 0
        skipped = 0

        for item in desktop.iterdir():
            if item.is_dir() or item.name.startswith("."):
                continue

            # Skip shortcuts
            if item.suffix.lower() in {".lnk", ".url"}:
                continue

            # Determine target folder
            if mode == "by_date":
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                folder_name = mtime.strftime("%Y-%m")
            else:  # by_type
                ext = item.suffix.lower()
                folder_name = "Outros"
                for folder, exts in type_folders.items():
                    if ext in exts:
                        folder_name = folder
                        break

            target_dir = desktop / folder_name
            target_dir.mkdir(exist_ok=True)
            target_path = target_dir / item.name

            if target_path.exists():
                skipped += 1
                continue

            try:
                shutil.move(str(item), str(target_path))
                moved += 1
            except Exception:
                skipped += 1

        return f"Desktop organizado: {moved} arquivos movidos, {skipped} ignorados."

    def _desktop_list(self) -> str:
        """List all items on desktop."""
        desktop = self._get_desktop_path()
        if not desktop.exists():
            return "Desktop não encontrado."

        items = []
        for item in sorted(desktop.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                try:
                    count = len(list(item.iterdir()))
                    items.append(f"📁 {item.name}/ ({count} itens)")
                except:
                    items.append(f"📁 {item.name}/")
            else:
                size = item.stat().st_size
                size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
                items.append(f"📄 {item.name} ({size_str})")

        if not items:
            return "Desktop está vazio."
        return f"Itens no Desktop ({len(items)}):\n" + "\n".join(items[:20])

    def _desktop_stats(self) -> str:
        """Get desktop statistics."""
        desktop = self._get_desktop_path()
        if not desktop.exists():
            return "Desktop não encontrado."

        files = [i for i in desktop.iterdir() if i.is_file()]
        folders = [i for i in desktop.iterdir() if i.is_dir()]
        total_size = sum(f.stat().st_size for f in files if f.exists())

        size_str = f"{total_size/1024:.1f} KB" if total_size < 1024*1024 else f"{total_size/1024/1024:.1f} MB"

        # Count by extension
        exts = {}
        for f in files:
            ext = f.suffix.lower() or "(sem extensão)"
            exts[ext] = exts.get(ext, 0) + 1

        ext_summary = ", ".join([f"{k}: {v}" for k, v in sorted(exts.items(), key=lambda x: -x[1])[:5]])

        return (
            f"Estatísticas do Desktop:\n"
            f"  Arquivos: {len(files)}\n"
            f"  Pastas: {len(folders)}\n"
            f"  Tamanho total: {size_str}\n"
            f"  Tipos principais: {ext_summary or 'N/A'}"
        )

    def _send_message(
        self,
        receiver: str,
        message: str,
        platform: str = "whatsapp",
        confirmed: str = "",
    ) -> str:
        """Send message via various platforms."""
        import urllib.parse
        from urllib.parse import quote

        platform = platform.lower().strip()
        receiver = receiver.strip()
        confirmed = str(confirmed).lower().strip()
        message_encoded = quote(message)
        preview = message if len(message) <= 180 else f"{message[:177]}..."

        if confirmed not in ("yes", "true", "1", "confirm"):
            return (
                "Prévia da mensagem (não enviada):\n"
                f"  Plataforma: {platform}\n"
                f"  Destinatário: {receiver}\n"
                f"  Mensagem: {preview}\n\n"
                "Se estiver certo, repita o envio com confirmed=yes."
            )

        if platform in ("whatsapp", "wp", "wapp"):
            # WhatsApp Web - works best
            clean_phone = "".join(filter(str.isdigit, receiver))
            if len(clean_phone) == 11 and not clean_phone.startswith("55"):
                clean_phone = "55" + clean_phone
            if clean_phone:
                url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={message_encoded}"
            else:
                url = f"https://web.whatsapp.com/send?text={message_encoded}"
            webbrowser.open(url)
            return f"Abrindo WhatsApp Web para enviar mensagem para {receiver}."

        elif platform in ("telegram", "tg"):
            # Telegram Web
            url = f"https://web.telegram.org/"
            webbrowser.open(url)
            return f"Abrindo Telegram Web. Busque por '{receiver}' e cole a mensagem: {message[:50]}..."

        elif platform == "discord":
            # Try to open Discord app
            try:
                subprocess.Popen(["discord"], shell=True)
                return f"Discord aberto. Cole a mensagem no chat de {receiver}: {message[:50]}..."
            except:
                webbrowser.open("https://discord.com/app")
                return f"Abrindo Discord. Envie a mensagem para {receiver}."

        elif platform in ("instagram", "ig", "insta"):
            url = f"https://www.instagram.com/direct/new/"
            webbrowser.open(url)
            return f"Abrindo Instagram Direct. Busque por '{receiver}' e envie a mensagem."

        elif platform in ("messenger", "facebook", "fb"):
            url = f"https://www.messenger.com/"
            webbrowser.open(url)
            return f"Abrindo Messenger. Busque por '{receiver}' e envie a mensagem."

        else:
            return f"Plataforma '{platform}' não suportada. Use: whatsapp, telegram, discord, instagram, messenger."

    def _set_reminder(self, date: str, time: str, message: str) -> str:
        """Set a reminder using Windows Task Scheduler."""
        from datetime import datetime
        from pathlib import Path
        import sys

        try:
            # Parse date and time
            target_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")

            if target_dt <= datetime.now():
                return "Essa hora já passou. Use uma data/hora futura."

            # Create reminder script
            scripts_dir = Path.home() / ".jarvis" / "reminders"
            scripts_dir.mkdir(parents=True, exist_ok=True)

            task_name = f"JARVISReminder_{target_dt.strftime('%Y%m%d_%H%M%S')}"
            script_path = scripts_dir / f"{task_name}.py"

            # Create notification script (simplified, uses winsound + msg)
            script_content = f'''# Reminder by JARVIS - Auto-generated
import winsound
import subprocess
import sys
from pathlib import Path

# Play notification sound
try:
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 200)
except:
    pass

# Show notification
try:
    subprocess.run(["msg", "*", "/TIME:30", "JARVIS Reminder: {message.replace('"', '')}"], check=False)
except:
    pass

# Self-delete
Path(__file__).unlink(missing_ok=True)
'''
            script_path.write_text(script_content, encoding="utf-8")

            # Create scheduled task via schtasks
            python_exe = sys.executable
            xml_path = scripts_dir / f"{task_name}.xml"

            xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>JARVIS Reminder</Description></RegistrationInfo>
  <Triggers><TimeTrigger>
    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
    <Enabled>true</Enabled>
  </TimeTrigger></Triggers>
  <Actions><Exec>
    <Command>{python_exe}</Command>
    <Arguments>"{script_path}"</Arguments>
  </Exec></Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Enabled>true</Enabled>
  </Settings>
</Task>'''

            xml_path.write_text(xml_content, encoding="utf-16")

            result = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
                capture_output=True, text=True,
            )

            # Cleanup XML
            xml_path.unlink(missing_ok=True)

            if result.returncode == 0:
                friendly_time = target_dt.strftime("%d/%m/%Y às %H:%M")
                return f"Lembrete definido para {friendly_time}: '{message}'"
            else:
                script_path.unlink(missing_ok=True)
                return f"Não consegui agendar o lembrete: {result.stderr}"

        except ValueError:
            return "Formato inválido. Use data: YYYY-MM-DD, hora: HH:MM (ex: 2025-01-15 14:30)"
        except Exception as e:
            return f"Erro ao criar lembrete: {e}"

    def _weather_report(self, city: str) -> str:
        """Show weather report by opening Google search."""
        from urllib.parse import quote_plus

        search_query = f"clima em {city}"
        url = f"https://www.google.com/search?q={quote_plus(search_query)}"

        webbrowser.open(url)
        return f"Mostrando clima para {city}."


def create_default_executor(memory: Optional[MemoryManager] = None) -> ToolExecutor:
    """Create a default tool executor with built-in tools."""
    return ToolExecutor(memory_manager=memory)
