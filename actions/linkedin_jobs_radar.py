# actions/linkedin_jobs_radar.py
import json
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
PROFILE_FILE = CONFIG_DIR / "user_profile.json"

def linkedin_jobs_radar(parameters: dict, player=None, speak=None) -> str:
    """Controls the LinkedIn Jobs Radar features via voice commands."""
    params = parameters or {}
    action = params.get("action", "search").lower().strip()
    keywords = params.get("keywords", "").strip()

    # Load default keywords if none provided
    if not keywords and PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                roles = d.get("target_roles", [])
                if roles:
                    keywords = roles[0]
        except Exception:
            pass

    if not keywords:
        keywords = "Desenvolvedor de Software"

    if action == "search":
        msg = f"Certo, senhor. Estou iniciando a busca automática por vagas de '{keywords}' no LinkedIn e abrindo o painel de triagem inteligente."
        if speak:
            speak(msg)
        return msg

    elif action == "analyze":
        def run_analysis():
            from core.intel.job_analyzer import analyze_all_jobs
            analyze_all_jobs()

        threading.Thread(target=run_analysis, daemon=True).start()
        msg = "Certo, senhor. Analisando as vagas salvas com base no seu perfil."
        if speak:
            speak(msg)
        return msg

    elif action == "list":
        msg = "Abrindo o painel do radar de vagas para você visualizar as oportunidades encontradas."
        if speak:
            speak(msg)
        return msg

    return "Ação não reconhecida para o radar de vagas."
