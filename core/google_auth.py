import os
import os.path
import json
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Se alterar estes escopos, delete o arquivo token.json.
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def get_google_service(service_name, version):
    """
    Autentica o usuário e retorna o objeto do serviço solicitado.
    """
    creds = None
    base_dir = get_base_dir()
    config_dir = base_dir / "config"
    token_path = config_dir / "google_token.json"
    
    # Tenta carregar credenciais manuais de api_keys.json se client_secrets.json não existir
    client_secrets_path = config_dir / "client_secrets.json"
    api_keys_path = config_dir / "api_keys.json"
    
    manual_creds = {}
    try:
        if api_keys_path.exists():
            api_data = json.loads(api_keys_path.read_text(encoding="utf-8"))
            manual_creds = api_data.get("google_creds", {})
    except Exception:
        pass

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            # Se não houver credenciais, precisamos rodar o fluxo
            # Mas aqui apenas retornamos None, o fluxo deve ser iniciado pela UI
            return None

    try:
        service = build(service_name, version, credentials=creds)
        return service
    except Exception as e:
        print(f"[GoogleAuth] Erro ao criar serviço {service_name}: {e}")
        return None

def run_auth_flow():
    """
    Inicia o fluxo de autenticação e salva o token.
    Retorna True se tiver sucesso.
    """
    base_dir = get_base_dir()
    config_dir = base_dir / "config"
    token_path = config_dir / "google_token.json"
    client_secrets_path = config_dir / "client_secrets.json"

    # Verificamos se existe o arquivo ou se as chaves estão no api_keys.json
    flow = None
    if client_secrets_path.exists():
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
    else:
        # Tenta usar chaves manuais (o usuário pode ter colado na UI)
        try:
            api_data = json.loads((config_dir / "api_keys.json").read_text(encoding="utf-8"))
            g = api_data.get("google_creds", {})
            if g.get("client_id") and g.get("client_secret"):
                client_config = {
                    "installed": {
                        "client_id": g["client_id"],
                        "client_secret": g["client_secret"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        except Exception:
            pass

    if not flow:
        return False, "Credenciais do Google não configuradas. Forneça o Client ID e Secret nas configurações."

    try:
        creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        return True, "Autenticação concluída com sucesso!"
    except Exception as e:
        return False, f"Erro na autenticação: {e}"
