"""Generate English Instagram captions using Google Gemini (free tier)."""
from __future__ import annotations

import logging
import os
import textwrap

log = logging.getLogger(__name__)

DISCLAIMER = "\n\n⚠️ Not financial advice. For educational purposes only."

HASHTAGS = {
    "market_recap": "#stockmarket #finance #investing #sp500 #nasdaq #daytrading #trading",
    "gainers_losers": "#stocks #marketmovers #trading #investing #wallstreet",
    "commodities_forex": "#forex #commodities #gold #oil #eurusd #trading",
    "weekly_recap": "#weeklyrecap #markets #investing #finance #stockmarket",
    "news_digest": "#financenews #markets #economy #wallstreet #investing",
}

FALLBACK_CAPTIONS = {
    "market_recap": (
        "Today's market recap is in. Here's how the major indices closed "
        "the session. Which one are you watching most closely?"
    ),
    "gainers_losers": (
        "The biggest movers of the day. Some names ran higher, others took "
        "a hit — see who made the list."
    ),
    "commodities_forex": (
        "Latest spot prices across commodities and FX. Gold, oil and the "
        "major pairs — where are the trends pointing?"
    ),
    "weekly_recap": (
        "Another week in the books. Here's how the major indices performed "
        "over the last 20 sessions."
    ),
    "news_digest": (
        "The headlines that moved markets in the last 24 hours. Save this "
        "for a quick weekend catch-up."
    ),
}


def _build_prompt(post_type: str, context: str) -> str:
    return textwrap.dedent(f"""
        You write concise, engaging Instagram captions for a daily finance
        content page. Audience: retail investors and finance-curious readers.

        Rules:
        - 2–4 sentences max. No emoji overkill: at most 2 tasteful emojis.
        - English only. Professional but friendly tone.
        - Do NOT invent numbers. Only reference figures present in the context.
        - End with ONE engagement question for the audience.
        - No hashtags in your output (we append them separately).
        - No disclaimer (we append it separately).

        Post type: {post_type}

        Context (live data for today):
        {context}
    """).strip()


def generate_caption(post_type: str, context: str) -> str:
    """Call Gemini; on any failure, fall back to a static caption."""
    api_key = os.getenv("GEMINI_API_KEY")
    body = FALLBACK_CAPTIONS.get(post_type, "Daily market update.")

    if api_key:
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(
                _build_prompt(post_type, context),
                generation_config={"temperature": 0.7, "max_output_tokens": 220},
            )
            text = (resp.text or "").strip()
            if text:
                body = text
        except Exception as e:
            log.warning("Gemini failed, using fallback caption: %s", e)

    tags = HASHTAGS.get(post_type, "")
    return f"{body}{DISCLAIMER}\n\n{tags}".strip()
