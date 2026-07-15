# core/linkedin_scraper.py
import asyncio
import json
import os
import random
import sys
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
JOBS_FILE = MEMORY_DIR / "linkedin_jobs.json"


def get_browser_profile_dir(browser: str = "chrome") -> str:
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")

    if sys.platform == "win32":
        m = {
            "chrome": [Path(local) / "Google" / "Chrome" / "User Data"],
            "edge": [Path(local) / "Microsoft" / "Edge" / "User Data"],
            "brave": [Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data"],
        }
        candidates = m.get(browser, [])
        for p in candidates:
            if p.exists():
                return str(p)

    fallback = home / ".sirius_profiles" / f"{browser}_vagas"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)


def _is_valid_url(url: str | None) -> bool:
    return bool(url and url.startswith(("http://", "https://")))


# Multiple selector sets to try (in order of preference)
_SELECTOR_SETS = [
    # Set 0: Current LinkedIn logged-in (unified UI)
    {
        "card": "li.jobs-search-results__list-item",
        "title": "a.job-card-list__title, a.job-card-container__link",
        "company": ".job-card-container__primary-description, .job-card-container__company-name",
        "loc": ".job-card-container__metadata-item",
        "desc": "div.jobs-description-content__text, div.job-details-about-company",
    },
    # Set 1: Current LinkedIn logged-out (unified UI)
    {
        "card": "li[data-entity-urn], li[data-job-id], .job-card-container, div.job-card-container",
        "title": "a.job-card-list__title, strong.job-card-list__title, h3",
        "company": ".job-card-container__company-name, h4",
        "loc": ".job-card-container__metadata-item, span.job-search-card__location",
        "desc": "div.show-more-less-html__markup, div.jobs-description-content__text",
    },
    # Set 2: Legacy LinkedIn logged-out
    {
        "card": "ul.jobs-search__results-list li, li.jobs-search__results-list-item",
        "title": "h3.base-search-card__title",
        "company": "h4.base-search-card__subtitle",
        "loc": "span.job-search-card__location",
        "desc": "div.show-more-less-html__markup, div.jobs-description-content__text",
    },
    # Set 3: Broad fallback — any list item with job-related attributes
    {
        "card": "li[data-entity-urn*='job'], div[data-job-id], article",
        "title": "strong, h3, a[data-anonymize]",
        "company": "span[data-anonymize], h4, .company-name",
        "loc": "span[class*='location'], span[class*='metadata']",
        "desc": "div.show-more-less-html__markup, div[class*='description']",
    },
]


async def _dismiss_overlay(page):
    """Remove modal/sign-in overlays that intercept clicks."""
    try:
        await page.evaluate("""
            document.querySelectorAll('.modal__overlay, .modal__dismiss-overlay, ' +
                '.sign-in-modal, div[aria-modal="true"], ' +
                'div[data-test-modal], .auth-wall, .join-modal').forEach(el => el.remove());
        """)
        await asyncio.sleep(0.2)
    except Exception:
        pass


async def _try_extract_card(page, card, sel_set: dict, idx: int, keywords: str) -> dict | None:
    try:
        await card.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        title_sel = sel_set["title"]
        comp_sel = sel_set["company"]
        loc_sel = sel_set["loc"]
        desc_sel = sel_set["desc"]

        # Title
        title_el = card.locator(title_sel).first
        title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else ""

        if not title:
            return None

        # Company
        comp_el = card.locator(comp_sel).first
        company = (await comp_el.inner_text()).strip() if await comp_el.count() > 0 else "Empresa não informada"

        # Location
        loc_el = card.locator(loc_sel).first
        location_text = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else "Não informada"

        # URL from card
        url_el = card.locator("a").first
        url = await url_el.get_attribute("href")
        if url:
            url = url.split("?")[0]

        if not _is_valid_url(url):
            url = ""

        # --- Click card to load description ---
        description = ""
        clicked = False
        for attempt in range(2):
            await _dismiss_overlay(page)
            try:
                await card.click(force=True, timeout=10000)
                clicked = True
                break
            except Exception as e:
                print(f"[Linkedin Scraper] Card {idx} click attempt {attempt+1} failed: {e}")
                await asyncio.sleep(random.uniform(0.5, 1.0))

        if clicked:
            await asyncio.sleep(random.uniform(2.0, 3.0))
            await _dismiss_overlay(page)

            desc_el = page.locator(desc_sel).first
            if await desc_el.count() > 0 and await desc_el.is_visible():
                description = await desc_el.inner_text()
            else:
                show_more = page.locator("button.show-more-less-html__button--more").first
                if await show_more.count() > 0 and await show_more.is_visible():
                    try:
                        await show_more.click()
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        if await desc_el.count() > 0:
                            description = await desc_el.inner_text()
                    except Exception:
                        pass

        if not description or len(description.strip()) < 20:
            description = "Não foi possível carregar a descrição."

        return {
            "id": f"linkedin_{keywords}_{idx}_{random.randint(1000, 9999)}",
            "title": title,
            "company": company,
            "location": location_text,
            "url": url,
            "description": description.strip(),
            "source": "linkedin",
            "status": "unknown",
            "scraped_at": str(asyncio.get_event_loop().time()),
        }
    except Exception as e:
        print(f"[Linkedin Scraper] Erro ao extrair card {idx}: {e}")
        return None


