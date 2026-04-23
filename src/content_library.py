"""Content selection + structured Gemini generation for premium reels.

The old version produced a single plain-text quote. This version produces a
fully-structured ContentItem that matches the 5-scene HTML reel template:

  Scene 1  Hook        — editorial opening headline (serif)
  Scene 2  Beat 1      — concrete fact/number (setup)
  Scene 3  Beat 2      — payoff / twist / consequence
  Scene 4  Takeaway    — one-line lesson (serif)
  Scene 5  Outro       — brand lockup (rendered by template, not generated)

Output is a JSON object from Gemini that maps 1:1 to template placeholders.
Falls back to hand-curated structured content if Gemini is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import dataclass
from datetime import date

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ContentItem:
    category: str           # internal key, e.g. "investor_quotes"
    category_label: str     # label shown in header, e.g. "Wisdom"
    source_text: str        # the original quote or topic seed
    author: str | None      # for investor_quotes; otherwise None

    # Structured content mapped to the HTML template:
    hook_kicker: str
    hook_html: str
    beats: list[dict]       # exactly 2 entries with {"kicker", "text_html"}
    takeaway_html: str
    image_keywords: str     # space-separated keywords for Pexels search


# ---------------------------------------------------------------------------
# Seed material: investor quotes + topical prompts
# ---------------------------------------------------------------------------
INVESTOR_QUOTES: list[tuple[str, str]] = [
    ("Be fearful when others are greedy, and greedy when others are fearful.", "Warren Buffett"),
    ("Price is what you pay. Value is what you get.", "Warren Buffett"),
    ("The stock market is a device for transferring money from the impatient to the patient.", "Warren Buffett"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("Our favorite holding period is forever.", "Warren Buffett"),
    ("It is far better to buy a wonderful company at a fair price than a fair company at a wonderful price.", "Warren Buffett"),
    ("The big money is not in the buying and selling, but in the waiting.", "Charlie Munger"),
    ("Invert, always invert.", "Charlie Munger"),
    ("It's not supposed to be easy. Anyone who finds it easy is stupid.", "Charlie Munger"),
    ("Show me the incentive, and I'll show you the outcome.", "Charlie Munger"),
    ("Don't look for the needle in the haystack. Just buy the haystack.", "John Bogle"),
    ("Time is your friend; impulse is your enemy.", "John Bogle"),
    ("The investor's chief problem — and even his worst enemy — is likely to be himself.", "Benjamin Graham"),
    ("In the short run, the market is a voting machine; in the long run, it is a weighing machine.", "Benjamin Graham"),
    ("The four most dangerous words in investing are 'this time it's different.'", "John Templeton"),
    ("Far more money has been lost by investors preparing for corrections than has been lost in the corrections themselves.", "Peter Lynch"),
    ("Know what you own, and know why you own it.", "Peter Lynch"),
    ("The market can remain irrational longer than you can remain solvent.", "John Maynard Keynes"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("Compound interest is the eighth wonder of the world.", "Albert Einstein"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
]

MINDSET_TOPICS: list[str] = [
    "why most people lose money trying to time the market",
    "the psychology of missing a bull run and what happens next",
    "how compound interest becomes unstoppable after year 20",
    "why luck looks like skill in short time frames",
    "the silent cost of lifestyle inflation",
    "why boredom is the real superpower of long-term investors",
    "how the fear of missing out creates losses at the top of every cycle",
    "why your first 100k is the hardest and everything after accelerates",
    "the difference between being rich and being wealthy",
    "why news is the enemy of returns",
]

HABITS_TOPICS: list[str] = [
    "why automating savings beats willpower every time",
    "the real cost of checking your portfolio daily",
    "tax-advantaged accounts most people underuse",
    "why a boring index fund beats 90% of active managers over 20 years",
    "how paying yourself first rewires your spending",
    "the envelope method, reborn for the digital age",
    "why low-cost beats everything else in fund selection",
    "how dollar-cost averaging removes emotion from investing",
    "why an emergency fund is the highest-ROI 'asset' you'll ever hold",
    "the 72 rule: how long until your money doubles",
]

PSYCHOLOGY_TOPICS: list[str] = [
    "loss aversion: why a loss hurts twice as much as a gain feels good",
    "recency bias: why investors over-weight the last 3 months",
    "anchoring: why we're stuck on the price we bought at",
    "confirmation bias: why you only hear news that agrees with your position",
    "survivor bias: why reading founder success stories misleads you",
    "the dunning-kruger trap in investing",
    "herd behavior: why crowds are usually wrong at the top and bottom",
    "sunk-cost fallacy: why 'waiting to break even' destroys portfolios",
    "overconfidence after a single good year",
    "the pain of watching friends get rich in a bubble",
]

MOTIVATION_TOPICS: list[str] = [
    "starting late is not a death sentence — what you can still do at 40",
    "why the person you become matters more than the returns you earn",
    "consistency over intensity: the real formula for wealth",
    "why discipline is a form of self-respect",
    "how a single decision to save $200/month changes everything at 65",
    "the quiet confidence of someone who lives below their means",
    "why patience is the rarest and most profitable skill",
    "building wealth is not about deprivation — it's about alignment",
    "why your biggest financial enemy is your future self's regret",
    "compound interest applies to skills, not just capital",
]


# Category rotation: investor quotes every other slot, topics interleaved.
CATEGORIES: dict[str, tuple[str, list]] = {
    "investor_quotes": ("Wisdom", INVESTOR_QUOTES),
    "mindset":         ("Mindset", MINDSET_TOPICS),
    "habits":          ("Habits", HABITS_TOPICS),
    "psychology":      ("Psychology", PSYCHOLOGY_TOPICS),
    "motivation":      ("Motivation", MOTIVATION_TOPICS),
}

ROTATION = [
    "investor_quotes",
    "mindset",
    "investor_quotes",
    "habits",
    "investor_quotes",
    "psychology",
    "investor_quotes",
    "motivation",
]


# ---------------------------------------------------------------------------
# Deterministic daily picker
# ---------------------------------------------------------------------------
def _rng_for(today: date) -> random.Random:
    return random.Random(today.toordinal())


def pick_content(today: date) -> ContentItem:
    rng = _rng_for(today)
    category = ROTATION[today.toordinal() % len(ROTATION)]
    category_label, pool = CATEGORIES[category]

    if category == "investor_quotes":
        quote, author = rng.choice(pool)
        source_text = quote
    else:
        source_text = rng.choice(pool)
        author = None

    log.info("Picked category=%s source=%r author=%s", category, source_text, author)

    structured = _generate_structured(source_text, author, category_label)

    return ContentItem(
        category=category,
        category_label=category_label,
        source_text=source_text,
        author=author,
        hook_kicker=structured["hook_kicker"],
        hook_html=structured["hook_html"],
        beats=structured["beats"],
        takeaway_html=structured["takeaway_html"],
        image_keywords=structured["image_keywords"],
    )


# ---------------------------------------------------------------------------
# Gemini structured generation
# ---------------------------------------------------------------------------
GEMINI_PROMPT = """You are a senior content editor for a premium Instagram finance account.
You are writing a 5-scene Reel in the voice of Financial Times / Monocle — editorial, \
serious, grounded. NOT hype. NOT get-rich-quick. NOT emoji-laden.

