import asyncio
import json
import random
import sys
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
JOBS_FILE = MEMORY_DIR / "linkedin_jobs.json"


def _load_api_keys():
    try:
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_valid_url(url: str | None) -> bool:
    return bool(url and url.startswith(("http://", "https://")))


_NON_JOB_KEYWORDS = [
    "resultados da web", "pesquisas relacionadas", "info exame",
    "web results", "related searches", "shopping", "notícias", "imagens",
    "videos", "news", "images", "maps", "forums", "sports",
    "people also ask", "perguntas frequentes", "mais resultados",
    "anúncio", "ad ·", "patrocinado",
]


def _is_job_card(title: str, card_text: str) -> bool:
    """Verify extracted text actually represents a job listing."""
    tl = title.lower()
    if any(kw in tl for kw in _NON_JOB_KEYWORDS):
        return False
    if not title.strip():
        return False
    # Must have at least one job indicator in the card text
    lower = card_text.lower()
    for kw in ["remoto", "presencial", "hibrido", "híbrido", "salário",
               "r$", "experiência", "efetivo", "pj", "clt", "tempo integral",
               "meio período", "estágio", "trainee", "júnior", "pleno", "sênior",
               "senior", "candidatar", "apply", "contratação", "vagas",
               "contratando", "candidatura", "inscrição", "empresa"]:
        if kw in lower:
            return True
    return False


