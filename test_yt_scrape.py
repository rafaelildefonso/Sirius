#!/usr/bin/env python3
"""Test YouTube scraping without opening browser."""
import urllib.request
import re
from urllib.parse import quote

query = 'musica relaxante'
search_url = f'https://www.youtube.com/results?search_query={quote(query)}&sp=EgIQAQ%253D%253D'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9',
}

req = urllib.request.Request(search_url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode('utf-8', errors='ignore')

        # Look for video IDs
        patterns = [
            r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"',
            r'"videoId":"([a-zA-Z0-9_-]{11})"',
            r'/watch\?v=([a-zA-Z0-9_-]{11})',
        ]

        found_ids = []
        for pattern in patterns:
            matches = re.findall(pattern, html)
            found_ids.extend(matches)
            print(f"Pattern '{pattern[:40]}...' found {len(matches)} matches")

        print(f"\nTotal unique IDs: {len(set(found_ids))}")
        unique_ids = list(dict.fromkeys(found_ids))  # Preserve order, remove duplicates
        if unique_ids:
            print(f"First ID: {unique_ids[0]}")
            print(f"Video URL: https://www.youtube.com/watch?v={unique_ids[0]}")
        else:
            print("No video IDs found - YouTube may have changed their HTML structure")
            # Save HTML for debugging
            with open("yt_debug.html", "w", encoding="utf-8") as f:
                f.write(html[:5000])
            print("Saved first 5000 chars to yt_debug.html")
except Exception as e:
    print(f"Error: {e}")
