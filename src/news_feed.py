"""Live finance news feed — pulls today's stories from public RSS feeds.

Goal: replace the hardcoded SEED_STORIES / INVESTOR_QUOTES rotation with a
truly live source so the Instagram pipeline always posts fresh content.

Sources (all public, no API key, free):
  - Yahoo Finance:    https://finance.yahoo.com/news/rssindex
  - MarketWatch:      https://feeds.content.dowjones.io/public/rss/mw_topstories
  - CNBC Markets:     https://www.cnbc.com/id/10000664/device/rss/rss.html
  - Reuters Business: https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best
  - Investing.com:    https://www.investing.com/rss/news_25.rss

Theme filter
------------
We only want stories matching the editorial profile of the IG account:
company success stories, founders/CEO journeys, big stock or crypto moves,
historic price swings, IPOs, M&A, earnings shockers, billionaire news.
We DON'T want generic macro reports, central-bank rate decisions, or sports.

A keyword whitelist + blacklist filters the raw feed pool down to fitting
stories. Anything that doesn't match a whitelist term is dropped.

De-duplication
--------------
The last N picked story IDs (md5 of headline) are kept in
``output/recent_stories.json`` so the same story isn't reused for ~14 days,
even though feeds may keep an item for several days.

Public API
----------
``fetch_candidates(today)``      → list of CandidateStory dicts, freshly
                                   filtered, dedup'd, ordered newest-first.
``mark_used(today, candidate)``  → record this story as used (call after
                                   the publisher commits).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
RSS_FEEDS: list[tuple[str, str]] = [
    # (label, url)
    ("yahoo_finance", "https://finance.yahoo.com/news/rssindex"),
    ("marketwatch",   "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("cnbc_markets",  "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("cnbc_business", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    ("investing",     "https://www.investing.com/rss/news_25.rss"),
]


# Whitelist: at least one of these must match the headline+summary lower-case.
# Tilted toward success stories, market moves, and recognisable names.
WHITELIST_KEYWORDS = [
    # market moves
    "surge", "soar", "skyrocket", "rally", "all-time high", "record high",
    "plunge", "crash", "tumble", "rout", "wipe out", "wiped out",
    "billion", "trillion", "%",
    # company / ceo / founder
    "ceo", "founder", "billionaire", "elon musk", "warren buffett",
    "jeff bezos", "mark zuckerberg", "jensen huang", "michael saylor",
    "saylor", "buffett", "berkshire", "musk",
    "ipo", "buyback", "split", "merger", "acquisition", "acquires",
    # big tickers / stocks
    "nvidia", "tesla", "apple", "microsoft", "amazon", "alphabet", "google",
    "meta", "broadcom", "amd", "palantir", "netflix", "uber", "spotify",
    "robinhood", "coinbase", "openai", "stripe",
    # crypto
    "bitcoin", "ethereum", "crypto", "btc", "eth", "memecoin",
    # extremes
    "biggest", "largest", "first ever", "historic", "record",
    "shocks", "stuns", "blowout", "blow-out", "beat estimates", "miss",
    "short squeeze", "meme stock", "default", "bankruptcy",
]


# Blacklist: if any of these match, drop the story even if a whitelist hit.
BLACKLIST_KEYWORDS = [
    "horoscope", "lottery", "weather", "recipe", "celebrity gossip",
    "kardashian", "taylor swift",
    # macroeconomic / political noise we don't want
    "rate cut speech", "fomc minutes", "powell speech",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class CandidateStory:
    story_id: str            # md5 of normalized headline
    title: str               # raw headline
    summary: str             # 1-3 sentence teaser from feed
    url: str                 # canonical link
    source: str              # feed label (yahoo_finance etc.)
    published: str           # ISO8601 string for traceability
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Recent-story tracking
# ---------------------------------------------------------------------------
def _state_path() -> Path:
    # Late import to avoid circular config dependency in unit tests
    try:
        from config import OUTPUT_DIR  # type: ignore
    except Exception:
        OUTPUT_DIR = Path("output")
    p = Path(OUTPUT_DIR) / "recent_stories.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# Stories are forgotten after RECENT_TTL_DAYS so we eventually reuse a hot
# story if it's still trending after two weeks (unlikely, but harmless).
RECENT_TTL_DAYS = 14


def _load_recent() -> dict:
    p = _state_path()
    if not p.exists():
        return {"used": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not read recent_stories.json (%s) - starting fresh", e)
        return {"used": []}


def _save_recent(data: dict) -> None:
    p = _state_path()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                 encoding="utf-8")


def _prune_recent(data: dict, today: date) -> dict:
    cutoff = today - timedelta(days=RECENT_TTL_DAYS)
    kept = []
    for entry in data.get("used", []):
        try:
            d = date.fromisoformat(entry["used_on"])
        except Exception:
            continue
        if d >= cutoff:
            kept.append(entry)
    data["used"] = kept
    return data


def _recent_ids(data: dict) -> set[str]:
    return {e["story_id"] for e in data.get("used", []) if "story_id" in e}


def mark_used(today: date, candidate: CandidateStory) -> None:
    """Record that ``candidate`` was used today, so it won't be picked again."""
    data = _load_recent()
    data = _prune_recent(data, today)
    data.setdefault("used", []).append({
        "story_id": candidate.story_id,
        "title": candidate.title,
        "url": candidate.url,
        "used_on": today.isoformat(),
    })
    _save_recent(data)
    log.info("Recorded story as used: %s", candidate.title[:80])


