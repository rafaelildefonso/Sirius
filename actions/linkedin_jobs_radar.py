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
        except:
            pass
            
    if not keywords:
        keywords = "Desenvolvedor de Software"
        
    if action == "search":
        # Toggle view to Job Radar in UI and trigger search
        if player and hasattr(player, "_win"):
            try:
                # Run this in a safe main thread transition if PyQt requires, but QWidget methods are usually fine or we call via QTimer/Signals
                # Let's switch view to radar tab
                player._win.left_stack.setCurrentIndex(1)
                
                # Update button text/style
                from ui.job_radar_widget import C
                player._win._view_btn.setText("ASSISTENTE DE VOZ")
                player._win._view_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; color: {C.ACC};
                        border: 1px solid {C.ACC}; border-radius: 3px; padding: 0 8px;
                    }}
                    QPushButton:hover {{
                        background: rgba(255, 107, 0, 0.1); color: {C.WHITE};
                    }}
                """)
                
                # Trigger scan on the JobRadar widget
                if hasattr(player._win, "job_radar"):
                    player._win.job_radar.refresh_btn.setEnabled(False)
                    player._win.job_radar.progress_bar.show()
                    player._win.job_radar.log_lbl.setText(f"Radar iniciado por comando de voz para '{keywords}'...")
                    player._win.job_radar.log_lbl.show()
                    
                    # Read max_jobs from the UI spinbox or default
                    max_jobs = player._win.job_radar.limit_spin.value() if hasattr(player._win.job_radar, 'limit_spin') else 8
                    sources = ["linkedin", "google_jobs"]
                    
                    # Start the QThread worker
                    from ui.job_radar_widget import ScrapeWorker
                    player._win.job_radar.worker = ScrapeWorker(keywords, max_jobs=max_jobs, sources=sources)
                    player._win.job_radar.worker.log_signal.connect(player._win.job_radar._update_log)
                    player._win.job_radar.worker.finished.connect(player._win.job_radar._scan_finished)
                    player._win.job_radar.worker.start()
                    
            except Exception as e:
                print(f"[Linkedin Jobs Radar Action] Erro ao integrar com a UI: {e}")
                
        msg = f"Certo, senhor. Estou iniciando a busca automática por vagas de '{keywords}' no LinkedIn e abrindo o painel de triagem inteligente."
        if speak:
            speak(msg)
        return msg
        
    elif action == "analyze":
        if player and hasattr(player, "_win") and hasattr(player._win, "job_radar"):
            # Trigger analysis
            player._win.job_radar.log_lbl.setText("Analisando vagas via Gemini...")
            player._win.job_radar.log_lbl.show()
            
            def run_analysis():
                from core.job_analyzer import analyze_all_jobs
                analyzed = analyze_all_jobs()
                # Safe reload jobs in UI
                player._win.job_radar.load_jobs()
                player._win.job_radar.log_lbl.setText(f"Análise finalizada! {analyzed} vagas processadas.")
                
            threading.Thread(target=run_analysis, daemon=True).start()
            
        msg = "Certo, senhor. Analisando as vagas salvas com base no seu perfil."
        if speak:
            speak(msg)
        return msg
        
    elif action == "list":
        # Toggle view to radar
        if player and hasattr(player, "_win"):
            player._win.left_stack.setCurrentIndex(1)
            player._win._view_btn.setText("ASSISTENTE DE VOZ")
            
        msg = "Abrindo o painel do radar de vagas para você visualizar as oportunidades encontradas."
        if speak:
            speak(msg)
        return msg
        
    return "Ação não reconhecida para o radar de vagas."
