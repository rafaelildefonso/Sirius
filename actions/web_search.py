import json
import re
import sys
import threading
from pathlib import Path

from core.cache import search_cache
from core.llm_utils import _get_mode, call_search_for_action
from core.config_loader import get_secret


def _get_api_key() -> str:
    key = get_secret("gemini_api_key", "")
    if not key:
        raise RuntimeError("gemini_api_key not found.")
    return key


def _gemini_search(query: str) -> str:
    cache_key = f"gemini:{query}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    from google import genai

    client   = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    search_cache.set(cache_key, text, ttl=600)
    return text


def _shopping_search(query: str) -> str:
    cache_key = f"shopping:{query}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    from google import genai

    client   = genai.Client(api_key=_get_api_key())
    prompt = (
        f"Search the web for options to buy: '{query}'. "
        "Return a structured list of specific products available for purchase. "
        "For each product, include:\n"
        "- Product name/model\n"
        "- Brand\n"
        "- Price range (in R$ or relevant currency)\n"
        "- Store name and direct link (URL)\n"
        "Focus on actual products and current prices, not generic descriptions."
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    search_cache.set(cache_key, text, ttl=1800)
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    cache_key = f"ddg:{query}:{max_results}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    search_cache.set(cache_key, results, ttl=300)
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    cache_key = f"ddg_news:{query}:{max_results}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] [WARN] DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(query, max_results=max_results)

    search_cache.set(cache_key, results, ttl=300)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] [WARN] Gemini compare failed: {e} - falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison - {aspect.upper()}", "=" * 40]
    for item in items:
        lines.append(f"\n> {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  - {r['snippet']}")
    return "\n".join(lines)


def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    cache_key = f"headlines:{n}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Current world news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*', '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    result = (headlines[:n], raw.strip())
    search_cache.set(cache_key, result, ttl=600)
    return result


def _news(query: str) -> str:
    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    result_box  = [None]
    lock        = threading.Lock()
    done_evt    = threading.Event()
    failures    = [0]

    def _store(r: str) -> None:
        if r and len(r) > 60:
            with lock:
                if result_box[0] is None:
                    result_box[0] = r
            done_evt.set()
        else:
            with lock:
                failures[0] += 1
                if failures[0] >= 2:
                    done_evt.set()

    def _try_gemini():
        try:
            _store(_gemini_search(gemini_query))
        except Exception as e:
            print(f"[WebSearch] [WARN] Gemini news failed ({e})")
            _store("")

    def _try_ddg():
        try:
            results = _ddg_news(ddg_query, max_results=8)
            _store(_format_news(ddg_query, results))
        except Exception as e:
            print(f"[WebSearch] [WARN] DDG news failed ({e})")
            _store("")

    threading.Thread(target=_try_gemini, daemon=True).start()
    threading.Thread(target=_try_ddg,    daemon=True).start()

    done_evt.wait(timeout=10.0)
    return result_box[0] or f"No news found for: {query}"


def _research(query: str) -> str:
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        print(f"[WebSearch] [WARN] Research Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        print(f"[WebSearch] [WARN] Price Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] [SEARCH] Query: {query!r}  Mode: {mode}")

    _mode = _get_mode()
    if _mode == "local":
        if mode == "compare" and items:
            parts = []
            for item in items:
                try:
                    results = _ddg_search(f"{item} {aspect}", max_results=3)
                    if results:
                        parts.append(f"> {item}")
                        for r in results[:2]:
                            parts.append(f"  - {r.get('snippet', '')}")
                except Exception:
                    parts.append(f"* {item}: no results")
            return "\n".join(parts) if parts else "No comparison results."

        if mode == "shopping":
            shopping_query = f"{query} buy price"
            results = _ddg_search(shopping_query)
            result  = _format_ddg(shopping_query, results)
            return f"{result}\n\n{call_search_for_action(query)}"

        if mode == "news":
            return _format_news(query, _ddg_news(query))
        if mode == "research":
            results = _ddg_search(query, max_results=10)
            return _format_ddg(query, results)
        if mode == "price":
            results = _ddg_search(f"{query} price buy", max_results=6)
            return _format_ddg(query, results)

        return call_search_for_action(query)

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] [CHART] Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] [OK] Compare done.")
            return result

        if mode == "news":
            print(f"[WebSearch] [NEWS] Fetching news: {query}")
            return _news(query)

        if mode == "research":
            print(f"[WebSearch] [RESEARCH] Deep research: {query}")
            return _research(query)

        if mode == "price":
            print(f"[WebSearch] [PRICE] Price lookup: {query}")
            return _price(query)

        if mode == "shopping":
            print(f"[WebSearch] [SHOPPING] Shopping search: {query}")
            try:
                result = _shopping_search(query)
                print("[WebSearch] [OK] Shopping Gemini OK.")
                return result
            except Exception as e:
                print(f"[WebSearch] [WARN] Shopping Gemini failed ({e}) — trying DDG...")
                shopping_query = f"{query} comprar preço"
                results = _ddg_search(shopping_query)
                result  = _format_ddg(shopping_query, results)
                print(f"[WebSearch] [OK] Shopping DDG: {len(results)} result(s).")
                return result

        print("[WebSearch] [WEB] Trying Gemini...")
        try:
            result = _gemini_search(query)
            print("[WebSearch] [OK] Gemini OK.")
            return result
        except Exception as e:
            print(f"[WebSearch] [WARN] Gemini failed ({e}) — trying DDG...")
            results = _ddg_search(query)
            result  = _format_ddg(query, results)
            print(f"[WebSearch] [OK] DDG: {len(results)} result(s).")
            return result

    except Exception as e:
        print(f"[WebSearch] [FAIL] All backends failed: {e}")
        return f"Search failed, sir: {e}"
