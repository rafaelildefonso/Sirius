# actions/freela_arsenal.py
import json
import os
import threading
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = Path.home() / "Downloads"
CONFIG_DIR = BASE_DIR / "config"
PROFILE_FILE = CONFIG_DIR / "user_profile.json"

# -- Mensagem padrão para prospecção via WhatsApp --
DEFAULT_WHATSAPP_MSG = (
    "Olá, {nome}! Tudo bem?\n\n"
    "Sou da Marco Um, agência especializada em criação de sites profissionais. "
    "Notei que {nome} ainda não possui um site e gostaria de apresentar como "
    "podemos ajudar a fortalecer a presença digital de vocês.\n\n"
    "Desenvolvemos sites modernos, responsivos e otimizados para o Google — "
    "ideais para {segmento} em {cidade}.\n\n"
    "Posso enviar um orçamento sem compromisso?"
)


def _call_maps_scraper(segmentos, cidade, max_por_seg, mostrar_navegador, log_func=None):
    """Wrapper para rodar o maps scraper (síncrono) em thread."""
    from core.google_maps_scraper import scrape_google_maps
    return scrape_google_maps(
        segmentos=segmentos,
        cidade=cidade,
        max_por_segmento=max_por_seg,
        mostrar_navegador=mostrar_navegador,
        log_func=log_func,
    )


def _call_deep_research(competencias, target, regiao, player):
    """Wrapper para deep research."""
    from actions.deep_research import deep_research
    return deep_research(
        parameters={
            "competencies": competencias,
            "target_audience": target,
            "region": regiao,
        },
        player=player,
    )


def _format_maps_result(resultado, detalhado=False):
    """Formata resultado do Maps scraper para texto."""
    r = resultado["resumo"]
    lines = [
        f"[MAPS]  PROSPECÇÃO GOOGLE MAPS",
        f"   Total de empresas encontradas: {r['total_encontrado']}",
        f"   Com telefone: {r['com_telefone']}",
        f"   Com site: {r['com_site']}",
        f"   Sem site (alvo prospecção): {r['sem_site']}",
        f"   Links WhatsApp gerados: {r['whatsapp_gerados']}",
    ]

    if detalhado and resultado["sem_site"]:
        lines.append("")
        lines.append("   Empresas sem site (top 10):")
        for emp in resultado["sem_site"][:10]:
            tel = emp["telefone"] or "sem telefone"
            lines.append(f"     - {emp['nome']} ({emp['segmento']}) | {tel}")

    if detalhado and resultado["whatsapp_links"]:
        lines.append("")
        lines.append("   Links WhatsApp (top 5):")
        for wa in resultado["whatsapp_links"][:5]:
            lines.append(f"     - {wa['nome']}: {wa['link_whatsapp']}")

    return "\n".join(lines)


