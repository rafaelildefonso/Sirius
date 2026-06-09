# actions/deep_research.py
import json
import traceback
import concurrent.futures
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from core.cache import search_cache, api_cache
from or_client import client as or_client


from core.config_loader import get_all_config


def _load_api_keys() -> dict:
    return get_all_config()

def _fetch_page_text(url: str, timeout: int = 5) -> str:
    """Fetches the webpage and extracts text."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()

        text = soup.get_text(separator=" ", strip=True)
        # Limit to first 4000 chars to avoid huge token usage
        return text[:4000]
    except Exception as e:
        print(f"[DeepResearch] ⚠️ Could not fetch {url}: {e}")
        return ""


def _is_relevant_domain(url: str) -> bool:
    """Check if domain is relevant for business leads."""
    domain = urlparse(url).netloc.lower()

    # Block social media
    social_domains = [
        "instagram.com", "facebook.com", "linkedin.com", "tiktok.com",
        "youtube.com", "twitter.com", "x.com", "pinterest.com"
    ]
    if any(social in domain for social in social_domains):
        return False

    # Block dictionaries and reference sites
    reference_domains = [
        "dicio.com", "wiktionary.org", "wikipedia.org", "britannica.com",
        "merriam-webster.com", "dictionary.com"
    ]
    if any(ref in domain for ref in reference_domains):
        return False

    # Block news aggregators and large content platforms
    content_domains = [
        "medium.com", "wordpress.com", "blogspot.com", "substack.com"
    ]
    if any(content in domain for content in content_domains):
        return False

    # Block government sites (unless specifically looking for them)
    if domain.endswith(".gov.br") or domain.endswith(".gov"):
        return False

    return True


def _extract_location_info(text: str, region: str) -> dict:
    """Extract location information from text."""
    location_info = {
        "has_address": False,
        "has_phone": False,
        "has_city_mention": False,
        "phone_numbers": [],
        "city_mentions": []
    }

    # Extract Brazilian phone numbers
    phone_pattern = r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}'
    phones = re.findall(phone_pattern, text)
    if phones:
        location_info["has_phone"] = True
        location_info["phone_numbers"] = phones

    # Check for address patterns
    address_keywords = ["rua", "avenida", "av.", "praça", "logradouro", "endereço", "endereco"]
    if any(keyword in text.lower() for keyword in address_keywords):
        location_info["has_address"] = True

    # Check for city/region mentions
    region_lower = region.lower()
    city_names = region_lower.split(",")
    for city in city_names:
        city = city.strip()
        if city and city in text.lower():
            location_info["has_city_mention"] = True
            location_info["city_mentions"].append(city)

    return location_info


def _build_search_queries(target: str, region: str) -> list[str]:
    """Generate multiple search query variations."""
    queries = []

    # Extract key terms from target
    target_lower = target.lower()

    # Basic query
    queries.append(f"{target} em {region}")

    # Query with .com.br filter
    queries.append(f"{target} {region} site:.com.br")

    # Query with contact terms
    contact_terms = ["telefone", "contato", "whatsapp", "email"]
    for term in contact_terms:
        queries.append(f"{target} {region} {term}")

    # Query with business terms
    business_terms = ["empresa", "negócio", "loja", "serviço"]
    for term in business_terms[:2]:  # Limit to avoid too many queries
        queries.append(f"{target} {region} {term}")

    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    return unique_queries[:5]  # Limit to 5 queries

def _search_tavily(query: str, max_results: int = 20) -> list[dict]:
    """Search using Tavily API if configured."""
    cache_key = f"tavily:{query}:{max_results}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    api_keys = _load_api_keys()
    tavily_key = api_keys.get("tavily_api_key", "").strip()

    if not tavily_key:
        print("[DeepResearch] ℹ️ Tavily API key not configured, skipping")
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_key)
        response = client.search(query, max_results=max_results, search_depth="advanced")

        results = []
        for result in response.get("results", []):
            results.append({
                "title": result.get("title", ""),
                "snippet": result.get("content", ""),
                "url": result.get("url", "")
            })

        print(f"[DeepResearch] ✅ Tavily: {len(results)} results")
        search_cache.set(cache_key, results, ttl=3600)
        return results
    except ImportError:
        if tavily_key:
            print("[DeepResearch] ⚠️ tavily-python not installed, skipping Tavily")
        return []
    except Exception as e:
        print(f"[DeepResearch] ⚠️ Tavily search failed: {e}")
        return []


def _search_serpapi(query: str, region: str, max_results: int = 20) -> list[dict]:
    """Search using SerpAPI if configured."""
    cache_key = f"serpapi:{query}:{region}:{max_results}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    api_keys = _load_api_keys()
    serpapi_key = api_keys.get("serpapi_key", "").strip()

    if not serpapi_key:
        print("[DeepResearch] ℹ️ SerpAPI key not configured, skipping")
        return []

    try:
        from serpapi import GoogleSearch

        # Extract country code from region (e.g., "Belo Horizonte, Brazil" -> "br")
        country = "br"  # Default to Brazil

        params = {
            "q": query,
            "hl": "pt-br",
            "gl": country,
            "num": max_results,
            "api_key": serpapi_key
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        organic_results = []
        for result in results.get("organic_results", []):
            organic_results.append({
                "title": result.get("title", ""),
                "snippet": result.get("snippet", ""),
                "url": result.get("link", "")
            })

        print(f"[DeepResearch] ✅ SerpAPI: {len(organic_results)} results")
        search_cache.set(cache_key, organic_results, ttl=3600)
        return organic_results
    except ImportError:
        if serpapi_key:
            print("[DeepResearch] ⚠️ google-search-results not installed, skipping SerpAPI")
        return []
    except Exception as e:
        print(f"[DeepResearch] ⚠️ SerpAPI search failed: {e}")
        return []


def _search_gemini(query: str) -> list[dict]:
    """Search using Gemini with Google Search integration."""
    cache_key = f"gemini_dr:{query}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from google import genai

        api_keys = _load_api_keys()
        gemini_key = api_keys.get("gemini_api_key", "").strip()

        if not gemini_key:
            print("[DeepResearch] ℹ️ Gemini API key not configured, skipping Gemini Search")
            return []

        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Search for: {query}. Return the top 15 results as a JSON list with 'title', 'snippet', and 'url' fields.",
            config={"tools": [{"google_search": {}}]},
        )

        text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                text += part.text

        # Try to parse JSON from response
        try:
            import json
            results = json.loads(text)
            if isinstance(results, list):
                print(f"[DeepResearch] ✅ Gemini: {len(results)} results")
                search_cache.set(cache_key, results, ttl=3600)
                return results
        except:
            pass

        # Fallback: extract URLs from text
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        results = [{"title": "Result", "snippet": text[:200], "url": url} for url in urls[:15]]
        print(f"[DeepResearch] ✅ Gemini (fallback): {len(results)} results")
        search_cache.set(cache_key, results, ttl=3600)
        return results

    except Exception as e:
        print(f"[DeepResearch] ⚠️ Gemini search failed: {e}")
        return []


def _search_ddg(query: str, max_results: int = 15) -> list[dict]:
    """Search using DuckDuckGo."""
    cache_key = f"ddg_dr:{query}:{max_results}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            print("[DeepResearch] ⚠️ DuckDuckGo search library not installed")
            return []

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, region="br-tz"):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", "")
                })
        print(f"[DeepResearch] ✅ DuckDuckGo: {len(results)} results")
        search_cache.set(cache_key, results, ttl=3600)
    except Exception as e:
        print(f"[DeepResearch] ⚠️ DuckDuckGo search failed: {e}")

    return results


def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results based on URL."""
    seen_urls = set()
    unique_results = []

    for result in results:
        url = result.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(result)

    return unique_results


