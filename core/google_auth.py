from __future__ import annotations

import concurrent.futures
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from core.cache import service_cache
from core.config_loader import get_google_creds

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
]

_GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
_GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"

_auth_lock = threading.Lock()


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_google_service(service_name: str, version: str):
    cache_key = f"{service_name}:{version}"
    cached = service_cache.get(cache_key)
    if cached is not None:
        return cached

    creds = _load_credentials()
    if creds is None:
        return None

    if not creds.valid:
        _try_refresh(creds)
    if not creds or not creds.valid:
        return None

    try:
        service = build(service_name, version, credentials=creds)
        service_cache.set(cache_key, service, ttl=3600)
        return service
    except Exception as e:
        print(f"[GoogleAuth] Erro ao criar servico {service_name}: {e}")
        return None


def run_auth_flow():
    if not _auth_lock.acquire(blocking=False):
        return False, "Um fluxo de autenticacao ja esta em andamento."

    try:
        return _run_auth_flow_impl()
    finally:
        _auth_lock.release()


def is_token_valid(time_buffer_s: int = 300) -> bool:
    from core.credential_manager import load_google_token
    token_dict = load_google_token()
    if not token_dict:
        return False
    expiry_str = token_dict.get("expiry")
    if not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(expiry_str)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return (expiry - datetime.now(timezone.utc)).total_seconds() > time_buffer_s
    except Exception:
        return False


def _load_credentials() -> Credentials | None:
    from core.credential_manager import load_google_token
    token_dict = load_google_token()
    if not token_dict:
        return None

    creds = get_google_creds()
    if not creds.get("client_id") or not creds.get("client_secret"):
        return None

    token_dict["client_id"] = creds["client_id"]
    token_dict["client_secret"] = creds["client_secret"]
    token_dict.setdefault("token_uri", _GOOGLE_TOKEN_URI)

    try:
        return Credentials.from_authorized_user_info(token_dict, SCOPES)
    except Exception:
        return None


def _try_refresh(creds: Credentials) -> None:
    if not creds.expired and not _should_proactive_refresh(creds):
        return
    if not creds.refresh_token:
        return
    try:
        creds.refresh(Request())
        _persist_credentials(creds)
    except Exception:
        print("[GoogleAuth] Falha ao renovar token.")


def _should_proactive_refresh(creds: Credentials) -> bool:
    if not creds.expiry:
        return False
    try:
        remaining = (creds.expiry - datetime.now(timezone.utc)).total_seconds()
        return remaining < 300
    except Exception:
        return False


def _persist_credentials(creds: Credentials) -> None:
    from core.credential_manager import save_google_token
    raw = json.loads(creds.to_json())
    raw.pop("client_id", None)
    raw.pop("client_secret", None)
    save_google_token(raw)


def _run_auth_flow_impl():
    base_dir = get_base_dir()
    config_dir = base_dir / "config"
    client_secrets_path = config_dir / "client_secrets.json"

    client_config = _build_client_config(client_secrets_path)
    if client_config is None:
        return False, "Credenciais do Google nao configuradas. Forneca o Client ID e Secret nas configuracoes ou no arquivo .env."

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(flow.run_local_server, port=0)
            creds = future.result(timeout=120)
    except concurrent.futures.TimeoutError:
        return False, "Tempo limite excedido (120s). O navegador demorou muito para responder."
    except Exception as e:
        return False, f"Erro na autenticacao: {e}"

    _persist_credentials(creds)
    return True, "Autenticacao concluida com sucesso!"


def _build_client_config(client_secrets_path: Path) -> dict | None:
    if client_secrets_path.exists():
        try:
            secrets = json.loads(client_secrets_path.read_text(encoding="utf-8"))
            installed = secrets.get("installed") or secrets.get("web")
            if installed and installed.get("client_id") and installed.get("client_secret"):
                return secrets
        except Exception:
            pass

    creds = get_google_creds()
    if creds.get("client_id") and creds.get("client_secret"):
        return {
            "installed": {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "auth_uri": _GOOGLE_AUTH_URI,
                "token_uri": _GOOGLE_TOKEN_URI,
            }
        }

    return None
