# core/google_maps_scraper.py
import csv
import json
import os
import random
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
MESSAGES_FILE = MEMORY_DIR / "whatsapp_messages.json"

DEFAULT_MESSAGE = (
    "Olá, {nome}! Tudo bem?\n\n"
    "Sou da Marco Um, agência especializada em criação de sites profissionais. "
    "Notei que {nome} ainda não possui um site e gostaria de apresentar como "
    "podemos ajudar a fortalecer a presença digital de vocês.\n\n"
    "Desenvolvemos sites modernos, responsivos e otimizados para o Google — "
    "ideais para {segmento} em {cidade}.\n\n"
    "Posso enviar um orçamento sem compromisso?"
)

CAMPOS = ["nome", "segmento", "telefone", "email", "site", "tem_site", "endereco", "cidade"]

def _pausar(min_s=1.5, max_s=3.0):
    """Pausa aleatória para parecer humano."""
    time.sleep(random.uniform(min_s, max_s))

def buscar_segmento(page, segmento, cidade, max_results=30, log_func=None):
    """Busca um segmento no Google Maps e retorna lista de empresas."""
    query = f"{segmento} em {cidade}"
    url   = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"

    if log_func:
        log_func(f"Buscando '{segmento}' em {cidade}...")

    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _pausar(2, 3)

    try:
        btn = page.locator('button:has-text("Aceitar tudo"), button:has-text("Accept all")')
        if btn.count() > 0:
            btn.first.click()
            _pausar(1, 2)
    except:
        pass

    resultados = []
    vistos     = set()
    tentativas = 0

    while len(resultados) < max_results and tentativas < 15:
        tentativas += 1
        cards = page.locator('a[href*="/maps/place/"]').all()

        for card in cards:
            try:
                href = card.get_attribute("href") or ""
                if href in vistos or not href:
                    continue
                vistos.add(href)

                nome = card.get_attribute("aria-label") or ""
                if not nome:
                    nome = card.inner_text().split("\n")[0].strip()
                if not nome:
                    continue

                resultados.append({"href": href, "nome": nome, "segmento": segmento})
                if len(resultados) >= max_results:
                    break
            except:
                continue

        if len(resultados) >= max_results:
            break

        painel = page.locator('div[role="feed"]')
        if painel.count() > 0:
            painel.last.evaluate("el => el.scrollBy(0, 800)")
            _pausar(1.5, 2.5)
        else:
            break

    return resultados


def coletar_detalhes(page, empresa, cidade):
    """Abre a página de cada empresa e coleta telefone, site, endereço."""
    try:
        page.goto(empresa["href"], wait_until="domcontentloaded", timeout=20000)
        _pausar(2, 3)

        nome = ""
        try:
            nome = page.locator('h1.DUwDvf, h1[class*="fontHeadlineLarge"]').first.inner_text(timeout=3000).strip()
        except:
            nome = empresa["nome"]

        telefone = ""
        try:
            tel_el = page.locator('[data-tooltip="Copiar número de telefone"], [aria-label*="telefone"], button[data-item-id*="phone"]')
            if tel_el.count() > 0:
                telefone = tel_el.first.get_attribute("aria-label") or ""
                telefone = telefone.replace("Telefone:", "").replace("Phone:", "").strip()
            if not telefone:
                spans = page.locator('span').all()
                for sp in spans:
                    txt = sp.inner_text()
                    if txt.startswith("+55") or (txt.startswith("(") and len(txt) < 20):
                        telefone = txt.strip()
                        break
        except:
            pass

        site = ""
        try:
            site_el = page.locator('a[data-item-id="authority"], a[href*="http"][aria-label*="site"], a[aria-label*="Site"]')
            if site_el.count() > 0:
                site = site_el.first.get_attribute("href") or ""
                if "google.com/maps" in site:
                    site = ""
        except:
            pass

        endereco = ""
        try:
            end_el = page.locator('[data-tooltip="Copiar endereço"], button[data-item-id*="address"], [aria-label*="Endereço"]')
            if end_el.count() > 0:
                endereco = end_el.first.get_attribute("aria-label") or ""
                endereco = endereco.replace("Endereço:", "").replace("Address:", "").strip()
        except:
            pass

        return {
            "nome":     nome or empresa["nome"],
            "segmento": empresa["segmento"],
            "telefone": telefone,
            "email":    "",
            "site":     site,
            "tem_site": "sim" if site else "não",
            "endereco": endereco,
            "cidade":   cidade,
        }

    except Exception as ex:
        return {
            "nome":     empresa["nome"],
            "segmento": empresa["segmento"],
            "telefone": "",
            "email":    "",
            "site":     "",
            "tem_site": "não",
            "endereco": "",
            "cidade":   cidade,
        }