Category: {category_label}
Source material: {source}

Produce a structured 5-scene reel with these fields:

- hook_kicker: Short uppercase-ready kicker label (max 25 chars). Examples: THE BUFFETT PRINCIPLE, COMPOUND RULE, MARKET PSYCHOLOGY.
- hook_html: Editorial opening headline (max 70 chars). Wrap 1-2 words in <em>...</em> for emphasis. No trailing period. Example: Why <em>Warren Buffett</em> buys when others sell.
- beats: Exactly 2 beats, each with a kicker (max 25 chars, often a year or setting) and text_html (max 120 chars, one concrete sentence with a fact/number/event). Wrap big numbers in <span class='big'>$5B</span> (max one per beat). Wrap 1-2 key words in <span class='highlight'>word</span>.
- takeaway_html: One-line lesson (max 80 chars). Wrap 2-3 meaningful words in <em>...</em>. No emojis. Example: Fear creates <em>bargains</em>. Discipline turns them into <em>wealth</em>.
- image_keywords: 3-4 keywords for atmospheric stock photos, space-separated. Prefer moody/urban/trading imagery. Example: stock market trading night.

HARD RULES:
- Every beat must contain a specific, checkable fact (year, number, named person, historical event, or named principle).
- No fluff. Every sentence must add information.
- No motivational-poster cliches (follow your dreams, grind, etc.).
- Allowed HTML tags: <em>, <span class='highlight'>, <span class='big'>. Nothing else.
- Numbers in beats: use concrete values like $5B, $10K, 7%, 20 years.
- Use straight ASCII quotes only. Never use curly quotes. Avoid embedded double-quotes inside strings.
"""


# JSON schema that Gemini must conform to. Enables clean structured output
# and bypasses brittle free-form JSON parsing (which broke on quotes before).
GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_kicker": {"type": "string"},
        "hook_html": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kicker": {"type": "string"},
                    "text_html": {"type": "string"},
                },
                "required": ["kicker", "text_html"],
            },
        },
        "takeaway_html": {"type": "string"},
        "image_keywords": {"type": "string"},
    },
    "required": ["hook_kicker", "hook_html", "beats", "takeaway_html", "image_keywords"],
}


def _generate_structured(source: str, author: str | None, category_label: str) -> dict:
    """Call Gemini to produce the 5-scene structure. Fall back on any error.

    Uses Gemini's structured-output mode (response_mime_type=application/json
    with response_schema) to guarantee valid JSON. Retries up to 3 times on
    transient failures before giving up and falling back.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("No GEMINI_API_KEY — using fallback structured content")
        return _fallback_structured(source, author, category_label)

    try:
        import google.generativeai as genai
    except Exception as e:
        log.warning("google-generativeai import failed (%s) - falling back", e)
        return _fallback_structured(source, author, category_label)

    genai.configure(api_key=api_key)
    source_with_author = f"{source} - {author}" if author else source
    prompt = GEMINI_PROMPT.format(category_label=category_label, source=source_with_author)

    generation_config = {
        "temperature": 0.75,
        "max_output_tokens": 1200,
        "response_mime_type": "application/json",
        "response_schema": GEMINI_SCHEMA,
    }

    last_err: Exception | None = None
    last_text: str = ""
    # Try multiple models in case one is unavailable in the current project.
    for model_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        for attempt in range(1, 3):  # 2 attempts per model
            try:
                model = genai.GenerativeModel(model_name)
                resp = model.generate_content(prompt, generation_config=generation_config)
                text = (resp.text or "").strip()
                last_text = text

                # Strip accidental markdown fences just in case
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

                data = json.loads(text)

                # Shape validation
                required = {"hook_kicker", "hook_html", "beats", "takeaway_html", "image_keywords"}
                missing = required - data.keys()
                if missing:
                    raise ValueError(f"Gemini output missing keys: {missing}")
                if not isinstance(data["beats"], list) or len(data["beats"]) != 2:
                    raise ValueError(f"beats must be a list of exactly 2 items (got {len(data['beats']) if isinstance(data['beats'], list) else type(data['beats']).__name__})")
                for b in data["beats"]:
                    if "kicker" not in b or "text_html" not in b:
                        raise ValueError("each beat needs 'kicker' and 'text_html'")

                log.info("Gemini (%s) generated structured content on attempt %d", model_name, attempt)
                return data

            except Exception as e:
                last_err = e
                log.info("Gemini attempt %d/%s failed: %s", attempt, model_name, e)
                continue

    log.warning("Gemini structured generation failed after all retries (%s) - falling back", last_err)
    if last_text:
        log.warning("Last raw Gemini response (first 500 chars): %s", last_text[:500])
    return _fallback_structured(source, author, category_label)