def _evaluate_lead_enhanced(url: str, text: str, snippet: str, competencies: str, target: str, region: str) -> dict:
    """Uses LLM to evaluate the lead with enhanced location verification."""
    cache_key = f"lead_eval:{url}:{hash(competencies)}:{hash(target)}:{hash(region)}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
    location_info = _extract_location_info(text, region)

    prompt = f"""
    You are an AI assistant helping a freelancer find potential clients.
    The freelancer's competencies are: {competencies}
    They are looking for clients in this niche: {target}
    They are looking for clients in this region: {region}

    Here is data from a potential client's website ({url}):
    Website Snippet from Search: {snippet}
    Website Content: {text[:2000]}

    Location analysis:
    - Has phone number: {location_info['has_phone']}
    - Has address: {location_info['has_address']}
    - Mentions region/city: {location_info['has_city_mention']}
    - Phone numbers found: {location_info['phone_numbers']}
    - Cities mentioned: {location_info['city_mentions']}

    Extract the following information about this business and return it as a JSON object:
    - "name": The name of the business (or "Unknown").
    - "phone": Contact phone number found (or "Unknown").
    - "email": Contact email found (or "Unknown").
    - "confidence": A score from 0 to 100 representing how likely they need the freelancer's services. (e.g. if the freelancer is a web developer and the text suggests an outdated or poor online presence, score is high).
    - "location_confidence": A score from 0 to 100 representing how confident you are that this business is actually located in the specified region. Consider phone area codes, addresses, and city mentions.
    - "reason": A short 1-sentence reason why we should contact them.

    IMPORTANT: If there is NO evidence this business is in the specified region (no local phone, no address, no city mention), set location_confidence very low (0-20).

    Return ONLY a valid JSON object.
    """
    try:
        result = or_client.chat_json(prompt, system="Return only valid JSON.")
        if "name" in result:
            result["url"] = url
            api_cache.set(cache_key, result, ttl=3600)
            return result
    except Exception as e:
        print(f"[DeepResearch] ⚠️ LLM evaluation failed for {url}: {e}")
    return None

