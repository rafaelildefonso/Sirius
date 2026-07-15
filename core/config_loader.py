from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

_CONFIGS_FILE = "configs.json"
_SECRETS_FILE = "api_keys.json"


def get_base_dir() -> Path:
    data_dir = os.environ.get("SIRIUS_DATA_DIR")
    if data_dir:
        return Path(data_dir)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    return get_base_dir() / "config"


def _load_dotenv() -> None:
    dotenv_path = get_base_dir() / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=True)


def _read_json(filename: str) -> dict:
    path = _config_dir() / filename
    try:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            print(f"[CONFIG] Read {filename}: {len(content)} bytes, {len(data)} keys")
            return data
    except Exception:
        print(f"[CONFIG] Failed to read {filename}")
        traceback.print_exc()
    return {}


def _write_json(filename: str, data: dict) -> None:
    path = _config_dir() / filename
    _config_dir().mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2)
    path.write_text(content, encoding="utf-8")
    print(f"[CONFIG] Wrote {filename}: {len(content)} bytes, keys={list(data.keys())}")


def get_secret(key: str, default: str | None = None) -> str | None:
    _load_dotenv()
    value = os.environ.get(key)
    if value:
        return value
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get(key, default)


def set_secret(key: str, value: str) -> None:
    _load_dotenv()
    # Normalize well-known credential keys to uppercase for .env convention
    _UPCASE_KEYS = {
        "google_client_id": "GOOGLE_CLIENT_ID",
        "google_client_secret": "GOOGLE_CLIENT_SECRET",
        "notion_token": "NOTION_TOKEN",
        "notion_database_id": "NOTION_DATABASE_ID",
    }
    key = _UPCASE_KEYS.get(key, key)
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
    os.environ[key] = value


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
    # Flatten legacy google_creds / notion_creds dicts
    gc = merged.pop("google_creds", {})
    if isinstance(gc, dict):
        merged.setdefault("google_client_id", gc.get("client_id", ""))
        merged.setdefault("google_client_secret", gc.get("client_secret", ""))
    nc = merged.pop("notion_creds", {})
    if isinstance(nc, dict):
        merged.setdefault("notion_token", nc.get("token", ""))
        merged.setdefault("notion_database_id", nc.get("database_id", ""))
    # Merge secret keys from env vars so UI can display them
    _load_dotenv()
    for key in ("gemini_api_key", "openrouter_api_key", "tavily_api_key", "serpapi_key",
                "elevenlabs_api_key",
                "google_client_id", "google_client_secret",
                "notion_token", "notion_database_id"):
        val = os.environ.get(key) or os.environ.get(key.upper()) or merged.get(key)
        if val:
            merged[key] = val
    am = merged.get("assistant_mode", "<not set>")
    print(f"[CONFIG] get_all_config() -> assistant_mode={am!r}, configs keys={list(configs.keys())}, legacy keys={list(legacy.keys())}")
    return merged


def save_configs(data: dict) -> None:
    clean = {k: v for k, v in data.items() if k not in (
        "gemini_api_key", "openrouter_api_key", "tavily_api_key",
        "serpapi_key", "elevenlabs_api_key",
        "google_creds", "notion_creds",
        "google_client_id", "google_client_secret",
        "notion_token", "notion_database_id",
    )}
    am = clean.get("assistant_mode", "<not set>")
    print(f"[CONFIG] save_configs() -> assistant_mode={am!r}, clean keys={list(clean.keys())}")
    _write_json(_CONFIGS_FILE, clean)
    # Read back and verify
    verify = _read_json(_CONFIGS_FILE)
    vam = verify.get("assistant_mode", "<not set>")
    if vam != am:
        print(f"[CONFIG] VERIFY FAILED: expected assistant_mode={am!r}, got {vam!r}")
    else:
        print(f"[CONFIG] Verify OK: assistant_mode={vam!r}")
    # Invalidate llm_client and llm_utils config caches so they pick up changes immediately
    try:
        from core.cache import config_cache
        config_cache.invalidate("app_config")
        config_cache.invalidate("llm_utils_config")
        print(f"[CONFIG] Invalidated config caches (app_config, llm_utils_config)")
    except Exception:
        pass


def get_google_creds() -> dict:
    _load_dotenv()
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("google_client_id") or ""
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or os.environ.get("google_client_secret") or ""
    if client_id and client_secret:
        return {"client_id": client_id, "client_secret": client_secret}
    legacy = _read_json(_SECRETS_FILE)
    return legacy.get("google_creds", {})


def get_notion_creds() -> dict:
    _load_dotenv()
    token = os.environ.get("NOTION_TOKEN") or os.environ.get("notion_token") or ""
    db_id = os.environ.get("NOTION_DATABASE_ID") or os.environ.get("notion_database_id") or ""
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
