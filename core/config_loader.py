from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_CONFIGS_FILE = "configs.json"
_SECRETS_FILE = "api_keys.json"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    return get_base_dir() / "config"


def _load_dotenv() -> None:
    dotenv_path = get_base_dir() / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=False)


def _read_json(filename: str) -> dict:
    path = _config_dir() / filename
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_json(filename: str, data: dict) -> None:
    path = _config_dir() / filename
    _config_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_secret(key: str, default: str | None = None) -> str | None:
    _load_dotenv()
    value = os.environ.get(key)
    if value:
        return value
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get(key, default)


def set_secret(key: str, value: str) -> None:
    _load_dotenv()
    dotenv_path = get_base_dir() / ".env"
    lines = []
    if dotenv_path.exists():
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    _config_dir().mkdir(parents=True, exist_ok=True)
    dotenv_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def get_config(key: str, default: str | None = None) -> str | None:
    data = _read_json(_CONFIGS_FILE)
    if key in data:
        return data.get(key, default)
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get(key, default)


def set_config(key: str, value: str | int | bool) -> None:
    data = _read_json(_CONFIGS_FILE)
    data[key] = value
    _write_json(_CONFIGS_FILE, data)


def get_all_config() -> dict:
    configs = _read_json(_CONFIGS_FILE)
    legacy = _read_json(_SECRETS_FILE)
    merged = dict(legacy)
    merged.update(configs)
    return merged


def save_configs(data: dict) -> None:
    clean = {k: v for k, v in data.items() if k not in (
        "gemini_api_key", "openrouter_api_key", "tavily_api_key",
        "serpapi_key", "google_creds", "notion_creds",
    )}
    _write_json(_CONFIGS_FILE, clean)


def get_google_creds() -> dict:
    _load_dotenv()
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or ""
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or ""
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get("google_creds", {})


def get_notion_creds() -> dict:
    _load_dotenv()
    token = os.environ.get("NOTION_TOKEN") or ""
    db_id = os.environ.get("NOTION_DATABASE_ID") or ""
    if token:
        result = {"token": token}
        if db_id:
            result["database_id"] = db_id
        return result
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get("notion_creds", {})


def set_notion_creds(token: str, database_id: str = "") -> None:
    set_secret("NOTION_TOKEN", token)
    if database_id:
        set_secret("NOTION_DATABASE_ID", database_id)


def get_os() -> str:
    value = get_config("os_system")
    if value:
        return value.lower()
    import platform
    s = platform.system().lower()
    if s == "darwin":
        return "mac"
    if s == "windows":
        return "windows"
    return "linux"


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"