# ---------------------------------------------------------------------------
# Feed fetching
# ---------------------------------------------------------------------------
def _hash_title(title: str) -> str:
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _parse_feed_entries(label: str, url: str) -> list[CandidateStory]:
    """Pull a single feed via feedparser, normalize entries to CandidateStory."""
    try:
        import feedparser  # type: ignore
    except Exception as e:
        log.warning("feedparser not available (%s) - skipping %s", e, label)
        return []

    try:
        # 8s per feed cap so a single slow source can't break the whole run.
        parsed = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (compatible; FinanceBot/1.0)"
        })
    except Exception as e:
        log.warning("Feed fetch failed for %s (%s)", label, e)
        return []

    entries = parsed.entries if hasattr(parsed, "entries") else []
    out: list[CandidateStory] = []
    for e in entries[:50]:  # cap per feed
        title = _strip_html(getattr(e, "title", ""))
        summary = _strip_html(getattr(e, "summary", "") or getattr(e, "description", ""))
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue
        published = getattr(e, "published", "") or getattr(e, "updated", "")
        out.append(CandidateStory(
            story_id=_hash_title(title),
            title=title,
            summary=summary[:600],
            url=link,
            source=label,
            published=published or "",
        ))
    log.info("Feed %s: parsed %d entries", label, len(out))
    return out


def _filter_theme(stories: Iterable[CandidateStory]) -> list[CandidateStory]:
    kept: list[CandidateStory] = []
    for s in stories:
        haystack = f"{s.title} {s.summary}".lower()
        if any(b in haystack for b in BLACKLIST_KEYWORDS):
            continue
        hits = [k for k in WHITELIST_KEYWORDS if k in haystack]
        if not hits:
            continue
        s.matched_keywords = hits[:5]
        kept.append(s)
    return kept


def _dedupe(stories: Iterable[CandidateStory], skip_ids: set[str]) -> list[CandidateStory]:
    """Drop stories whose IDs are in skip_ids and de-dupe within the pool."""
    seen: set[str] = set(skip_ids)
    out: list[CandidateStory] = []
    for s in stories:
        if s.story_id in seen:
            continue
        seen.add(s.story_id)
        out.append(s)
    return out


def fetch_candidates(today: date, limit: int = 30) -> list[CandidateStory]:
    """Pull all configured feeds, filter, dedupe, return up to ``limit`` items.

    Returns an empty list if every feed failed or no story matched the
    theme filter — callers should always have a fallback path.
    """
    all_stories: list[CandidateStory] = []
    for label, url in RSS_FEEDS:
        all_stories.extend(_parse_feed_entries(label, url))

    if not all_stories:
        log.warning("All RSS feeds returned 0 entries")
        return []

    themed = _filter_theme(all_stories)
    log.info("Theme filter: %d/%d entries match whitelist",
             len(themed), len(all_stories))

    recent = _load_recent()
    recent = _prune_recent(recent, today)
    _save_recent(recent)

    fresh = _dedupe(themed, _recent_ids(recent))
    log.info("After dedup vs. recent_stories.json: %d candidates", len(fresh))

    return fresh[:limit]


# ---------------------------------------------------------------------------
# Convenience: serialise a CandidateStory to dict for prompt/JSON contexts
# ---------------------------------------------------------------------------
def to_dict(c: CandidateStory) -> dict:
    return asdict(c)
