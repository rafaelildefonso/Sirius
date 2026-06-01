# core/linkedin_scraper.py
import asyncio
import json
import os
import random
import sys
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
JOBS_FILE = MEMORY_DIR / "linkedin_jobs.json"
PROFILE_FILE = CONFIG_DIR / "user_profile.json"
API_KEYS_FILE = CONFIG_DIR / "api_keys.json"

# Helper to find real browser profiles (adapted from browser_control.py)
def get_browser_profile_dir(browser: str = "chrome") -> str:
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam = os.environ.get("APPDATA", "")
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
    
    fallback = home / ".sirius_profiles" / f"{browser}_vagas"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)

async def scrape_linkedin_jobs(keywords: str, location: str = "Brasil", max_jobs: int = 10, browser_name: str = "chrome"):
    """Scrapes jobs from LinkedIn using Playwright, simulating human behavior to avoid bans."""
    jobs_found = []
    
    # Construction of LinkedIn search URL (last 24 hours)
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={keywords.replace(' ', '%20')}&location={location.replace(' ', '%20')}&f_TPR=r86400"
    
    print(f"[Linkedin Scraper] Iniciando busca por '{keywords}' em '{location}' usando {browser_name}...")
    
    async with async_playwright() as p:
        # Try dedicated Sirius profile first, fallback to real browser profile
        profile_dir = str(Path.home() / ".sirius_profiles" / f"{browser_name}_dedicated_vagas")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-default-apps",
            "--no-default-browser-check",
            "--start-maximized"
        ]
        
        # Determine executable path if Windows
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
            "headless": False,  # Keep it visible for safety and login
            "args": launch_args,
            "slow_mo": 100,  # Slow down steps to mimic human input
        }
        if executable_path:
            kwargs["executable_path"] = executable_path
            
        browser_type = p.chromium  # default to chromium
        
        try:
            try:
                context = await browser_type.launch_persistent_context(**kwargs)
            except Exception as launch_err:
                print(f"[Linkedin Scraper] ⚠️ Perfil dedicado do Sirius falhou. Tentando perfil real do {browser_name}...")
                fallback_dir = get_browser_profile_dir(browser_name)
                kwargs["user_data_dir"] = fallback_dir
                context = await browser_type.launch_persistent_context(**kwargs)
                
            page = await context.new_page()
            
            # Stealth measures
            await page.set_viewport_size({"width": 1280, "height": 800})
            
            # Go to Search URL
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(2, 4))
            
            # Handle potential Auth wall or overlay
            # If we see a login button/modal, we wait a bit or let the user login
            # LinkedIn logged-out page has different selectors than logged-in
            is_logged_in = False
            try:
                # Check for logged-in indicators
                if await page.locator("a.nav__button-secondary").count() == 0 and await page.locator("#global-nav").count() > 0:
                    is_logged_in = True
            except:
                pass
                
            print(f"[Linkedin Scraper] Logged In Status: {is_logged_in}")
            
            # Close initial auth prompt if logged out
            try:
                close_btn = page.locator("button.modal__dismiss").first
                if await close_btn.is_visible():
                    await close_btn.click()
                    await asyncio.sleep(random.uniform(0.5, 1))
            except:
                pass
                
            # Scroll slowly to load items
            for _ in range(3):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(random.uniform(1.0, 2.0))
                
            # Define selectors based on login state
            if is_logged_in:
                # Logged in LinkedIn job cards
                card_selector = "li.jobs-search-results__list-item"
                title_sel = "a.job-card-list__title"
                company_sel = ".job-card-container__primary-description"
                loc_sel = ".job-card-container__metadata-item"
                desc_container = "div.jobs-description-content__text"
            else:
                # Logged out LinkedIn job cards
                card_selector = "ul.jobs-search__results-list li"
                title_sel = "h3.base-search-card__title"
                company_sel = "h4.base-search-card__subtitle"
                loc_sel = "span.job-search-card__location"
                desc_container = "div.show-more-less-html__markup"
                
            cards = page.locator(card_selector)
            count = await cards.count()
            print(f"[Linkedin Scraper] Encontrados {count} cards de vaga.")
            
            limit = min(count, max_jobs)
            for i in range(limit):
                try:
                    card = cards.nth(i)
                    # Scroll card into view
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                    
                    # Extract basic details
                    title = (await card.locator(title_sel).inner_text()).strip()
                    
                    # Company
                    comp_el = card.locator(company_sel)
                    company = (await comp_el.inner_text()).strip() if await comp_el.count() > 0 else "Empresa não informada"
                    
                    # Location
                    loc_el = card.locator(loc_sel)
                    location_text = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else "Não informada"
                    
                    # URL
                    url_el = card.locator("a").first
                    url = await url_el.get_attribute("href")
                    if url:
                        url = url.split("?")[0]  # clean trackers
                    
                    # Click to load description
                    await card.click()
                    await asyncio.sleep(random.uniform(2.0, 3.5))  # Wait for description to load
                    
                    # Extract description text
                    desc_el = page.locator(desc_container).first
                    description = ""
                    if await desc_el.is_visible():
                        description = await desc_el.inner_text()
                    elif not is_logged_in:
                        # Fallback for logged out details button click
                        show_more = page.locator("button.show-more-less-html__button--more").first
                        if await show_more.is_visible():
                            await show_more.click()
                            await asyncio.sleep(random.uniform(0.5, 1.0))
                            description = await page.locator(desc_container).first.inner_text()
                    
                    if not description:
                        description = "Não foi possível carregar a descrição."
                        
                    jobs_found.append({
                        "id": f"linkedin_{keywords}_{i}_{random.randint(1000, 9999)}",
                        "title": title,
                        "company": company,
                        "location": location_text,
                        "url": url,
                        "description": description.strip(),
                        "scraped_at": str(asyncio.get_event_loop().time())
                    })
                    print(f"[Linkedin Scraper] Vaga extraída: {title} na {company}")
                    
                except Exception as e:
                    print(f"[Linkedin Scraper] Erro ao extrair card {i}: {e}")
                    continue
                    
            await context.close()
            
        except Exception as e:
            print(f"[Linkedin Scraper] Falha geral no scraper: {e}")
            
    # Save results
    if jobs_found:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        # Read existing jobs if file exists to append or merge
        existing = []
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except:
                pass
                
        # Merge by URL to avoid duplicates
        existing_urls = {job["url"] for job in existing if "url" in job}
        new_jobs = [job for job in jobs_found if job["url"] not in existing_urls]
        
        all_jobs = new_jobs + existing
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=4, ensure_ascii=False)
            
        print(f"[Linkedin Scraper] Salvas {len(new_jobs)} novas vagas no arquivo {JOBS_FILE}")
        return len(new_jobs)
        
    return 0

# Test run if invoked directly
if __name__ == "__main__":
    asyncio.run(scrape_linkedin_jobs("Desenvolvedor React", max_jobs=2))