async def scrape_linkedin_jobs(keywords: str, location: str = "Brasil", max_jobs: int = 10, browser_name: str = "chrome"):
    jobs_found = []

    search_url = f"https://www.linkedin.com/jobs/search/?keywords={keywords.replace(' ', '%20')}&location={location.replace(' ', '%20')}&f_TPR=r86400"

    print(f"[Linkedin Scraper] Buscando '{keywords}' em '{location}' usando {browser_name}...")

    async with async_playwright() as p:
        profile_dir = str(Path.home() / ".sirius_profiles" / f"{browser_name}_dedicated_vagas")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-default-apps",
            "--no-default-browser-check",
            "--start-maximized",
        ]

        executable_path = None
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "")
            program_files = os.environ.get("PROGRAMFILES", "")
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")

            common_paths = {
                "chrome": [
                    Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
                    Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
                ],
                "edge": [
                    Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                ],
                "brave": [
                    Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                    Path(program_files) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
                ],
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
                print(f"[Linkedin Scraper] Perfil dedicado falhou. Tentando perfil real...")
                kwargs["user_data_dir"] = get_browser_profile_dir(browser_name)
                context = await browser_type.launch_persistent_context(**kwargs)

            page = await context.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})

            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(2, 4))

            # Try to detect login state
            is_logged_in = False
            try:
                if await page.locator("#global-nav").count() > 0:
                    is_logged_in = True
            except Exception:
                pass

            print(f"[Linkedin Scraper] Logged In: {is_logged_in}")

            # Close auth prompt overlay if present
            await _dismiss_overlay(page)
            for cls in ["button.modal__dismiss", "button[aria-label='Dismiss']",
                        ".sign-in-modal button", "button[data-tracking-control-name='public_jobs_contextual-sign-in-modal_modal_dismiss']"]:
                try:
                    btn = page.locator(cls).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(random.uniform(0.5, 1))
                except Exception:
                    pass

            # Scroll more times to trigger lazy loading
            for _ in range(8):
                await page.mouse.wheel(0, 500)
                await asyncio.sleep(random.uniform(1.0, 1.5))

            # Try each selector set until we find cards
            count = 0
            selected_sel = None
            for sel_set in _SELECTOR_SETS:
                cards = page.locator(sel_set["card"])
                count = await cards.count()
                print(f"[Linkedin Scraper] Selector '{sel_set['card']}' -> {count} cards")
                if count > 0:
                    selected_sel = sel_set
                    break

            if count == 0:
                print(f"[Linkedin Scraper] Nenhum card encontrado. Logando HTML parcial para debug...")
                html_snippet = await page.content()
                print(f"[Linkedin Scraper] HTML snippet (500 chars): {html_snippet[:500]}")
                await context.close()
                return 0

            limit = min(count, max_jobs)
            print(f"[Linkedin Scraper] Extraindo até {limit} vagas...")

            for i in range(limit):
                card = cards.nth(i)
                job = await _try_extract_card(page, card, selected_sel, i, keywords)
                if job:
                    jobs_found.append(job)
                    print(f"[Linkedin Scraper] Vaga extraída: {job['title']} na {job['company']}")

            await context.close()

        except Exception as e:
            print(f"[Linkedin Scraper] Falha geral: {e}")

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
        new_jobs = [j for j in jobs_found if j.get("url") not in existing_urls]

        all_jobs = new_jobs + existing
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=4, ensure_ascii=False)

        print(f"[Linkedin Scraper] Salvas {len(new_jobs)} novas vagas")
        return len(new_jobs)

    return 0


if __name__ == "__main__":
    asyncio.run(scrape_linkedin_jobs("Desenvolvedor React", max_jobs=2))
