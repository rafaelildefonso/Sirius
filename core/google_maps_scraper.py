import asyncio
import csv
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
PROSPECTS_FILE = MEMORY_DIR / "business_prospects.json"
MESSAGES_FILE = MEMORY_DIR / "whatsapp_messages.json"
BUSINESS_PROFILE_FILE = CONFIG_DIR / "user_profile_business.json"

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


def load_business_profile():
    if BUSINESS_PROFILE_FILE.exists():
        try:
            with open(BUSINESS_PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"state": "SP"}


def get_browser_profile_dir(browser: str = "chrome") -> str:
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    system = sys.platform

    if system == "win32":
        m = {
            "chrome":   [Path(local) / "Google" / "Chrome" / "User Data"],
            "edge":     [Path(local) / "Microsoft" / "Edge" / "User Data"],
            "brave":    [Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data"],
        }
        candidates = m.get(browser, [])
        for p in candidates:
            if p.exists():
                return str(p)

    fallback = home / ".sirius_profiles" / f"{browser}_prospeccao"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)


async def scrape_maps_businesses(state: str = "SP", max_results: int = 50, browser_name: str = "chrome"):
    businesses = []
    search_terms = [
        f"empresas em {state}",
        f"estabelecimentos em {state}",
        f"com\u00e9rcio em {state}",
        f"prestadores de servi\u00e7o em {state}",
        f"lojas em {state}",
    ]

    async with async_playwright() as p:
        profile_dir = str(Path.home() / ".sirius_profiles" / f"{browser_name}_dedicated_prospeccao")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-default-apps",
            "--no-default-browser-check",
            "--start-maximized"
        ]

        executable_path = None
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("PROGRAMFILES", "")
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")

            common_paths = {
                "chrome": [
                    Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
                    Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe"
                ],
                "edge": [
                    Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                ],
                "brave": [
                    Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                    Path(program_files) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
                ]
            }
            for path in common_paths.get(browser_name, []):
                if path.exists():
                    executable_path = str(path)
                    break

        kwargs = {
            "user_data_dir": profile_dir,
            "headless": False,
            "args": launch_args,
            "slow_mo": 100,
        }
        if executable_path:
            kwargs["executable_path"] = executable_path

        browser_type = p.chromium

        try:
            try:
                context = await browser_type.launch_persistent_context(**kwargs)
            except Exception:
                print("[Maps Scraper] Perfil dedicado falhou. Tentando perfil real...")
                fallback_dir = get_browser_profile_dir(browser_name)
                kwargs["user_data_dir"] = fallback_dir
                context = await browser_type.launch_persistent_context(**kwargs)

            page = await context.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})

            for term in search_terms:
                if len(businesses) >= max_results:
                    break

                remaining = max_results - len(businesses)
                search_url = f"https://www.google.com/maps/search/{term.replace(' ', '+')}/"
                print(f"[Maps Scraper] Buscando: '{term}'")

                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(random.uniform(3, 5))

                    for attempt in range(3):
                        await page.mouse.wheel(0, 800)
                        await asyncio.sleep(random.uniform(1.5, 2.5))

                    cards_selector = "div[role='article']"
                    cards = page.locator(cards_selector)
                    count = await cards.count()
                    print(f"[Maps Scraper] Encontrados {count} cards para '{term}'")

                    limit = min(count, remaining)
                    for i in range(limit):
                        try:
                            card = cards.nth(i)
                            await card.scroll_into_view_if_needed()
                            await asyncio.sleep(random.uniform(0.5, 1.0))

                            name_el = card.locator(".fontHeadlineSmall")
                            name = ""
                            if await name_el.count() > 0:
                                name = (await name_el.first.inner_text()).strip()

                            if not name:
                                continue

                            type_el = card.locator(".fontBodyMedium > span:first-child")
                            category = ""
                            if await type_el.count() > 0:
                                category = (await type_el.first.inner_text()).strip()

                            rating_el = card.locator("span[role='img']")
                            rating = ""
                            if await rating_el.count() > 0:
                                rating_text = await rating_el.first.get_attribute("aria-label")
                                if rating_text:
                                    rating = rating_text

                            await card.click()
                            await asyncio.sleep(random.uniform(2.0, 3.0))

                            address = ""
                            phone = ""
                            website = ""
                            reviews = ""

                            detail_items = page.locator("button[data-item-id]")
                            dc = await detail_items.count()
                            for di in range(dc):
                                try:
                                    item = detail_items.nth(di)
                                    item_id = await item.get_attribute("data-item-id") or ""

                                    if "address" in item_id:
                                        address = (await item.inner_text()).strip()
                                    elif "phone" in item_id:
                                        phone = (await item.inner_text()).strip()
                                    elif "authority" in item_id:
                                        website = await item.get_attribute("href") or ""
                                except Exception:
                                    pass

                            if not website:
                                try:
                                    web_btn = page.locator("a[data-item-id*='authority']").first
                                    if await web_btn.count() > 0:
                                        website = await web_btn.get_attribute("href") or ""
                                except Exception:
                                    pass

                            reviews_count_el = page.locator("button[aria-label*='avalia\u00e7\u00f5es']")
                            if await reviews_count_el.count() > 0:
                                reviews = (await reviews_count_el.first.inner_text()).strip()

                            url = page.url

                            is_dup = any(b.get("name") == name for b in businesses)
                            if not is_dup:
                                businesses.append({
                                    "id": f"maps_{state}_{i}_{random.randint(1000, 9999)}",
                                    "name": name,
                                    "category": category,
                                    "address": address,
                                    "phone": phone,
                                    "website": website,
                                    "rating": rating,
                                    "reviews": reviews,
                                    "maps_url": url,
                                    "state": state,
                                    "has_website": bool(website),
                                    "scraped_at": str(asyncio.get_event_loop().time())
                                })
                                print(f"[Maps Scraper] Extra\u00edda: {name} ({category})")

                        except Exception as e:
                            print(f"[Maps Scraper] Erro ao extrair card {i}: {e}")
                            continue

                    await page.goto("about:blank")
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"[Maps Scraper] Erro na busca '{term}': {e}")
                    continue

            await context.close()

        except Exception as e:
            print(f"[Maps Scraper] Falha geral: {e}")

    if businesses:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        existing = []
        if PROSPECTS_FILE.exists():
            try:
                with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing_names = {b.get("name") for b in existing if b.get("name")}
        new_biz = [b for b in businesses if b.get("name") not in existing_names]

        all_biz = new_biz + existing
        with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_biz, f, indent=4, ensure_ascii=False)

        print(f"[Maps Scraper] Salvas {len(new_biz)} novas empresas em {PROSPECTS_FILE}")
        return len(new_biz)

    return 0


