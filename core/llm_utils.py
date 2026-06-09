"""
core/llm_utils.py — Unified LLM helper for dual-mode operations.
Routes to Gemini (mode=gemini) or Local Ollama (mode=local) based on config.
"""
import base64
import json
import re
from pathlib import Path

from core.cache import config_cache, search_cache, llm_cache
from core.config_loader import get_all_config, get_secret


def _get_config() -> dict:
    cached = config_cache.get("llm_utils_config")
    if cached is not None:
        return cached
    data = get_all_config()
    config_cache.set("llm_utils_config", data, ttl=3600)
    return data


def _get_mode() -> str:
    cfg = _get_config()
    return cfg.get("assistant_mode", "gemini").strip().lower()


def call_llm_for_action(prompt: str, system: str = None) -> str:
    """Call the appropriate LLM based on current mode (gemini or local)."""
    cache_key = f"llm_action:{hash(prompt)}:{hash(system)}"
    cached = llm_cache.get(cache_key)
    if cached is not None:
        return cached
    mode = _get_mode()
    if mode == "local":
        from core.llm_client import call_llm_text
        result = call_llm_text(prompt, system=system)
        llm_cache.set(cache_key, result, ttl=600)
        return result
    cfg = _get_config()
    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("gemini_api_key not found in config.")
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    kwargs = {"model_name": "gemini-2.5-flash"}
    if system:
        kwargs["system_instruction"] = system
    model = genai.GenerativeModel(**kwargs)
    response = model.generate_content(prompt)
    result = response.text.strip()
    llm_cache.set(cache_key, result, ttl=600)
    return result


def call_vision_for_action(prompt: str, image_bytes: bytes, mime_type: str) -> str:
    """Analyze image based on current mode (gemini or local)."""
    image_hash = str(hash(image_bytes[:4096]))
    cache_key = f"vision:{image_hash}:{hash(prompt)}"
    cached = llm_cache.get(cache_key)
    if cached is not None:
        return cached
    mode = _get_mode()
    cfg = _get_config()
    if mode == "local":
        import requests as _req
        url = cfg.get("llm_url", "http://localhost:11434").rstrip("/")
        vision_model = cfg.get("vision_model") or cfg.get("llm_model", "llava")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = _req.post(
            f"{url}/api/chat",
            json={
                "model": vision_model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = (resp.json().get("message", {}).get("content") or "").strip()
        llm_cache.set(cache_key, result, ttl=60)
        return result
    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("gemini_api_key not found in config.")
    from google import genai as genai_client
    from google.genai import types as gtypes
    client = genai_client.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
    )
    result = response.text.strip()
    llm_cache.set(cache_key, result, ttl=60)
    return result


def call_search_for_action(query: str) -> str:
    """Search web based on current mode (gemini or local)."""
    cache_key = f"search_action:{query}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    mode = _get_mode()
    cfg = _get_config()
    if mode == "local":
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=6):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        if not results:
            return f"No results found for: {query}"
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            if r.get("title"):
                lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        raw = "\n".join(lines).strip()
        from core.llm_client import call_llm_text
        system = "You are SIRIUS. Summarize web search results concisely. Be factual."
        prompt = f"User question: {query}\n\nSearch results:\n{raw[:4000]}\n\nAnswer:"
        result = call_llm_text(prompt, system=system)
        search_cache.set(cache_key, result, ttl=300)
        return result
    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("gemini_api_key not found in config.")
    from google import genai as genai_client
    client = genai_client.Client(api_key=api_key)
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
    search_cache.set(cache_key, text, ttl=300)
    return text
