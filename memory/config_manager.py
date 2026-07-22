import json
from pathlib import Path

from core.config_loader import get_secret, get_all_config, save_configs as _save_configs


def get_base_dir() -> Path:
    from core.config_loader import get_base_dir as _get_base_dir
    return _get_base_dir()


def ensure_config_dir() -> None:
    (get_base_dir() / "config").mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    # Check if the main configuration file exists without loading its content.
    cfg_path = get_base_dir() / "config" / "configs.json"
    return cfg_path.is_file()

def save_config(cfg: dict) -> None:
    _save_configs(cfg)

def save_api_keys(gemini_api_key: str) -> None:
    from core.config_loader import set_secret
    set_secret("GEMINI_API_KEY", gemini_api_key.strip())
    config_dir = get_base_dir() / "config"
    api_keys_path = config_dir / "api_keys.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {}
    if api_keys_path.exists():
        try:
            data = json.loads(api_keys_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["gemini_api_key"] = gemini_api_key.strip()
    api_keys_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_api_keys() -> dict:
    return get_all_config()

def get_gemini_key() -> str | None:
    return get_secret("gemini_api_key") or None

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    cfg = get_all_config()
    return cfg.get("assistant_name", "SIRIUS") or "SIRIUS"


def get_user_name() -> str:
    cfg = get_all_config()
    return cfg.get("user_name", "")


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    ensure_config_dir()
    cfg = get_all_config()
    cfg["assistant_name"] = assistant_name.strip() or "SIRIUS"
    cfg["user_name"] = user_name.strip()
    _save_configs(cfg)


def get_speak_greeting_enabled() -> bool:
    cfg = get_all_config()
    return cfg.get("speak_greeting_enabled", True)

def save_speak_greeting_enabled(enabled: bool) -> None:
    ensure_config_dir()
    cfg = get_all_config()
    cfg["speak_greeting_enabled"] = enabled
    _save_configs(cfg)

def get_speak_news_enabled() -> bool:
    cfg = get_all_config()
    return cfg.get("speak_news_enabled", True)

def save_speak_news_enabled(enabled: bool) -> None:
    ensure_config_dir()
    cfg = get_all_config()
    cfg["speak_news_enabled"] = enabled
    _save_configs(cfg)

def get_speak_briefing_enabled() -> bool:
    cfg = get_all_config()
    return cfg.get("speak_briefing_enabled", True)

def save_speak_briefing_enabled(enabled: bool) -> None:
    ensure_config_dir()
    cfg = get_all_config()
    cfg["speak_briefing_enabled"] = enabled
    _save_configs(cfg)

def get_speak_proactive_enabled() -> bool:
    cfg = get_all_config()
    return cfg.get("speak_proactive_enabled", True)

def save_speak_proactive_enabled(enabled: bool) -> None:
    ensure_config_dir()
    cfg = get_all_config()
    cfg["speak_proactive_enabled"] = enabled
    _save_configs(cfg)