if __name__ == "__main__":
    asyncio.run(scrape_maps_businesses(state="SP", max_results=5))


def _pausar(min_s=1.5, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


def buscar_segmento(page, segmento, cidade, max_results=30, log_func=None):
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
            tel_el = page.locator('[data-tooltip="Copiar n\u00famero de telefone"], [aria-label*="telefone"], button[data-item-id*="phone"]')
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
            end_el = page.locator('[data-tooltip="Copiar endere\u00e7o"], button[data-item-id*="address"], [aria-label*="Endere\u00e7o"]')
            if end_el.count() > 0:
                endereco = end_el.first.get_attribute("aria-label") or ""
                endereco = endereco.replace("Endere\u00e7o:", "").replace("Address:", "").strip()
        except:
            pass

        return {
            "nome":     nome or empresa["nome"],
            "segmento": empresa["segmento"],
            "telefone": telefone,
            "email":    "",
            "site":     site,
            "tem_site": "sim" if site else "n\u00e3o",
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
            "tem_site": "n\u00e3o",
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
    total = len(links)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("LINKS WHATSAPP \u2014 PROSPEC\u00c7\u00c3O GOOGLE MAPS\n")
        f.write(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        for r in links:
            f.write(f"\U0001f4cd {r['nome']}\n")
            f.write(f"   Segmento : {r['segmento']}\n")
            f.write(f"   Telefone : {r['telefone']}\n")
            f.write(f"   Endere\u00e7o : {r.get('endereco', '')}\n")
            f.write(f"   Link WA  : {r['link_whatsapp']}\n\n")
    return caminho


def scrape_google_maps(segmentos, cidade, max_por_segmento=10, mostrar_navegador=True, log_func=None):
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
                log_func(f"  \u2192 {len(empresas)} empresas encontradas para '{seg}'. Coletando detalhes...")
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
