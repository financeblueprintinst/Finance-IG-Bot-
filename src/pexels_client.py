"""Pexels API client — fetches portrait-orientation stock images for reel backgrounds.

Requires PEXELS_API_KEY env var (free: https://www.pexels.com/api/).
If no key is available, falls back to a curated list of known-good direct URLs
so the pipeline never fully breaks.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

PEXELS_SEARCH = "https://api.pexels.com/v1/search"


# Hand-picked Pexels photo URLs used if the API is unreachable or key missing.
# All portrait, moody finance/wealth aesthetic.
FALLBACK_URLS = [
    "https://images.pexels.com/photos/6802049/pexels-photo-6802049.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/210607/pexels-photo-210607.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/7054735/pexels-photo-7054735.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/8370752/pexels-photo-8370752.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/6801648/pexels-photo-6801648.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/187041/pexels-photo-187041.jpeg?auto=compress&cs=tinysrgb&w=1200",
]


def search_portrait_images(query: str, count: int = 3) -> list[str]:
    """Return a list of direct Pexels image URLs for the given query.

    Tries the real API first; on any failure, returns curated fallbacks.
    Always returns exactly ``count`` URLs.
    """
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        log.warning("PEXELS_API_KEY not set — using curated fallback images")
        return _pad_with_fallback([], count)

    try:
        r = requests.get(
            PEXELS_SEARCH,
            headers={"Authorization": key},
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": max(count * 2, 6),
                "size": "large",
            },
            timeout=30,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        # Prefer 'large' (typically ~940px wide); good enough as blurred BG
        urls = [p["src"].get("large2x") or p["src"]["large"] for p in photos]
        if not urls:
            log.warning("Pexels returned 0 results for %r — using fallback", query)
            return _pad_with_fallback([], count)
        log.info("Pexels returned %d images for %r", len(urls), query)
        return _pad_with_fallback(urls[:count], count)
    except Exception as e:
        log.warning("Pexels fetch failed (%s) — using fallback", e)
        return _pad_with_fallback([], count)


def _pad_with_fallback(urls: list[str], count: int) -> list[str]:
    """Ensure we always return exactly ``count`` URLs, padding from fallback."""
    out = list(urls)
    i = 0
    while len(out) < count:
        out.append(FALLBACK_URLS[i % len(FALLBACK_URLS)])
        i += 1
    return out[:count]
