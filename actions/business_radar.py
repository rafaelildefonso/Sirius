import json
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
BUSINESS_PROFILE_FILE = CONFIG_DIR / "user_profile_business.json"


def business_radar(parameters: dict, player=None, speak=None) -> str:
    """Controls the Business Prospecting Radar features via voice commands."""
    params = parameters or {}
    action = params.get("action", "search").lower().strip()
    estado = params.get("estado", "").strip()

    if not estado:
        if BUSINESS_PROFILE_FILE.exists():
            try:
                with open(BUSINESS_PROFILE_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    estado = d.get("state", "SP")
            except Exception:
                pass
    if not estado:
        estado = "SP"

    if action == "search":
        msg = f"Certo, senhor. Iniciando prospecção de empresas em '{estado}' no Google Maps."
        if speak:
            speak(msg)
        return msg

    elif action == "analyze":
        def run_analysis():
            from core.intel.business_analyzer import analyze_all_businesses
            analyze_all_businesses()

        threading.Thread(target=run_analysis, daemon=True).start()
        msg = "Certo, senhor. Analisando as empresas salvas com base no seu perfil de prospecção."
        if speak:
            speak(msg)
        return msg

    elif action == "list":
        msg = "Abrindo o painel do radar de prospecção para você visualizar as empresas encontradas."
        if speak:
            speak(msg)
        return msg

    elif action == "export":
        msg = "Não foi possível exportar. Abra o radar de prospecção primeiro."
        if speak:
            speak(msg)
        return msg

    return "Ação não reconhecida para o radar de prospecção."
