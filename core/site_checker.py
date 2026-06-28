import asyncio
import json
import random
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
PROSPECTS_FILE = MEMORY_DIR / "business_prospects.json"


async def check_site(url: str):
    """Visits a website and returns quality indicators."""
    result = {
        "has_site": bool(url),
        "title": "",
        "meta_description": "",
        "has_viewport": False,
        "has_analytics": False,
        "has_whatsapp": False,
        "load_time_ms": 0,
        "quality": "unknown",
        "error": None
    }

    if not url:
        result["quality"] = "none"
        return result

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = await browser.new_page()
            start = asyncio.get_event_loop().time()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                load_time = (asyncio.get_event_loop().time() - start) * 1000
                result["load_time_ms"] = round(load_time, 0)

                await asyncio.sleep(random.uniform(1, 2))

                title = await page.title()
                result["title"] = (title or "").strip()

                meta_desc = await page.locator("meta[name='description']").get_attribute("content")
                result["meta_description"] = (meta_desc or "").strip()

                viewport = await page.locator("meta[name='viewport']").count()
                result["has_viewport"] = viewport > 0

                ga = await page.locator("script[src*='google-analytics'], script[src*='googletagmanager'], script:has-text('gtag')").count()
                result["has_analytics"] = ga > 0

                wa = await page.locator("a[href*='wa.me'], a[href*='whatsapp'], [class*='whatsapp'], [id*='whatsapp']").count()
                result["has_whatsapp"] = wa > 0

                body_text = await page.locator("body").inner_text() if await page.locator("body").count() > 0 else ""
                content_length = len(body_text.strip())

                if content_length < 100:
                    result["quality"] = "ruim"
                elif not result["has_viewport"]:
                    result["quality"] = "ruim"
                elif result["load_time_ms"] > 5000:
                    result["quality"] = "ruim"
                elif content_length < 500:
                    result["quality"] = "medio"
                elif result["has_analytics"] and result["has_viewport"]:
                    result["quality"] = "bom"
                else:
                    result["quality"] = "medio"

            except Exception as e:
                result["quality"] = "ruim"
                result["error"] = str(e)[:200]

            await browser.close()

    except Exception as e:
        result["quality"] = "ruim"
        result["error"] = str(e)[:200]

    return result


async def check_all_sites():
    """Check websites for all unscored businesses in the prospects file."""
    if not PROSPECTS_FILE.exists():
        print("[Site Checker] Nenhum arquivo de prospecção encontrado.")
        return 0

    try:
        with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
            businesses = json.load(f)
    except Exception as e:
        print(f"[Site Checker] Erro ao ler arquivo: {e}")
        return 0

    unscored = [b for b in businesses if "site_check" not in b]
    if not unscored:
        print("[Site Checker] Todos os sites já foram verificados.")
        return 0

    print(f"[Site Checker] Verificando sites de {len(unscored)} empresas...")

    for biz in unscored:
        url = biz.get("website", "")
        print(f"[Site Checker] Verificando: {biz.get('name')} - {url or 'sem site'}")
        result = await check_site(url)
        biz["site_check"] = result

    with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(businesses, f, indent=4, ensure_ascii=False)

    print(f"[Site Checker] Concluído. {len(unscored)} empresas verificadas.")
    return len(unscored)


if __name__ == "__main__":
    asyncio.run(check_all_sites())
