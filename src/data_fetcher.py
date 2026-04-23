"""Fetch market data (Yahoo JSON API + Frankfurter + Stooq fallback) and news (RSS).

We avoid the yfinance library entirely because its default HTTP path gets
rate-limited on GitHub Actions runners. Instead we hit Yahoo's public JSON
chart endpoint directly with browser-like headers — far less aggressive
rate limiting. Frankfurter handles forex (free, no key, no limits).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from io import StringIO

import feedparser
import pandas as pd
import requests

from config import COMMODITIES, FOREX, INDICES, LARGE_CAPS, NEWS_FEEDS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session: browser-like UA, persistent cookies
# ---------------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
})


# ---------------------------------------------------------------------------
# Forex pair mapping: Yahoo ticker → (base, quote) for Frankfurter
# ---------------------------------------------------------------------------
_FOREX_PAIRS: dict[str, tuple[str, str]] = {
    "EURUSD=X": ("EUR", "USD"),
    "GBPUSD=X": ("GBP", "USD"),
    "USDJPY=X": ("USD", "JPY"),
    "USDCHF=X": ("USD", "CHF"),
    "USDCAD=X": ("USD", "CAD"),
    "AUDUSD=X": ("AUD", "USD"),
}


# ---------------------------------------------------------------------------
# Yahoo → Stooq fallback translation
# ---------------------------------------------------------------------------
_YAHOO_TO_STOOQ: dict[str, str] = {
    "^GSPC": "^spx", "^IXIC": "^ndq", "^DJI":  "^dji",
    "^GDAXI": "^dax", "^FTSE": "^ukx",
    "GC=F": "gc.f", "SI=F": "si.f", "CL=F": "cl.f",
    "BZ=F": "b.f", "NG=F": "ng.f",
}


def _to_stooq(yahoo_ticker: str) -> str:
    if yahoo_ticker in _YAHOO_TO_STOOQ:
        return _YAHOO_TO_STOOQ[yahoo_ticker]
    return f"{yahoo_ticker.lower()}.us"


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    change_pct: float
    history: pd.Series  # recent closes, for sparkline/line chart


# ---------------------------------------------------------------------------
# Source 1: Yahoo Finance chart JSON API
# ---------------------------------------------------------------------------
def _fetch_yahoo_chart(ticker: str, range_: str = "1mo") -> pd.DataFrame | None:
    """Fetch daily closes from Yahoo Finance's public chart JSON endpoint.

    This hits the same URL that Yahoo's own web charts use. Far more
    permissive than yfinance library's request path.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": range_}
    try:
        r = _SESSION.get(url, params=params, timeout=12)
        if r.status_code == 429:
            log.warning("Yahoo chart: rate limited for %s", ticker)
            return None
        r.raise_for_status()
        j = r.json()
        err = j.get("chart", {}).get("error")
        if err:
            log.warning("Yahoo chart error for %s: %s", ticker, err)
            return None
        result = j.get("chart", {}).get("result") or []
        if not result:
            return None
        r0 = result[0]
        ts = r0.get("timestamp") or []
        quote = (r0.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        if not ts or not closes or len(ts) != len(closes):
            return None
        dates = pd.to_datetime(ts, unit="s").tz_localize(None)
        df = pd.DataFrame({"Close": closes}, index=dates)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        return df
    except Exception as e:
        log.warning("Yahoo chart fetch failed for %s: %s", ticker, e)
        return None


# ---------------------------------------------------------------------------
# Source 2: Frankfurter (forex only, free, no key)
# ---------------------------------------------------------------------------
def _fetch_frankfurter(base: str, quote: str, days: int = 30) -> pd.DataFrame | None:
    """Historical FX rates from Frankfurter. Open source, ECB-backed."""
    end = date.today()
    start = end - timedelta(days=max(days * 2, 14))  # pad for weekends
    url = f"https://api.frankfurter.app/{start.isoformat()}..{end.isoformat()}"
    params = {"from": base, "to": quote}
    try:
        r = _SESSION.get(url, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        rates = j.get("rates") or {}
        if not rates:
            return None
        records = []
        for d, vals in rates.items():
            if quote in vals:
                records.append((pd.to_datetime(d), float(vals[quote])))
        if not records:
            return None
        df = pd.DataFrame(records, columns=["Date", "Close"]).sort_values("Date").set_index("Date")
        return df
    except Exception as e:
        log.warning("Frankfurter fetch failed for %s/%s: %s", base, quote, e)
        return None


# ---------------------------------------------------------------------------
# Source 3: Stooq CSV fallback (for whatever Yahoo misses)
# ---------------------------------------------------------------------------
def _fetch_stooq_csv(stooq_symbol: str) -> pd.DataFrame | None:
    url = "https://stooq.com/q/d/l/"
    params = {"s": stooq_symbol, "i": "d"}
    try:
        r = _SESSION.get(url, params=params, timeout=10)
        r.raise_for_status()
        text = r.text
        if not text or len(text) < 50 or "No data" in text[:100]:
            return None
        # Try comma first, then semicolon; skip bad lines
        for sep in (",", ";"):
            try:
                df = pd.read_csv(StringIO(text), sep=sep, on_bad_lines="skip")
                if "Close" in df.columns and "Date" in df.columns and not df.empty:
                    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                    df = df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
                    if not df.empty:
                        return df
            except Exception:
                continue
        log.warning("Stooq: unparseable response for %s (first 150 chars: %r)",
                    stooq_symbol, text[:150])
        return None
    except Exception as e:
        log.warning("Stooq fetch failed for %s: %s", stooq_symbol, e)
        return None


# ---------------------------------------------------------------------------
# Unified fetcher: try Yahoo → Frankfurter (forex) → Stooq
# ---------------------------------------------------------------------------
def _period_to_rows(period: str) -> int:
    mapping = {"5d": 10, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 260}
    return mapping.get(period, 30)


def _period_to_yahoo_range(period: str) -> str:
    mapping = {"5d": "1mo", "1mo": "3mo", "3mo": "6mo", "6mo": "1y", "1y": "2y"}
    return mapping.get(period, "1mo")


def _fetch_one(yahoo_ticker: str, display_name: str, period: str) -> Quote | None:
    rows = _period_to_rows(period)

    # Forex: prefer Frankfurter
    df = None
    if yahoo_ticker in _FOREX_PAIRS:
        base, quote = _FOREX_PAIRS[yahoo_ticker]
        df = _fetch_frankfurter(base, quote, days=max(rows, 10))

    # Primary: Yahoo JSON chart
    if df is None:
        df = _fetch_yahoo_chart(yahoo_ticker, range_=_period_to_yahoo_range(period))

    # Fallback: Stooq
    if df is None:
        df = _fetch_stooq_csv(_to_stooq(yahoo_ticker))

    if df is None or len(df) < 2:
        return None
    closes = df["Close"].dropna()
    if len(closes) < 2:
        return None
    if rows > 0 and len(closes) > rows:
        closes = closes.iloc[-rows:]
    prev = float(closes.iloc[-2])
    last = float(closes.iloc[-1])
    pct = ((last - prev) / prev) * 100 if prev else 0.0
    return Quote(ticker=yahoo_ticker, name=display_name, price=last,
                 change_pct=pct, history=closes)


def fetch_quotes(tickers: dict[str, str], period: str = "5d",
                 interval: str = "1d") -> list[Quote]:
    quotes: list[Quote] = []
    for yahoo_sym, display_name in tickers.items():
        q = _fetch_one(yahoo_sym, display_name, period)
        if q is not None:
            quotes.append(q)
        time.sleep(0.15)  # gentle pacing
    return quotes


def fetch_indices() -> list[Quote]:
    return fetch_quotes(INDICES, period="5d")


def fetch_commodities() -> list[Quote]:
    return fetch_quotes(COMMODITIES, period="5d")


def fetch_forex() -> list[Quote]:
    return fetch_quotes(FOREX, period="5d")


def fetch_gainers_losers(top_n: int = 5) -> tuple[list[Quote], list[Quote]]:
    tickers = {t: t for t in LARGE_CAPS}
    quotes = fetch_quotes(tickers, period="5d")
    quotes.sort(key=lambda q: q.change_pct, reverse=True)
    gainers = quotes[:top_n]
    losers = list(reversed(quotes[-top_n:]))
    return gainers, losers


def fetch_weekly_indices() -> list[Quote]:
    return fetch_quotes(INDICES, period="1mo", interval="1d")


# ---------------------------------------------------------------------------
# News (unchanged)
# ---------------------------------------------------------------------------
@dataclass
class NewsItem:
    title: str
    source: str
    published: datetime
    link: str


def fetch_news(limit: int = 6, hours: int = 24) -> list[NewsItem]:
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