async def scrape_google_jobs_via_serpapi(keywords: str, max_jobs: int = 10) -> list[dict]:
    """Scrapes Google Jobs using SerpAPI via direct HTTP request."""
    api_keys = _load_api_keys()
    serpapi_key = api_keys.get("serpapi_key", "").strip()

    if not serpapi_key:
        print("[Google Jobs Scraper] SerpAPI key not configured, skipping.")
        return []

    try:
        import httpx

        params = {
            "engine": "google_jobs",
            "q": keywords,
            "hl": "pt-br",
            "gl": "br",
            "api_key": serpapi_key,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            resp.raise_for_status()
            results = resp.json()

        # Debug SerpAPI response
        print(f"[Google Jobs Scraper] SerpAPI keys: {list(results.keys())}")
        print(f"[Google Jobs Scraper] SerpAPI metadata: {results.get('search_metadata', {})}")
        if "error" in results:
            print(f"[Google Jobs Scraper] SerpAPI error: {results['error']}")

        jobs_results = results.get("jobs_results", [])
        if not jobs_results:
            print(f"[Google Jobs Scraper] SerpAPI 0 jobs. Trying without hl/gl...")
            # Fallback: try without hl/gl
            params2 = {k: v for k, v in params.items() if k not in ("hl", "gl")}
            resp2 = await client.get("https://serpapi.com/search", params=params2)
            if resp2.status_code == 200:
                results2 = resp2.json()
                jobs_results = results2.get("jobs_results", [])
                print(f"[Google Jobs Scraper] SerpAPI retry (no hl/gl): {len(jobs_results)} jobs")
                if jobs_results:
                    results = results2  # use the fallback results
        jobs_found = []

        for i, job in enumerate(jobs_results[:max_jobs]):
            title = (job.get("title") or "").strip()
            if not title:
                continue

            company = (job.get("company_name") or "").strip()
            location = (job.get("location") or "").strip()
            description = (job.get("description") or "").strip()

            detected_extensions = job.get("detected_extensions", {}) or {}

            # Status detection
            status = "active"
            extensions_text = " ".join(
                str(v) for v in detected_extensions.values() if isinstance(v, str)
            ).lower()
            if any(kw in extensions_text for kw in ["expir", "fechada", "closed", "filled", "cancelada", "preenchida"]):
                status = "closed"
            elif any(kw in extensions_text for kw in ["ativa", "active", "new", "nova"]):
                status = "active"

            # Location with schedule
            schedule = detected_extensions.get("schedule_type", "")
            full_location = location
            if schedule:
                full_location += f" ({schedule})"

            # URL extraction: prefer apply_options > related_links
            url = ""
            apply_options = job.get("apply_options", [])
            if isinstance(apply_options, list):
                for opt in apply_options:
                    link = (opt.get("link") or "").strip() if isinstance(opt, dict) else ""
                    if _is_valid_url(link):
                        url = link
                        break

            if not url:
                related_links = job.get("related_links", [])
                if isinstance(related_links, list):
                    for rl in related_links:
                        link = (rl.get("link") or "").strip() if isinstance(rl, dict) else ""
                        if _is_valid_url(link):
                            url = link
                            break

            jobs_found.append({
                "id": f"google_jobs_{keywords}_{i}_{random.randint(1000, 9999)}",
                "title": title,
                "company": company if company else "Não informada",
                "location": full_location if full_location else "Não informada",
                "url": url,
                "description": description[:5000] if description else "Não foi possível carregar a descrição.",
                "source": "google_jobs",
                "status": status,
                "scraped_at": str(asyncio.get_event_loop().time()),
            })
            print(f"[Google Jobs Scraper] Vaga (SerpAPI): {title} na {company} [{status}]")

        print(f"[Google Jobs Scraper] SerpAPI: {len(jobs_found)} vagas")
        return jobs_found

    except ImportError:
        print("[Google Jobs Scraper] httpx not installed, trying requests...")
        return await _serpapi_via_requests(keywords, serpapi_key, max_jobs)
    except Exception as e:
        print(f"[Google Jobs Scraper] Erro SerpAPI: {e}")
        return []


async def _serpapi_via_requests(keywords: str, serpapi_key: str, max_jobs: int) -> list[dict]:
    """Fallback SerpAPI using sync requests."""
    try:
        import requests

        params = {
            "engine": "google_jobs",
            "q": keywords,
            "hl": "pt-br",
            "gl": "br",
            "api_key": serpapi_key,
        }

        resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
        resp.raise_for_status()
        results = resp.json()
        jobs_results = results.get("jobs_results", [])
        jobs_found = []

        for i, job in enumerate(jobs_results[:max_jobs]):
            title = (job.get("title") or "").strip()
            if not title:
                continue

            company = (job.get("company_name") or "").strip()
            location = (job.get("location") or "").strip()
            description = (job.get("description") or "").strip()
            detected_extensions = job.get("detected_extensions", {}) or {}

            status = "active"
            extensions_text = " ".join(str(v) for v in detected_extensions.values() if isinstance(v, str)).lower()
            if any(kw in extensions_text for kw in ["expir", "fechada", "closed", "filled"]):
                status = "closed"

            schedule = detected_extensions.get("schedule_type", "")
            full_location = location
            if schedule:
                full_location += f" ({schedule})"

            url = ""
            apply_options = job.get("apply_options", [])
            if isinstance(apply_options, list):
                for opt in apply_options:
                    link = (opt.get("link") or "").strip() if isinstance(opt, dict) else ""
                    if _is_valid_url(link):
                        url = link
                        break
            if not url:
                related_links = job.get("related_links", [])
                if isinstance(related_links, list):
                    for rl in related_links:
                        link = (rl.get("link") or "").strip() if isinstance(rl, dict) else ""
                        if _is_valid_url(link):
                            url = link
                            break

            jobs_found.append({
                "id": f"google_jobs_{keywords}_{i}_{random.randint(1000, 9999)}",
                "title": title,
                "company": company if company else "Não informada",
                "location": full_location if full_location else "Não informada",
                "url": url,
                "description": description[:5000] if description else "Não foi possível carregar a descrição.",
                "source": "google_jobs",
                "status": status,
                "scraped_at": str(asyncio.get_event_loop().time()),
            })
            print(f"[Google Jobs Scraper] Vaga (requests): {title} na {company} [{status}]")

        print(f"[Google Jobs Scraper] requests: {len(jobs_found)} vagas")
        return jobs_found
    except Exception as e:
        print(f"[Google Jobs Scraper] Erro requests: {e}")
        return []


async def scrape_google_jobs_via_playwright(keywords: str, max_jobs: int = 10) -> list[dict]:
    """Fallback: scrape Google Jobs via Playwright with better selectors and status detection."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Google Jobs Scraper] Playwright not installed.")
        return []

    search_url = f"https://www.google.com/search?q={keywords.replace(' ', '+')}+vagas&ibp=htl;jobs"

    print(f"[Google Jobs Scraper] Playwright iniciando para '{keywords}'...")
    jobs_found = []

    async with async_playwright() as p:
        profile_dir = str(Path.home() / ".sirius_profiles" / "chrome_dedicated_vagas")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--start-maximized",
                ],
                slow_mo=100,
            )

            page = await context.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(3, 5))

            # Scroll many times to load all lazy cards
            for _ in range(10):
                await page.mouse.wheel(0, 600)
                await asyncio.sleep(random.uniform(1.0, 1.8))

            # Primary: Google Jobs panel with role=list
            job_cards = page.locator("div[role='list'] > div[role='listitem']")
            count = await job_cards.count()

            if count == 0:
                job_cards = page.locator(".iFjolb, .gws-job-pages__result-container, div[data-variable]")
                count = await job_cards.count()

            if count == 0:
                # Log debug HTML
                html = await page.content()
                print(f"[Google Jobs Scraper] 0 cards. HTML snippet: {html[:600]}")
                await context.close()
                return []

            limit = min(count, max_jobs, 10)  # Cap at 10 for stability
            print(f"[Google Jobs Scraper] {count} cards, extraindo {limit}...")

            for i in range(limit):
                try:
                    card = job_cards.nth(i)
                    # Scroll card into view
                    try:
                        await card.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        print(f"[Google Jobs Scraper] Card {i} nao visivel, pulando.")
                        continue

                    # ---- Extract from card text BEFORE clicking ----
                    card_text = (await card.inner_text()).strip()

                    # Title from card
                    title = ""
                    t_el = card.locator("div[role='heading'], h3, h2, strong, .job-card-title, [data-title]").first
                    if await t_el.count() > 0:
                        title = (await t_el.inner_text()).strip()

                    if not title:
                        lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                        if lines:
                            title = lines[0]

                    if not title or not _is_job_card(title, card_text):
                        print(f"[Google Jobs Scraper] Card {i} descartado (não é vaga): '{title[:40]}'")
                        continue

                    # Company from card text: usually 2nd line in card
                    company = "Não informada"
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    for line in lines:
                        if line != title and line != lines[0]:
                            # Remove common non-company prefixes
                            cand = re.sub(r'^[·\s•\-|]+', '', line).strip()
                            if cand and len(cand) < 80:
                                company = cand
                                break

                    # Location from card text: usually 3rd line
                    location = "Não informada"
                    for line in lines:
                        loc_kw = ["remoto", "presencial", "hibrido", "híbrido", "são paulo",
                                  "rio de janeiro", "brasil", "belo horizonte", "brasília",
                                  "salvador", "fortaleza", "curitiba", "recife",
                                  "porto alegre", "manaus", "distrito federal"]
                        ll = line.lower()
                        if any(kw in ll for kw in loc_kw):
                            location = line
                            break
                    # If no location found in any line, use generic
                    if location == "Não informada" and len(lines) >= 3:
                        location = lines[2]

                    await asyncio.sleep(random.uniform(0.6, 1.2))
                    await card.click()
                    await asyncio.sleep(random.uniform(2.5, 4.0))

                    # ---- Extract from the detail panel ----

                    # Title (from detail panel, prefer over card)
                    for sel in [".tNxQIb", ".pMhGee", ".BjJfJf", "h2", "h3",
                                "[data-detail-header]", ".job-detail-header"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            t = (await el.inner_text()).strip()
                            if t:
                                title = t
                                break

                    # Company - try multiple selectors
                    for sel in [".nFoFM", ".QjpI0d", ".vNnBgf", ".wHYlDd", ".sWr3j",
                                ".job-company-name", "[data-company]",
                                "div[class*='company']", "span[class*='company']"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            c = (await el.inner_text()).strip()
                            if c and not c.startswith("http") and len(c) < 100:
                                company = c
                                break

                    # Location from detail panel
                    for sel in [".sUATkd", ".XLC8M", ".iL8Y9e", ".r0SIB",
                                "[data-location]", "span[class*='location']"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            l = (await el.inner_text()).strip()
                            if l:
                                location = l
                                break

                    # Description
                    description = ""
                    for sel in [".YgLqNc", ".bOQuI", ".wDYxhc", ".HBvzDb",
                                "[data-description]", "div[class*='description']"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            d = (await el.inner_text()).strip()
                            if d:
                                description = d[:5000]
                                break

                    if not description:
                        description = "Não foi possível carregar a descrição."

                    # URL - try to find apply link
                    url = ""
                    for sel in ["a[href*='apply']", "a[jsname]", "a[href*='job']",
                                "a[href*='linkedin']", "a[href*='glassdoor']",
                                "a[href*='indeed']"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            href = await el.get_attribute("href")
                            if _is_valid_url(href):
                                url = href
                                break

                    # Status detection from detail panel text
                    status = "unknown"
                    panel_text = ""
                    for sel in [".wDYxhc", ".HBvzDb", ".YgLqNc", "[data-description]"]:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            panel_text = (await el.inner_text()).strip()
                            if panel_text:
                                break
                    if panel_text:
                        pl = panel_text.lower()
                        if any(kw in pl for kw in ["expir", "fechada", "closed", "filled", "cancelada"]):
                            status = "closed"
                        elif any(kw in pl for kw in ["candidatar", "apply", "inscrever", "ativa", "active"]):
                            status = "active"

                    jobs_found.append({
                        "id": f"google_jobs_{keywords}_{i}_{random.randint(1000, 9999)}",
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": url,
                        "description": description,
                        "source": "google_jobs",
                        "status": status,
                        "scraped_at": str(asyncio.get_event_loop().time()),
                    })
                    print(f"[Google Jobs Scraper] Vaga (PW): {title} na {company} [{status}]")

                except Exception as e:
                    print(f"[Google Jobs Scraper] Erro card {i}: {e}")
                    continue

            await context.close()
        except Exception as e:
            print(f"[Google Jobs Scraper] Falha Playwright: {e}")

    return jobs_found


async def scrape_google_jobs(keywords: str, max_jobs: int = 10):
    """Scrapes Google Jobs via SerpAPI (async httpx -> sync requests) -> Playwright fallback."""
    jobs_found = await scrape_google_jobs_via_serpapi(keywords, max_jobs)

    if not jobs_found:
        print("[Google Jobs Scraper] SerpAPI vazio, tentando Playwright...")
        jobs_found = await scrape_google_jobs_via_playwright(keywords, max_jobs)

    if jobs_found:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        existing = []
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing_urls = {job.get("url", "") for job in existing if job.get("url")}
        existing_title_company = {
            (job.get("title", ""), job.get("company", "")) for job in existing
        }

        new_jobs = []
        for job in jobs_found:
            is_dup_url = job.get("url") and job["url"] in existing_urls
            is_dup_identity = (job.get("title", ""), job.get("company", "")) in existing_title_company
            if not is_dup_url and not is_dup_identity:
                new_jobs.append(job)

        all_jobs = new_jobs + existing
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=4, ensure_ascii=False)

        print(f"[Google Jobs Scraper] Salvas {len(new_jobs)} novas vagas")
        return len(new_jobs)

    return 0


if __name__ == "__main__":
    asyncio.run(scrape_google_jobs("Desenvolvedor Python", max_jobs=3))
