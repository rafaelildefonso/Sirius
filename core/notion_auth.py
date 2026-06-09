import os
import json
import sys
from pathlib import Path

import requests

from core.config_loader import get_notion_creds as _get_notion_creds, set_notion_creds as _set_notion_creds


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2026-03-11",
        "Content-Type": "application/json"
    }


def get_notion_token() -> str | None:
    """Read the static Notion API token from .env or api_keys.json"""
    creds = _get_notion_creds()
    token = creds.get("token")
    if token:
        return token
    return os.environ.get("NOTION_TOKEN") or None


def save_notion_token(token: str) -> None:
    """Save the static Notion API token to .env and api_keys.json (backward compat)"""
    _set_notion_creds(token)
    base_dir = get_base_dir()
    config_dir = base_dir / "config"
    api_keys_path = config_dir / "api_keys.json"
    config_dir.mkdir(exist_ok=True)
    data = {}
    if api_keys_path.exists():
        try:
            data = json.loads(api_keys_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("notion_creds", {})["token"] = token
    api_keys_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_notion_client() -> dict | None:
    """Get authenticated headers for Notion API requests."""
    token = get_notion_token()
    if not token:
        return None
    return get_notion_headers(token)
