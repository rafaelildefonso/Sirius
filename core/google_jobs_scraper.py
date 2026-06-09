import asyncio
import json
import random
import sys
from pathlib import Path

from core.config_loader import get_secret

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
JOBS_FILE = MEMORY_DIR / "linkedin_jobs.json"


async def scrape_google_jobs_via_serpapi(keywords: str, max_jobs: int = 10) -> list[dict]:
    """Scrapes Google Jobs using SerpAPI engine=google_jobs."""
    serpapi_key = (get_secret("serpapi_key") or "").strip()

    if not serpapi_key:
        print("[Google Jobs Scraper] SerpAPI key not configured, skipping SerpAPI path.")
        return []

    try:
        from serpapi import GoogleSearch

        params = {
            "engine": "google_jobs",
            "q": keywords,
            "hl": "pt-br",
            "gl": "br",
            "api_key": serpapi_key,
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        jobs_results = results.get("jobs_results", [])

        jobs_found = []
        for i, job in enumerate(jobs_results[:max_jobs]):
            title = job.get("title", "").strip()
            company = job.get("company_name", "").strip()
            location = job.get("location", "").strip()
            description = job.get("description", "").strip()
            via = job.get("via", "")
            detected_extensions = job.get("detected_extensions", {})
            posted_at = detected_extensions.get("posted_at", "")
            schedule = detected_extensions.get("schedule_type", "")
            salary = detected_extensions.get("salary", "")

            full_location = location
            if schedule:
                full_location += f" ({schedule})"

            related_links = job.get("related_links", [])
            url = ""
            if isinstance(related_links, list) and len(related_links) > 0:
                link_obj = related_links[0]
                if isinstance(link_obj, dict):
                    url = link_obj.get("link", "")
            if not url:
                apply_options = job.get("apply_options", [])
                if isinstance(apply_options, list) and len(apply_options) > 0:
                    url = apply_options[0].get("link", "")

            jobs_found.append({
                "id": f"google_jobs_{keywords}_{i}_{random.randint(1000, 9999)}",
                "title": title,
                "company": company,
                "location": full_location if full_location else "Não informada",
                "url": url,
                "description": description if description else "Não foi possível carregar a descrição.",
                "source": "google_jobs",
                "posted_at": posted_at,
                "salary": salary,
                "scraped_at": str(asyncio.get_event_loop().time()),
            })
            print(f"[Google Jobs Scraper] Vaga extraída (SerpAPI): {title} na {company}")

        print(f"[Google Jobs Scraper] SerpAPI retornou {len(jobs_found)} vagas.")
        return jobs_found

    except ImportError:
        print("[Google Jobs Scraper] google-search-results not installed.")
        return []
    except Exception as e:
        print(f"[Google Jobs Scraper] Erro no SerpAPI: {e}")
        return []


async def scrape_google_jobs_via_playwright(keywords: str, max_jobs: int = 10) -> list[dict]:
    """Fallback: scrape Google Jobs via Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Google Jobs Scraper] Playwright not installed.")
        return []

    search_url = f"https://www.google.com/search?q={keywords.replace(' ', '+')}+vagas&ibp=htl;jobs"

    print(f"[Google Jobs Scraper] Iniciando busca via Playwright para '{keywords}'...")
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
            await asyncio.sleep(random.uniform(2, 4))

            # Scroll to load job results
            for _ in range(3):
                await page.mouse.wheel(0, 500)
                await asyncio.sleep(random.uniform(1, 2))

            # Try to find job cards in the Google Jobs container
            # Google Jobs uses a specific structure with role="list"
            job_cards = page.locator("div[role='list'] > div[role='listitem']")
            count = await job_cards.count()
            print(f"[Google Jobs Scraper] Playwright: encontrados {count} cards.")

            if count == 0:
                # Fallback selectors
                job_cards = page.locator(".iFjolb, .gws-job-pages__result-container")
                count = await job_cards.count()
                print(f"[Google Jobs Scraper] Playwright: fallback selector encontrou {count} cards.")

            limit = min(count, max_jobs)
            for i in range(limit):
                try:
                    card = job_cards.nth(i)
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                    await card.click()
                    await asyncio.sleep(random.uniform(2, 3.5))

                    # Try extracting job details from the detail panel
                    title_el = page.locator(".tNxQIb, .pMhGee, .BjJfJf").first
                    title = await title_el.inner_text() if await title_el.count() > 0 else ""

                    company_el = page.locator(".N2C0j, .q0v6J, .vNnBgf").first
                    company = await company_el.inner_text() if await company_el.count() > 0 else ""

                    loc_el = page.locator(".sUATkd, .iL8Y9e, .XLC8M").first
                    location = await loc_el.inner_text() if await loc_el.count() > 0 else ""

                    desc_el = page.locator(".YgLqNc, .bOQuI, .wDYxhc").first
                    description = await desc_el.inner_text() if await desc_el.count() > 0 else ""

                    apply_el = page.locator("a[href*='apply']").first
                    url = await apply_el.get_attribute("href") if await apply_el.count() > 0 else ""

                    if not title.strip():
                        continue

                    jobs_found.append({
                        "id": f"google_jobs_pw_{keywords}_{i}_{random.randint(1000, 9999)}",
                        "title": title.strip(),
                        "company": company.strip() if company.strip() else "Não informada",
                        "location": location.strip() if location.strip() else "Não informada",
                        "url": url.strip(),
                        "description": description.strip() if description.strip() else "Não foi possível carregar a descrição.",
                        "source": "google_jobs",
                        "posted_at": "",
                        "salary": "",
                        "scraped_at": str(asyncio.get_event_loop().time()),
                    })
                    print(f"[Google Jobs Scraper] Vaga extraída (Playwright): {title.strip()} na {company.strip()}")
                except Exception as e:
                    print(f"[Google Jobs Scraper] Erro ao extrair card {i}: {e}")
                    continue

            await context.close()
        except Exception as e:
            print(f"[Google Jobs Scraper] Falha geral no Playwright: {e}")

    return jobs_found


async def scrape_google_jobs(keywords: str, max_jobs: int = 10):
    """Scrapes Google Jobs using SerpAPI first, falling back to Playwright."""
    jobs_found = []

    # Try SerpAPI first
    jobs_found = await scrape_google_jobs_via_serpapi(keywords, max_jobs)

    # Fallback to Playwright if SerpAPI returned nothing
    if not jobs_found:
        print("[Google Jobs Scraper] SerpAPI retornou 0, tentando Playwright...")
        jobs_found = await scrape_google_jobs_via_playwright(keywords, max_jobs)

    # Save results
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

        print(f"[Google Jobs Scraper] Salvas {len(new_jobs)} novas vagas no arquivo {JOBS_FILE}")
        return len(new_jobs)

    return 0


if __name__ == "__main__":
    asyncio.run(scrape_google_jobs("Desenvolvedor Python", max_jobs=3))