def _fallback_structured(source: str, author: str | None, category_label: str) -> dict:
    """Deterministic last-resort output so the pipeline never crashes."""
    if author:
        hook = f"<em>{author}</em>"
        beat1_text = source[:120]
        kicker = author.upper().split()[-1]
        beat1_kicker = f"THE {kicker} PRINCIPLE"
    else:
        words = source.split()
        mid = len(words) // 2
        hook = " ".join(words[:mid])[:70]
        beat1_text = source[:120]
        beat1_kicker = "THE PRINCIPLE"

    return {
        "hook_kicker": category_label.upper(),
        "hook_html": hook,
        "beats": [
            {"kicker": beat1_kicker, "text_html": beat1_text},
            {"kicker": "WHY IT MATTERS",
             "text_html": "Applied consistently, this principle compounds into serious wealth over decades."},
        ],
        "takeaway_html": "<em>Discipline</em> over hype. <em>Time</em> over timing.",
        "image_keywords": "finance stock market charts wealth",
    }


# ---------------------------------------------------------------------------
# Caption builder (Instagram post text)
# ---------------------------------------------------------------------------
HASHTAGS = (
    "#investing #wealthbuilding #financialfreedom #stockmarket #personalfinance "
    "#moneymindset #compound #valueinvesting #financialliteracy #warrenbuffett "
    "#stocks #wealth #passiveincome #moneytips #investmentstrategy"
)


def build_reel_caption(item: ContentItem) -> str:
    """Build the Instagram caption shown under the reel."""
    hook_plain = _strip_html(item.hook_html)
    takeaway_plain = _strip_html(item.takeaway_html)

    parts = [hook_plain, "", takeaway_plain]
    if item.author:
        parts.append("")
        parts.append(f"- {item.author}")
    parts.append("")
    parts.append("Follow @financeblueprintdaily for daily mindset & market insights.")
    parts.append("")
    parts.append(HASHTAGS)
    parts.append("")
    parts.append("Not financial advice. For informational purposes only.")
    return "\n".join(parts)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()
