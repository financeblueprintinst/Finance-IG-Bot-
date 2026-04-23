"""Content library for Reels: curated investor quotes + topical Gemini content.

Categories rotate deterministically based on the current date. A given date
always produces the same category + topic pick, which makes the render and
publish phases of the workflow reproducible (important because the workflow
runs Python twice — once to render, once to publish).

For AI-generated content (non-quote categories), Gemini is called with a
temperature > 0 so output varies, but we persist the rendered output + caption
to a JSON file so the publish phase uses the exact same text.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date

log = logging.getLogger(__name__)


@dataclass
class ContentItem:
    text: str             # The quote / insight itself (spoken + displayed)
    author: str           # Attributed author, or "" for AI-generated
    category: str         # slug
    category_label: str   # Human display label on the reel


# ---------------------------------------------------------------------------
# Curated investor quotes — real, attributed, short excerpts (fair use).
# ---------------------------------------------------------------------------
INVESTOR_QUOTES: list[tuple[str, str]] = [
    ("The stock market is designed to transfer money from the active to the patient.", "Warren Buffett"),
    ("Price is what you pay. Value is what you get.", "Warren Buffett"),
    ("Be fearful when others are greedy, and greedy when others are fearful.", "Warren Buffett"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("The most important quality for an investor is temperament, not intellect.", "Warren Buffett"),
    ("Our favorite holding period is forever.", "Warren Buffett"),
    ("It's far better to buy a wonderful company at a fair price than a fair company at a wonderful price.", "Warren Buffett"),
    ("The best chance to deploy capital is when things are going down.", "Warren Buffett"),
    ("Someone's sitting in the shade today because someone planted a tree a long time ago.", "Warren Buffett"),
    ("Opportunities come infrequently. When it rains gold, put out the bucket, not the thimble.", "Warren Buffett"),
    ("The big money is not in the buying or selling, but in the waiting.", "Charlie Munger"),
    ("Invert, always invert.", "Charlie Munger"),
    ("Take a simple idea and take it seriously.", "Charlie Munger"),
    ("Knowing what you don't know is more useful than being brilliant.", "Charlie Munger"),
    ("Spend each day trying to be a little wiser than you were when you woke up.", "Charlie Munger"),
    ("A lot of success in life and business comes from knowing what you want to avoid.", "Charlie Munger"),
    ("Don't look for the needle in the haystack. Just buy the haystack.", "John Bogle"),
    ("Time is your friend. Impulse is your enemy.", "John Bogle"),
    ("The two greatest enemies of the equity fund investor are expenses and emotions.", "John Bogle"),
    ("Stay the course. No matter what happens, stick to your program.", "John Bogle"),
    ("The investor's chief problem, and even his worst enemy, is likely to be himself.", "Benjamin Graham"),
    ("In the short run, the market is a voting machine. In the long run, it is a weighing machine.", "Benjamin Graham"),
    ("The intelligent investor is a realist who sells to optimists and buys from pessimists.", "Benjamin Graham"),
    ("Successful investing is about managing risk, not avoiding it.", "Benjamin Graham"),
    ("Know what you own, and know why you own it.", "Peter Lynch"),
    ("The best stock to buy may be the one you already own.", "Peter Lynch"),
    ("The four most dangerous words in investing are: this time it's different.", "Sir John Templeton"),
    ("Bull markets are born on pessimism, grown on skepticism, mature on optimism, and die on euphoria.", "Sir John Templeton"),
    ("The time of maximum pessimism is the best time to buy.", "Sir John Templeton"),
    ("The stock market is filled with individuals who know the price of everything, but the value of nothing.", "Philip Fisher"),
    ("If the job has been correctly done when a common stock is purchased, the time to sell it is almost never.", "Philip Fisher"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("The market can stay irrational longer than you can stay solvent.", "John Maynard Keynes"),
]


# ---------------------------------------------------------------------------
# Topic lists for Gemini-generated categories
# ---------------------------------------------------------------------------
SUCCESS_MINDSET_TOPICS = [
    "the power of delayed gratification in wealth building",
    "why compound interest rewards patience over genius",
    "discipline outperforming motivation over a decade",
    "how boredom builds empires while excitement destroys them",
    "why showing up daily beats rare heroic effort",
    "the mindset shift from consumer to owner",
    "why small consistent wins compound into fortune",
    "the difference between being rich and being wealthy",
    "why your first hundred thousand euros is the hardest",
    "long-term thinking as the ultimate competitive edge",
    "why solitude and focus matter more than networking",
    "the freedom of needing less instead of earning more",
]

FINANCIAL_HABITS_TOPICS = [
    "paying yourself first before any other expense",
    "tracking every euro spent for thirty days",
    "automating investments on payday",
    "reading one financial book per month",
    "reviewing your portfolio quarterly, not daily",
    "setting a specific savings goal with a deadline",
    "calculating your net worth every month",
    "maximizing an employer pension or retirement match first",
    "building a three to six month emergency fund",
    "cutting one recurring subscription every quarter",
    "never financing a depreciating asset",
    "asking 'is this worth my hours of work' before every purchase",
]

MONEY_PSYCHOLOGY_TOPICS = [
    "loss aversion and why we sell winners too early",
    "anchoring bias distorting our sense of fair price",
    "recency bias in market predictions",
    "overconfidence bias in trading decisions",
    "herd mentality at market tops",
    "confirmation bias when researching stocks",
    "sunk cost fallacy in losing positions",
    "the illusion of control in active trading",
    "mental accounting and why a euro is a euro",
    "availability bias from financial news",
    "the endowment effect inflating what we already own",
    "narrative fallacy and seductive market stories",
]

HOPE_MOTIVATION_TOPICS = [
    "starting from zero as a strength, not a weakness",
    "why your financial future is closer than you think",
    "the freedom that comes from consistent saving",
    "how ten years of discipline changes everything",
    "why it is never too late to start investing",
    "the quiet confidence of being debt free",
    "rebuilding after a financial setback",
    "the power of a fully funded emergency fund",
    "small monthly investments becoming life-changing wealth",
    "why frugality is a superpower, not a sacrifice",
    "the calm of having options in your career",
    "what financial independence actually feels like",
]


# ---------------------------------------------------------------------------
# Category rotation — indexed by date ordinal
# ---------------------------------------------------------------------------
CATEGORY_ROTATION = [
    "investor_quotes",
    "success_mindset",
    "investor_quotes",
    "financial_habits",
    "investor_quotes",
    "money_psychology",
    "investor_quotes",
    "hope_motivation",
]

CATEGORY_LABELS = {
    "investor_quotes": "INVESTOR WISDOM",
    "success_mindset": "SUCCESS MINDSET",
    "financial_habits": "FINANCIAL HABIT",
    "money_psychology": "MONEY PSYCHOLOGY",
    "hope_motivation": "MINDSET FUEL",
}

TOPIC_LISTS = {
    "success_mindset": SUCCESS_MINDSET_TOPICS,
    "financial_habits": FINANCIAL_HABITS_TOPICS,
    "money_psychology": MONEY_PSYCHOLOGY_TOPICS,
    "hope_motivation": HOPE_MOTIVATION_TOPICS,
}


# ---------------------------------------------------------------------------
# Gemini prompts per category
# ---------------------------------------------------------------------------
_PROMPTS = {
    "success_mindset": (
        "Write a punchy, thought-provoking 2-3 sentence insight on: {topic}. "
        "Tone: confident, warm, slightly philosophical. Audience: retail "
        "investors and self-improvers. No hashtags, no emojis, no attribution. "
        "Output only the insight itself."
    ),
    "financial_habits": (
        "Write a concrete, actionable 2-3 sentence piece of financial advice "
        "on: {topic}. Tone: direct, practical, no fluff. Audience: everyday "
        "savers building wealth. No hashtags, no emojis. Output only the advice."
    ),
    "money_psychology": (
        "Write a 2-3 sentence insight about the behavioral finance concept: "
        "{topic}. Tone: sharp, slightly contrarian, educational. Audience: "
        "investors who want to understand their own mistakes. No jargon beyond "
        "the concept name, no hashtags, no emojis. Output only the insight."
    ),
    "hope_motivation": (
        "Write 2-3 sentences of grounded, non-cheesy motivation on: {topic}. "
        "Tone: quietly confident, realistic, encouraging without hype. Audience: "
        "people building long-term financial stability. No hashtags, no emojis, "
        "no motivational cliches. Output only the message itself."
    ),
}


# Fallback when Gemini is unavailable / errors out
FALLBACK_CONTENT = {
    "success_mindset": (
        "Wealth is built in the boring years — the ones where nothing exciting "
        "happens, but you keep showing up. Most people quit before the "
        "compounding even starts to matter."
    ),
    "financial_habits": (
        "Pay yourself first. Before rent, before groceries, move a fixed amount "
        "into investments automatically on payday. What you never see, you "
        "never miss."
    ),
    "money_psychology": (
        "Loss aversion makes us sell winners too early and hold losers too long. "
        "The pain of a paper loss feels twice as strong as the pleasure of an "
        "equivalent gain — and it quietly costs us a fortune."
    ),
    "hope_motivation": (
        "Your first hundred thousand is the hardest. After that, compounding "
        "does the heavy lifting. The real milestone isn't the money — it's "
        "proving to yourself that you can stay the course."
    ),
}


def pick_category(today: date) -> str:
    idx = today.toordinal() % len(CATEGORY_ROTATION)
    return CATEGORY_ROTATION[idx]


def _pick_quote(today: date) -> ContentItem:
    idx = today.toordinal() % len(INVESTOR_QUOTES)
    text, author = INVESTOR_QUOTES[idx]
    return ContentItem(text=text, author=author,
                       category="investor_quotes",
                       category_label=CATEGORY_LABELS["investor_quotes"])


def _generate_with_gemini(category: str, topic: str) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = model.generate_content(
            _PROMPTS[category].format(topic=topic),
            generation_config={"temperature": 0.8, "max_output_tokens": 200},
        )
        text = (resp.text or "").strip()
        # Gemini occasionally wraps output in quotes — strip once
        text = text.strip('"').strip("'").strip()
        return text or None
    except Exception as e:
        log.warning("Gemini generation failed for %s: %s", category, e)
        return None


def _pick_generated(category: str, today: date) -> ContentItem:
    topics = TOPIC_LISTS[category]
    idx = today.toordinal() % len(topics)
    topic = topics[idx]
    log.info("Gemini topic for %s: %s", category, topic)

    text = _generate_with_gemini(category, topic)
    if not text:
        text = FALLBACK_CONTENT.get(
            category,
            "Stay the course. Small, consistent action compounds into something extraordinary.",
        )
        log.info("Using fallback text for %s", category)

    return ContentItem(text=text, author="",
                       category=category,
                       category_label=CATEGORY_LABELS[category])


def pick_content(today: date | None = None) -> ContentItem:
    """Pick today's reel content. Deterministic on date + (for AI cats) on Gemini."""
    today = today or date.today()
    category = pick_category(today)
    log.info("Reel category for %s: %s", today.isoformat(), category)
    if category == "investor_quotes":
        return _pick_quote(today)
    return _pick_generated(category, today)


