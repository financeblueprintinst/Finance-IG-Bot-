"""Fetch market data (yfinance) and news (RSS). No paid APIs."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import feedparser
import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

from config import COMMODITIES, FOREX, INDICES, LARGE_CAPS, NEWS_FEEDS

log = logging.getLogger(__name__)


def _make_session():
    if _HAS_CURL_CFFI:
        try:
            return curl_requests.Session(impersonate="chrome")
        except Exception as e:
            log.warning("curl_cffi session init failed: %s", e)
    return None


_SESSION = _make_session()


@dataclass
class Quote:
    ticker: str
    name: str
    price: float
    change_pct: float
    history: pd.Series


def _latest_two_closes(hist: pd.DataFrame) -> tuple[float, float] | None:
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return None
    return float(closes.iloc[-2]), float(closes.iloc[-1])


def _download_with_retry(tickers_str: str, period: str, interval: str,
                          retries: int = 3) -> pd.DataFrame | None:
    """yf.download with exponential backoff. yfinance >=0.2.65 uses curl_cffi
    automatically if installed, so we don't pass session explicitly."""
    delay = 2.0
    for attempt in range(retries):
        try:
            data = yf.download(
                tickers=tickers_str,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                threads=False,
                progress=False,
            )
            if data is not None and not data.empty:
                return data
            log.warning("yfinance returned empty data (attempt %d)", attempt + 1)
        except Exception as e:
            log.warning("yfinance download attempt %d failed: %s", attempt + 1, e)
        if attempt < retries - 1:
            log.info("Backing off %.1fs before retry", delay)
            time.sleep(delay)
            delay *= 2.5
    return None


def _fetch_ticker_history(symbol: str, period: str, interval: str) -> pd.DataFrame | None:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval, auto_adjust=True)
        if hist is not None and not hist.empty:
            return hist
    except Exception as e:
        log.warning("Ticker %s fetch failed: %s", symbol, e)
    return None


def fetch_quotes(tickers: dict[str, str], period: str = "5d", interval: str = "1d") -> list[Quote]:
    symbols = list(tickers.keys())
    data = _download_with_retry(" ".join(symbols), period, interval)

    quotes: list[Quote] = []

    if data is not None and not data.empty:
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
        if quotes:
            return quotes

    log.info("Batch fetch produced no quotes, falling back to per-ticker")
    for sym in symbols:
        hist = _fetch_ticker_history(sym, period, interval)
        if hist is None:
            continue
        pair = _latest_two_closes(hist)
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
                history=hist["Close"].dropna(),
            )
        )
        time.sleep(0.4)
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