def _salvar_resultados(objetivo, maps_result, dr_result):
    """Salva resultados em arquivos na pasta memory/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    arquivos = []

    if maps_result and maps_result["todos"]:
        from core.google_maps_scraper import salvar_csv, salvar_whatsapp_messages

        csv_path = DOWNLOADS_DIR / f"maps_prospeccao_{ts}.csv"
        salvar_csv(maps_result["todos"], str(csv_path))
        arquivos.append(str(csv_path))

        sem_site_csv = DOWNLOADS_DIR / f"maps_sem_site_{ts}.csv"
        salvar_csv(maps_result["sem_site"], str(sem_site_csv))
        arquivos.append(str(sem_site_csv))

        if maps_result["whatsapp_links"]:
            wa_path = DOWNLOADS_DIR / f"maps_whatsapp_{ts}.txt"
            salvar_whatsapp_messages(maps_result["whatsapp_links"], str(wa_path))
            arquivos.append(str(wa_path))

    if dr_result and "Deep Research Results" in dr_result:
        dr_path = DOWNLOADS_DIR / f"deep_research_{ts}.txt"
        with open(dr_path, "w", encoding="utf-8") as f:
            f.write(dr_result)
        arquivos.append(str(dr_path))

    return arquivos


def freela_arsenal(parameters: dict, player=None, speak=None) -> str:
    """
    Orquestrador central de prospecção de freelas.

    Combina:
      1. Google Maps -> encontra empresas sem site (prospecção ativa)
      2. Deep Research -> encontra leads de freelance na web

    Parâmetros:
      - objetivo: "tudo" | "prospectar_clientes" | "achar_vagas" | "so_maps"
      - competencias: suas habilidades (ex: "React, Python, Django")
      - target_audience: nicho de clientes (ex: "restaurantes, pet shops")
      - segmentos: segmentos p/ Maps (ex: "restaurante, pet shop")
      - cidade / regiao: localização
      - max_resultados: limite por fonte (default: 10)
      - mostrar_navegador: "true" pra ver o Chrome abrindo (default: "true")
      - detalhado: "true" pra listar empresas no relatório
      - gerar_arquivos: "false" pra não salvar CSV/TXT
    """
    params = parameters or {}
    objetivo = params.get("objetivo", "tudo").strip().lower()
    competencias = params.get("competencias", "").strip()
    target = params.get("target_audience", "").strip()
    segmentos_raw = params.get("segmentos", "").strip()
    cidade = params.get("cidade", "").strip()
    regiao = params.get("regiao", cidade or "").strip()
    max_resultados = min(int(params.get("max_resultados", 10)), 30)
    mostrar_navegador = str(params.get("mostrar_navegador", "true")).lower() == "true"
    detalhado = str(params.get("detalhado", "false")).lower() == "true"
    gerar_arquivos = str(params.get("gerar_arquivos", "true")).lower() == "true"

    segmentos = [s.strip() for s in segmentos_raw.split(",") if s.strip()]

    # -- Fallbacks a partir do perfil do usuário --
    if (not competencias or not target) and PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
            if not competencias:
                skills = profile.get("skills", [])
                if skills:
                    competencias = ", ".join(skills[:5])
            if not target:
                roles = profile.get("target_roles", [])
                if roles:
                    target = ", ".join(roles)
        except:
            pass

    if not competencias:
        competencias = "freelancer services"
    if not cidade:
        cidade = "Belo Horizonte"

    if not segmentos:
        segmentos = ["restaurante", "pet shop"]

    def _log(msg):
        if player:
            player.write_log(msg)

    _log(f"[FreelaArsenal] Objetivo: {objetivo} | Competências: {competencias} | Cidade: {cidade} | Navegador visível: {mostrar_navegador}")

    if speak:
        speak("Iniciando prospecção. Vou abrir o navegador e buscar empresas. Aviso o progresso aqui no chat.")

    # -- Execução --
    maps_result = None
    dr_result = None
    erros = []

    # 1. Google Maps (prospecção de clientes)
    rodar_maps = objetivo in ("tudo", "prospectar_clientes", "so_maps")
    if rodar_maps and segmentos:
        try:
            _log(f"Iniciando Maps: {len(segmentos)} segmento(s) em {cidade}, max {max_resultados} por segmento...")
            maps_result = _call_maps_scraper(
                segmentos, cidade, max_resultados, mostrar_navegador,
                log_func=lambda msg: _log(f"[Maps] {msg}"),
            )
            _log(f"Maps concluído: {maps_result['resumo']['total_encontrado']} empresas encontradas")
        except Exception as e:
            erros.append(f"MapsScraper: {e}")
            _log(f"ERRO no Maps: {e}")

    # 2. Deep Research (leads web)
    rodar_dr = objetivo in ("tudo", "achar_vagas", "prospectar_clientes")
    if rodar_dr:
        try:
            _log("Iniciando Deep Research na web...")
            dr_target = target or f"empresas de {', '.join(segmentos[:3])}" if segmentos else "empresas que precisam de serviços"
            dr_result = _call_deep_research(competencias, dr_target, regiao or cidade, player)
            _log("Deep Research concluído.")
        except Exception as e:
            erros.append(f"DeepResearch: {e}")
            _log(f"ERRO no Deep Research: {e}")

    # -- Montar relatório --
    report_parts = ["=" * 50, "  FREELA ARSENAL - RELATÓRIO COMPLETO", "=" * 50, ""]
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    report_parts.append(f"Gerado em: {now_str}")
    report_parts.append(f"Objetivo: {objetivo}")
    report_parts.append(f"Competências: {competencias}")
    report_parts.append("")

    if maps_result:
        report_parts.append(_format_maps_result(maps_result, detalhado=detalhado))
        report_parts.append("")

    if dr_result:
        report_parts.append(dr_result)
        report_parts.append("")

    if erros:
        report_parts.append("[WARN]  Alertas:")
        for e in erros:
            report_parts.append(f"   - {e}")
        report_parts.append("")

    total_empresas = maps_result["resumo"]["total_encontrado"] if maps_result else 0
    total_whatsapp = maps_result["resumo"]["whatsapp_gerados"] if maps_result else 0

    report_parts.append("=" * 50)
    report_parts.append("  >> RESUMO FINAL")
    report_parts.append(f"  Empresas encontradas (Maps): {total_empresas}")
    report_parts.append(f"  Links WhatsApp gerados: {total_whatsapp}")
    report_parts.append(f"  Fontes consultadas: {'Maps' if rodar_maps else ''}{' + Deep Research' if rodar_dr else ''}")
    report_parts.append("=" * 50)

    final_report = "\n".join(report_parts)

    # -- Salvar arquivos --
    if gerar_arquivos:
        try:
            arquivos = _salvar_resultados(objetivo, maps_result, dr_result)
            if arquivos:
                final_report += "\n\n[FILE] Arquivos salvos:\n" + "\n".join(f"  - {a}" for a in arquivos)
        except Exception as e:
            final_report += f"\n\n[WARN]  Erro ao salvar arquivos: {e}"

    _log("Freela Arsenal concluído.")

    return final_report
