# config/permissions.py
"""Permission management for the Sirius assistant.

Each "permission category" maps to one or more tools.  The user can enable or
disable categories from the UI. When a tool is called and its category is
disabled, Sirius shows a runtime popup before proceeding.
"""

from __future__ import annotations

import json
from pathlib import Path

_PERM_PATH = Path(__file__).parent / "permissions.json"

# ── Metadata (displayed in the UI) ────────────────────────────────────────────

PERMISSION_META: dict[str, dict] = {
    "control_mouse_keyboard": {
        "label":       "Controlar Mouse e Teclado",
        "description": "Mover o cursor, clicar e digitar automaticamente.",
        "icon":        "fa5s.mouse",
    },
    "view_screen": {
        "label":       "Visualizar Tela",
        "description": "Capturar e analisar a tela do computador.",
        "icon":        "fa5s.desktop",
    },
    "view_camera": {
        "label":       "Acessar Câmera",
        "description": "Capturar imagens da webcam.",
        "icon":        "fa5s.camera",
    },
    "manage_files": {
        "label":       "Gerenciar Arquivos",
        "description": "Criar, editar, mover e excluir arquivos e pastas.",
        "icon":        "fa5s.folder",
    },
    "execute_commands": {
        "label":       "Executar Comandos e Código",
        "description": "Rodar scripts, compilar e executar programas.",
        "icon":        "fa5s.bolt",
    },
    "access_web_browser": {
        "label":       "Controlar Navegador",
        "description": "Abrir sites, pesquisar e interagir com páginas web.",
        "icon":        "fa5s.globe",
    },
    "open_applications": {
        "label":       "Abrir Aplicativos",
        "description": "Iniciar programas instalados no computador.",
        "icon":        "fa5s.rocket",
    },
    "access_personal_accounts": {
        "label":       "Acessar Contas Pessoais",
        "description": "Ler e gerenciar Gmail, Google Calendar e Notion Calendar.",
        "icon":        "fa5s.lock",
    },
    "send_messages": {
        "label":       "Enviar Mensagens e Lembretes",
        "description": "Enviar mensagens via WhatsApp, Telegram e criar lembretes.",
        "icon":        "fa5s.comment-dots",
    },
}

# ── Tool → Permission category ─────────────────────────────────────────────────

TOOL_TO_PERMISSION: dict[str, str] = {
    "computer_control":   "control_mouse_keyboard",
    "computer_settings":  "control_mouse_keyboard",
    "screen_process":     "view_screen",
    "file_controller":    "manage_files",
    "file_processor":     "manage_files",
    "desktop_control":    "manage_files",
    "workspaces":         "manage_files",
    "code_helper":        "execute_commands",
    "dev_agent":          "execute_commands",
    "agent_task":         "execute_commands",
    "browser_control":    "access_web_browser",
    "web_search":         "access_web_browser",
    "deep_research":      "access_web_browser",
    "linkedin_jobs_radar":"access_web_browser",
    "apply_assist":       "access_web_browser",
    "business_radar":     "access_web_browser",
    "youtube_video":      "access_web_browser",
    "flight_finder":      "access_web_browser",
    "weather_report":     "access_web_browser",
    "open_app":           "open_applications",
    "game_updater":       "open_applications",
    "gmail":              "access_personal_accounts",
    "google_calendar":    "access_personal_accounts",
    "notion_calendar":    "access_personal_accounts",
    "send_message":       "send_messages",
    "reminder":           "send_messages",
}

_DEFAULTS: dict[str, bool] = {k: True for k in PERMISSION_META}

# ── Public API ─────────────────────────────────────────────────────────────────

def get_permissions() -> dict[str, bool]:
    """Return the current permission state, filling missing keys with True."""
    data: dict[str, bool] = dict(_DEFAULTS)
    if _PERM_PATH.exists():
        try:
            saved = json.loads(_PERM_PATH.read_text(encoding="utf-8"))
            data.update({k: bool(v) for k, v in saved.items() if k in _DEFAULTS})
        except Exception:
            pass
    return data


def save_permissions(perms: dict[str, bool]) -> None:
    """Write permissions to disk."""
    _PERM_PATH.write_text(json.dumps(perms, indent=4), encoding="utf-8")


def is_granted(tool_name: str) -> bool:
    """Return True if the tool's permission category is currently enabled."""
    perm_key = TOOL_TO_PERMISSION.get(tool_name)
    if perm_key is None:
        return True  # Unknown tools always pass through
    return get_permissions().get(perm_key, True)


def get_category(tool_name: str) -> str | None:
    """Return the permission category key for a tool, or None."""
    return TOOL_TO_PERMISSION.get(tool_name)


def grant_permission(perm_key: str) -> None:
    """Permanently enable a permission category and persist to disk."""
    perms = get_permissions()
    perms[perm_key] = True
    save_permissions(perms)
