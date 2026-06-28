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
        if player and hasattr(player, "_win"):
            try:
                from ui.business_radar_widget import C
                player._win.left_stack.setCurrentIndex(2)
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

                from ui.business_radar_widget import BusinessRadarWidget
                if hasattr(player._win, "business_radar"):
                    player._win.business_radar.estado_input.setText(estado)
                    player._win.business_radar.refresh_btn.setEnabled(False)
                    player._win.business_radar.progress_bar.show()
                    player._win.business_radar.log_lbl.setText(
                        f"Prospecção iniciada por comando de voz para '{estado}'..."
                    )
                    player._win.business_radar.log_lbl.show()

                    max_results = (
                        player._win.business_radar.limit_spin.value()
                        if hasattr(player._win.business_radar, "limit_spin") else 30
                    )

                    from ui.business_radar_widget import ScrapeWorker
                    player._win.business_radar.worker = ScrapeWorker(estado, max_results=max_results)
                    player._win.business_radar.worker.log_signal.connect(
                        player._win.business_radar._update_log
                    )
                    player._win.business_radar.worker.finished.connect(
                        player._win.business_radar._scan_finished
                    )
                    player._win.business_radar.worker.start()

            except Exception as e:
                print(f"[Business Radar Action] Erro ao integrar com a UI: {e}")

        msg = f"Certo, senhor. Iniciando prospecção de empresas em '{estado}' no Google Maps."
        if speak:
            speak(msg)
        return msg

    elif action == "analyze":
        if player and hasattr(player, "_win") and hasattr(player._win, "business_radar"):
            player._win.business_radar.log_lbl.setText("Analisando empresas via Gemini...")
            player._win.business_radar.log_lbl.show()

            def run_analysis():
                from core.business_analyzer import analyze_all_businesses
                analyzed = analyze_all_businesses()
                player._win.business_radar.load_businesses()
                player._win.business_radar.log_lbl.setText(
                    f"Análise finalizada! {analyzed} empresas processadas."
                )

            threading.Thread(target=run_analysis, daemon=True).start()

        msg = "Certo, senhor. Analisando as empresas salvas com base no seu perfil de prospecção."
        if speak:
            speak(msg)
        return msg

    elif action == "list":
        if player and hasattr(player, "_win"):
            player._win.left_stack.setCurrentIndex(2)
            from ui.business_radar_widget import C
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

        msg = "Abrindo o painel do radar de prospecção para você visualizar as empresas encontradas."
        if speak:
            speak(msg)
        return msg

    elif action == "export":
        if player and hasattr(player, "_win") and hasattr(player._win, "business_radar"):
            player._win.business_radar._export_csv()
            msg = "Exportando empresas para CSV."
        else:
            msg = "Não foi possível exportar. Abra o radar de prospecção primeiro."
        if speak:
            speak(msg)
        return msg

    return "Ação não reconhecida para o radar de prospecção."