def build_reel_caption(item: ContentItem) -> str:
    """Build the Instagram caption that goes below the reel."""
    body_map = {
        "investor_quotes": (
            f"Timeless wisdom from {item.author}. Save this for when markets get noisy."
            if item.author else
            "Timeless investing wisdom. Save this for when markets get noisy."
        ),
        "success_mindset": "The mindset that builds wealth isn't flashy — it's patient. Save this one.",
        "financial_habits": "Small habit, massive compounding. Try it for thirty days.",
        "money_psychology": "Knowing your biases is the difference between investing and gambling.",
        "hope_motivation": "Your financial future is closer than you think. Keep going.",
    }
    body = body_map.get(item.category, "Daily wisdom from FinanceBlueprint.")

    tags_map = {
        "investor_quotes": "#investing #buffett #munger #stockmarket #valueinvesting #wealth #mindset #finance",
        "success_mindset": "#mindset #success #wealthbuilding #discipline #finance #motivation #entrepreneur",
        "financial_habits": "#financialhabits #personalfinance #moneytips #budgeting #wealthbuilding #savings",
        "money_psychology": "#behavioralfinance #investing #psychology #biases #mindset #money",
        "hope_motivation": "#financialfreedom #motivation #mindset #wealth #success #money #fire",
    }
    tags = tags_map.get(item.category, "#finance #mindset #wealth")

    disclaimer = "\u26A0\uFE0F Not financial advice. For educational purposes only."
    return f"{body}\n\n{disclaimer}\n\n{tags}"
