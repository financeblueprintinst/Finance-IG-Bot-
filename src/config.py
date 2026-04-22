"""Central config: branding, ticker universes, post-type rotation."""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Branding (tune these to your visual style)
# ---------------------------------------------------------------------------
BRAND_NAME = os.getenv("BRAND_NAME", "Daily Market Pulse")
BRAND_HANDLE = os.getenv("BRAND_HANDLE", "@yourhandle")

# Instagram-optimised portrait size (4:5)
IMG_W, IMG_H = 1080, 1350

COLORS = {
    "bg": "#0B0F14",
    "panel": "#121822",
    "fg": "#E8ECF1",
    "muted": "#8A95A5",
    "up": "#21C27A",
    "down": "#E5484D",
    "accent": "#5B9DF9",
    "grid": "#1F2733",
}

# ---------------------------------------------------------------------------
# Ticker universes
# ---------------------------------------------------------------------------
INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^GDAXI": "DAX",
    "^FTSE": "FTSE 100",
}

COMMODITIES = {
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Crude Oil",
    "BZ=F": "Brent",
    "NG=F": "Natural Gas",
}

FOREX = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF",
}

# Curated large-cap universe for gainers/losers (free, no S&P 500 membership API needed)
LARGE_CAPS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    "BRK-B", "JPM", "V", "MA", "UNH", "HD", "PG", "XOM", "CVX", "LLY",
    "JNJ", "WMT", "ABBV", "KO", "PEP", "COST", "MRK", "BAC", "ADBE",
    "CRM", "NFLX", "DIS", "CSCO", "INTC", "AMD", "ORCL", "TMO", "ABT",
    "ACN", "LIN", "MCD", "NKE", "PFE", "PM", "T", "TXN", "UNP", "UPS",
    "VZ", "WFC", "GS", "MS",
]

# ---------------------------------------------------------------------------
# News RSS feeds (free, no API key)
# ---------------------------------------------------------------------------
NEWS_FEEDS = [
    "https://www.marketwatch.com/rss/topstories",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # Top News
]

# ---------------------------------------------------------------------------
# Post type rotation by weekday (0 = Monday ... 6 = Sunday)
# ---------------------------------------------------------------------------
ROTATION = {
    0: "market_recap",       # Mon
    1: "gainers_losers",     # Tue
    2: "market_recap",       # Wed
    3: "commodities_forex",  # Thu
    4: "market_recap",       # Fri
    5: "weekly_recap",       # Sat
    6: "news_digest",        # Sun
}

# ---------------------------------------------------------------------------
# Secrets / env vars (read at runtime, validated in main)
# ---------------------------------------------------------------------------
REQUIRED_ENV = [
    "IG_ACCESS_TOKEN",       # Long-lived Instagram Graph API token
    "IG_BUSINESS_ACCOUNT_ID",  # Instagram Business Account ID
    "GEMINI_API_KEY",        # Google Gemini free tier
    "GITHUB_REPO",           # e.g. "your-user/finance-ig-bot" for raw image URL
    "GITHUB_REF_NAME",       # branch, usually "main"
]

DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
