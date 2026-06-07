import os
import json
import sys
from pathlib import Path

import requests


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
    """Read the static Notion API token from api_keys.json -> notion_creds.token"""
    base_dir = get_base_dir()
    api_keys_path = base_dir / "config" / "api_keys.json"

    if api_keys_path.exists():
        try:
            api_data = json.loads(api_keys_path.read_text(encoding="utf-8"))
            token = api_data.get("notion_creds", {}).get("token")
            if token:
                return token
        except Exception:
            pass
    return os.environ.get("NOTION_TOKEN") or None


def save_notion_token(token: str) -> None:
    """Save the static Notion API token to api_keys.json -> notion_creds.token"""
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
