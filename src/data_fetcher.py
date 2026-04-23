"""Fetch market data (Stooq CSV) and news (RSS). No paid APIs, no keys."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import StringIO

import feedparser
import pandas as pd
import requests

from config import COMMODITIES, FOREX, INDICES, LARGE_CAPS, NEWS_FEEDS

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Yahoo Finance → Stooq ticker translation
# Stooq is a free Polish data provider. No rate limits, no auth.
# ---------------------------------------------------------------------------
_YAHOO_TO_STOOQ: dict[str, str] = {
    # Indices
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^DJI":  "^dji",
    "^GDAXI": "^dax",
    "^FTSE": "^ukx",
    # Commodities (continuous futures)
    "GC=F": "gc.f",
    "SI=F": "si.f",
    "CL=F": "cl.f",
    "BZ=F": "b.f",
    "NG=F": "ng.f",
    # Forex
    "EURUSD=X": "eurusd",
    "GBPUSD=X": "gbpusd",
    "USDJPY=X": "usdjpy",
    "USDCHF=X": "usdchf",
}


def _to_stooq(yahoo_ticker: str) -> str:
    """Translate Yahoo Finance ticker to Stooq symbol.

    For US equities without an explicit mapping we default to `<ticker>.us`
    in lowercase — this covers our LARGE_CAPS universe.
    """
    if yahoo_ticker in _YAHOO_TO_STOOQ:
        return _YAHOO_TO_STOOQ[yahoo_ticker]
    # BRK-B → brk-b.us, AAPL → aapl.us
    return f"{yahoo_ticker.lower()}.us"


_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
})


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    change_pct: float
    history: pd.Series  # recent closes, for sparkline/line chart


def _fetch_stooq_csv(stooq_symbol: str, timeout: float = 10.0) -> pd.DataFrame | None:
    """Download daily CSV from Stooq. Returns a DataFrame with Date index, or None."""
    url = "https://stooq.com/q/d/l/"
    params = {"s": stooq_symbol, "i": "d"}
    try:
        r = _SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        text = r.text
        # Stooq returns very short body ("No data" or empty) for unknown tickers
        if not text or len(text) < 50 or "No data" in text[:100]:
            log.warning("Stooq: no data for %s", stooq_symbol)
            return None
        df = pd.read_csv(StringIO(text))
        if df.empty or "Close" not in df.columns or "Date" not in df.columns:
            log.warning("Stooq: malformed data for %s", stooq_symbol)
            return None
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        df = df.sort_values("Date").set_index("Date")
        return df
    except Exception as e:
        log.warning("Stooq fetch failed for %s: %s", stooq_symbol, e)
        return None


def _period_to_rows(period: str) -> int:
    """Approx number of trading days to keep for a given Yahoo-style period."""
    mapping = {"5d": 10, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 260}
    return mapping.get(period, 30)


def fetch_quotes(tickers: dict[str, str], period: str = "5d",
                 interval: str = "1d") -> list[Quote]:
    """Fetch quotes from Stooq for each ticker in the dict.

    Unknown/missing tickers are skipped, not fatal.
    """
    rows = _period_to_rows(period)
    quotes: list[Quote] = []
    for yahoo_sym, display_name in tickers.items():
        stooq_sym = _to_stooq(yahoo_sym)
        df = _fetch_stooq_csv(stooq_sym)
        if df is None or len(df) < 2:
            continue
        closes = df["Close"].dropna()
        if len(closes) < 2:
            continue
        # Trim to the requested window from the latest row backwards
        if rows > 0 and len(closes) > rows:
            closes = closes.iloc[-rows:]
        prev = float(closes.iloc[-2])
        last = float(closes.iloc[-1])
        pct = ((last - prev) / prev) * 100 if prev else 0.0
        quotes.append(
            Quote(
                ticker=yahoo_sym,
                name=display_name,
                price=last,
                change_pct=pct,
                history=closes,
            )
        )
        time.sleep(0.15)  # gentle pacing
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
    """Indices with 1-month history for Saturday weekly recap."""
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
