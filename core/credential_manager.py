from __future__ import annotations

import json
from pathlib import Path

try:
    import keyring
    HAS_KEYRING = True
except Exception:
    HAS_KEYRING = False

GOOGLE_SERVICE = "sirius_google"
GOOGLE_ACCOUNT = "oauth_token"


def _fallback_path() -> Path:
    from core.config_loader import get_base_dir
    return get_base_dir() / "config" / "google_token.json"


def save_google_token(token_dict: dict) -> None:
    payload = json.dumps(token_dict)
    if HAS_KEYRING:
        try:
            keyring.set_password(GOOGLE_SERVICE, GOOGLE_ACCOUNT, payload)
            return
        except Exception:
            pass
    _fallback_path().write_text(payload, encoding="utf-8")


def load_google_token() -> dict | None:
    if HAS_KEYRING:
        try:
            raw = keyring.get_password(GOOGLE_SERVICE, GOOGLE_ACCOUNT)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    path = _fallback_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def delete_google_token() -> None:
    if HAS_KEYRING:
        try:
            keyring.delete_password(GOOGLE_SERVICE, GOOGLE_ACCOUNT)
        except Exception:
            pass
    path = _fallback_path()
    if path.exists():
        path.unlink(missing_ok=True)
