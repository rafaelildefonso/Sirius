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
PROSPECTS_FILE = MEMORY_DIR / "business_prospects.json"

BUSINESS_PROFILE_FILE = CONFIG_DIR / "user_profile_business.json"

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
        f"comércio em {state}",
        f"prestadores de serviço em {state}",
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

                            reviews_count_el = page.locator("button[aria-label*='avaliações']")
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
                                print(f"[Maps Scraper] Extraída: {name} ({category})")

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
