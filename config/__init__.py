# config/__init__.py
import json, os, sys
from pathlib import Path

def _get_config_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config"
    return Path(__file__).resolve().parent

_CONFIG_DIR = _get_config_dir()
_CONFIG_PATH = _CONFIG_DIR / "api_keys.json"

def get_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_os() -> str:
    """Returns: 'windows' | 'mac' | 'linux'"""
    return get_config().get("os_system", "windows").lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"