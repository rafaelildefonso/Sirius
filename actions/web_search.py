#web_search.py
import json
import sys
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


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
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

    # DDG fallback: fetch results per item and merge
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
                    parts.append(f"▸ {item}: no results")
            return "\n".join(parts) if parts else "No comparison results."

        if mode == "shopping":
            shopping_query = f"{query} buy price"
            results = _ddg_search(shopping_query)
            result  = _format_ddg(shopping_query, results)
            return f"{result}\n\n{call_search_for_action(query)}"

        return call_search_for_action(query)

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] [CHART] Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] [OK] Compare done.")
            return result

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