def salvar_csv(linhas, caminho):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(linhas)
    return caminho


def gerar_whatsapp_links(linhas, mensagem_template=None):
    """Gera links de WhatsApp para empresas sem site."""
    if mensagem_template is None:
        mensagem_template = DEFAULT_MESSAGE

    links = []
    for r in linhas:
        if not r["telefone"]:
            continue
        num = "".join(c for c in r["telefone"] if c.isdigit())
        if not num.startswith("55"):
            num = "55" + num
        msg = (
            mensagem_template
            .replace("{nome}",     r["nome"])
            .replace("{segmento}", r["segmento"])
            .replace("{cidade}",   r["cidade"])
            .replace("{telefone}", r["telefone"])
        )
        link = f"https://wa.me/{num}?text={urllib.parse.quote(msg)}"
        links.append({
            "nome": r["nome"],
            "segmento": r["segmento"],
            "telefone": r["telefone"],
            "cidade": r["cidade"],
            "link_whatsapp": link,
        })
    return links


def salvar_whatsapp_messages(links, caminho):
    """Salva mensagens WhatsApp em txt formatado."""
    total = len(links)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("LINKS WHATSAPP — PROSPECÇÃO GOOGLE MAPS\n")
        f.write(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        for r in links:
            f.write(f"[PIN] {r['nome']}\n")
            f.write(f"   Segmento : {r['segmento']}\n")
            f.write(f"   Telefone : {r['telefone']}\n")
            f.write(f"   Endereço : {r.get('endereco', '')}\n")
            f.write(f"   Link WA  : {r['link_whatsapp']}\n\n")
    return caminho


def scrape_google_maps(segmentos, cidade, max_por_segmento=10, mostrar_navegador=True, log_func=None):
    """
    Função principal: varre segmentos no Google Maps e retorna dados estruturados.

    Args:
        segmentos: lista de strings (ex: ["restaurante", "pet shop"])
        cidade: string (ex: "Belo Horizonte")
        max_por_segmento: int
        mostrar_navegador: bool
        log_func: callable(msg) opcional para feedback de progresso

    Returns:
        dict com:
            - todos: lista de dicionários com dados de todas empresas
            - sem_site: lista de empresas sem site
            - whatsapp_links: lista de links de WhatsApp
            - resumo: dict com totais
    """
    todos    = []
    sem_site = []

    if log_func:
        log_func(f"Preparando navegador para buscar {len(segmentos)} segmentos em {cidade}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not mostrar_navegador,
            args=["--lang=pt-BR"]
        )
        context = browser.new_context(
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for idx, seg in enumerate(segmentos, 1):
            if log_func:
                log_func(f"[{idx}/{len(segmentos)}] Buscando '{seg}' no Maps...")
            empresas = buscar_segmento(page, seg, cidade, max_por_segmento, log_func)
            if log_func:
                log_func(f"  -> {len(empresas)} empresas encontradas para '{seg}'. Coletando detalhes...")
            for i, emp in enumerate(empresas, 1):
                if log_func:
                    log_func(f"    [{i}/{len(empresas)}] {emp['nome']}")
                row = coletar_detalhes(page, emp, cidade)
                todos.append(row)
                if not row["site"]:
                    sem_site.append(row)
                _pausar(1, 2)

        browser.close()

    whatsapp_links = gerar_whatsapp_links(sem_site)

    resumo = {
        "total_encontrado": len(todos),
        "com_telefone": sum(1 for r in todos if r["telefone"]),
        "sem_site": len(sem_site),
        "com_site": len(todos) - len(sem_site),
        "whatsapp_gerados": len(whatsapp_links),
    }

    return {
        "todos": todos,
        "sem_site": sem_site,
        "whatsapp_links": whatsapp_links,
        "resumo": resumo,
    }