def deep_research(parameters: dict, player=None) -> str:
    """Main deep research tool with multi-strategy search."""
    params = parameters or {}
    competencies = params.get("competencies", "").strip()
    target = params.get("target_audience", "").strip()
    region = params.get("region", "").strip()

    if not competencies:
        competencies = "freelancer services"
    if not target:
        target = "businesses needing services"
    if not region:
        region = "Brazil"

    if player:
        player.write_log(f"[DeepResearch] Searching {target} in {region}...")

    # Generate multiple search queries
    queries = _build_search_queries(target, region)
    print(f"[DeepResearch] 🔍 Generated {len(queries)} search queries")

    all_results = []

    # Try each search strategy
    for query in queries[:2]:  # Use first 2 queries to avoid too many requests
        print(f"[DeepResearch] 🔍 Query: {query!r}")

        # Try Tavily (if configured)
        tavily_results = _search_tavily(query, max_results=20)
        all_results.extend(tavily_results)

        # Try SerpAPI (if configured)
        serpapi_results = _search_serpapi(query, region, max_results=20)
        all_results.extend(serpapi_results)

        # Try Gemini Search (if configured)
        gemini_results = _search_gemini(query)
        all_results.extend(gemini_results)

        # Try DuckDuckGo (always available)
        ddg_results = _search_ddg(query, max_results=15)
        all_results.extend(ddg_results)

        # If we have enough results, stop
        if len(all_results) >= 30:
            break

    if not all_results:
        return f"No businesses found for {target} in {region}."

    # Filter relevant domains
    filtered_results = [r for r in all_results if _is_relevant_domain(r.get("url", ""))]
    print(f"[DeepResearch] 🎯 Filtered to {len(filtered_results)} relevant domains")

    # Deduplicate results
    unique_results = _deduplicate_results(filtered_results)
    print(f"[DeepResearch] 🔄 Deduplicated to {len(unique_results)} unique results")

    if not unique_results:
        return "Found search results, but none passed the relevance filters."

    print(f"[DeepResearch] ✅ Found {len(unique_results)} potential leads. Analyzing sites...")
    if player:
        player.write_log(f"[DeepResearch] Found {len(unique_results)} leads. Analyzing sites...")

    leads = []

    # Process results in parallel
    def process_result(r):
        url = r["url"]
        snippet = r["snippet"]

        print(f"[DeepResearch] 🌐 Fetching {url}...")
        text = _fetch_page_text(url)
        if not text:
            text = "Could not fetch webpage content. Evaluate based on snippet."

        print(f"[DeepResearch] 🧠 Evaluating {url}...")
        return _evaluate_lead_enhanced(url, text, snippet, competencies, target, region)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_result, r) for r in unique_results[:20]]  # Limit to 20 for performance
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                leads.append(res)

    if not leads:
        return "Found some sites, but could not extract valid business information from them."

    # Sort by combined confidence (confidence + location_confidence)
    leads.sort(key=lambda x: (
        int(x.get("confidence", 0) if str(x.get("confidence", 0)).isdigit() else 0) +
        int(x.get("location_confidence", 0) if str(x.get("location_confidence", 0)).isdigit() else 0)
    ) / 2, reverse=True)

    # Filter out leads with very low location confidence
    leads = [l for l in leads if int(l.get("location_confidence", 0)) > 30]

    if not leads:
        return "Found potential businesses, but none appear to be in the specified region."

    response_lines = [f"Deep Research Results for '{target}' in '{region}':\n"]
    for i, lead in enumerate(leads[:15], 1):  # Return top 15
        name = lead.get("name", "Unknown")
        phone = lead.get("phone", "Unknown")
        email = lead.get("email", "Unknown")
        conf = lead.get("confidence", 0)
        loc_conf = lead.get("location_confidence", 0)
        reason = lead.get("reason", "")
        url = lead.get("url", "")

        response_lines.append(f"{i}. {name} (Confiança: {conf}% | Local: {loc_conf}%)")
        if phone != "Unknown": response_lines.append(f"   📞 {phone}")
        if email != "Unknown": response_lines.append(f"   ✉️ {email}")
        response_lines.append(f"   🌐 {url}")
        response_lines.append(f"   💡 {reason}")
        response_lines.append("")

    final_report = "\n".join(response_lines).strip()
    print("[DeepResearch] ✅ Research complete.")

    if player:
        import os
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop", "deep_research_results.txt")
            with open(desktop, "w", encoding="utf-8") as f:
                f.write(final_report)
            final_report += "\n\n(A report has also been saved to your Desktop)."
        except:
            pass

    return final_report
