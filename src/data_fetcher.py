"""Fetch market data (yfinance) and news (RSS). No paid APIs."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import feedparser
import pandas as pd
import yfinance as yf

from config import COMMODITIES, FOREX, INDICES, LARGE_CAPS, NEWS_FEEDS

log = logging.getLogger(__name__)


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    change_pct: float
    history: pd.Series  # recent closes, for sparkline/line chart


def _latest_two_closes(hist: pd.DataFrame) -> tuple[float, float] | None:
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return None
    return float(closes.iloc[-2]), float(closes.iloc[-1])


def fetch_quotes(tickers: dict[str, str], period: str = "5d", interval: str = "1d") -> list[Quote]:
    """Batch-download quotes. Returns latest price + % change vs. previous close."""
    symbols = list(tickers.keys())
    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as e:
        log.error("yfinance batch download failed: %s", e)
        return []

    quotes: list[Quote] = []
    for sym in symbols:
        try:
            sub = data[sym] if len(symbols) > 1 else data
            pair = _latest_two_closes(sub)
            if not pair:
                continue
            prev, last = pair
            pct = ((last - prev) / prev) * 100 if prev else 0.0
            quotes.append(
                Quote(
                    ticker=sym,
                    name=tickers[sym],
                    price=last,
                    change_pct=pct,
                    history=sub["Close"].dropna(),
                )
            )
        except Exception as e:
            log.warning("Skip %s: %s", sym, e)
    return quotes


def fetch_indices() -> list[Quote]:
    return fetch_quotes(INDICES, period="5d")


def fetch_commodities() -> list[Quote]:
    return fetch_quotes(COMMODITIES, period="5d")


def fetch_forex() -> list[Quote]:
    return fetch_quotes(FOREX, period="5d")


def fetch_gainers_losers(top_n: int = 5) -> tuple[list[Quote], list[Quote]]:
    """Return (gainers, losers) from the curated large-cap universe."""
    tickers = {t: t for t in LARGE_CAPS}
    quotes = fetch_quotes(tickers, period="5d")
    quotes.sort(key=lambda q: q.change_pct, reverse=True)
    gainers = quotes[:top_n]
    losers = list(reversed(quotes[-top_n:]))
    return gainers, losers


def fetch_weekly_indices() -> list[Quote]:
    """Indices with a 1-week history for the Saturday weekly recap."""
    return fetch_quotes(INDICES, period="1mo", interval="1d")


@dataclass
class NewsItem:
    title: str
    source: str
    published: datetime
    link: str


def fetch_news(limit: int = 6, hours: int = 24) -> list[NewsItem]:
    """Aggregate latest headlines from finance RSS feeds."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    items: list[NewsItem] = []
    for feed_url in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            source = parsed.feed.get("title", feed_url)
            for entry in parsed.entries[:20]:
                published = None
                for key in ("published_parsed", "updated_parsed"):
                    if entry.get(key):
                        published = datetime(*entry[key][:6])
                        break
                if not published or published < cutoff:
                    continue
                items.append(
                    NewsItem(
                        title=entry.get("title", "").strip(),
                        source=source,
                        published=published,
                        link=entry.get("link", ""),
                    )
                )
        except Exception as e:
            log.warning("News feed failed %s: %s", feed_url, e)

    # Dedup by title prefix; newest first
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for n in sorted(items, key=lambda x: x.published, reverse=True):
        key = n.title[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
        if len(unique) >= limit:
            break
    return unique
