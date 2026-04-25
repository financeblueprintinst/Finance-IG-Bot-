"""News-style slideshow content generator.

Two source modes (live-first, fallback to curated):

  1. Live RSS news (preferred): pulls today's biggest finance stories from
     Yahoo Finance / MarketWatch / CNBC / Investing.com, filters by theme
     (success stories, market moves, CEO/founder news, IPOs, M&A), and
     hands the headline + summary to Gemini as the seed.

  2. Curated SEED_STORIES (fallback): 25 hand-picked historic finance
     episodes used only when every RSS feed fails or no story matches the
     theme filter. Ensures the pipeline never produces an empty post.

Each generated story has 5 slides; each slide has:
  - text_html: 100-180 chars of UPPERCASE news copy, with 4-6 key words
               wrapped in <span class='h'>...</span> for cyan highlighting.
  - image_keywords: a 2-3 word Pexels query unique to that slide so every
                    slide has its own full-bleed background.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import dataclass
from datetime import date
from typing import TypedDict

log = logging.getLogger(__name__)


class _Slide(TypedDict):
    text_html: str
    image_keywords: str


class _SlideshowStructure(TypedDict):
    topic_label: str
    slides: list[_Slide]


@dataclass
class SlideshowStory:
    category: str
    category_label: str
    topic_title: str
    seed_text: str
    slides: list[dict]


# ---------------------------------------------------------------------------
# Curated fallback seed stories (used only if live RSS pipeline fails)
# ---------------------------------------------------------------------------
SEED_STORIES: list[dict] = [
    {"category": "silver_2025", "label": "BREAKING", "title": "Silver's Historic 2025 Rally",
     "seed": "Silver surged past its 1980 and 2011 peaks in 2025, hitting a record around $56/oz. Industrial demand from solar panels, EVs and AI chips has collided with a decade-low inventory at COMEX and LBMA, triggering a supply crunch that pushed prices into uncharted territory.",
     "fallback_keywords": ["silver bars stack", "silver mine", "solar panels factory", "silver bullion india", "silver warehouse"]},
    {"category": "gamestop_squeeze", "label": "BREAKING", "title": "The GameStop Short Squeeze",
     "seed": "In January 2021 GameStop stock rocketed from $17 to an intraday peak near $483. A Reddit-driven short squeeze forced hedge funds like Melvin Capital to take billion-dollar losses, Robinhood halted buying, and regulators were dragged before Congress.",
     "fallback_keywords": ["stock market screen red", "trading floor chaos", "wall street bull", "phone trading app", "congressional hearing"]},
    {"category": "bitcoin_rise", "label": "HISTORIC", "title": "Bitcoin: $0 to $100,000",
     "seed": "Bitcoin started worthless in 2009 when programmer Laszlo Hanyecz famously paid 10,000 BTC for two pizzas in 2010. By 2021 it crossed $60K, then $100K in 2024 after spot ETF approvals and institutional adoption from BlackRock and Fidelity.",
     "fallback_keywords": ["bitcoin coin dark", "crypto computer mining", "digital chart screen", "bitcoin atm", "crypto trader office"]},
    {"category": "lehman_2008", "label": "CRASH", "title": "The Lehman Brothers Collapse",
     "seed": "September 15, 2008: Lehman Brothers filed the largest bankruptcy in US history — $691 billion in assets. Subprime mortgage losses wiped out 158 years of history overnight, froze global credit markets, and triggered a crisis that cost 8 million US jobs.",
     "fallback_keywords": ["new york skyline crisis", "stock market crash", "bank building empty", "housing for sale signs", "financial district night"]},
    {"category": "tesla_rise", "label": "HISTORIC", "title": "Tesla: Bankruptcy to $1 Trillion",
     "seed": "In 2008 Tesla was weeks from bankruptcy with $9 million left. Elon Musk put his last $35M into the company. By 2021 Tesla hit a $1 trillion valuation, and early investors who bought at IPO in 2010 saw gains of over 20,000 percent.",
     "fallback_keywords": ["tesla car factory", "electric vehicle charging", "tech startup office", "assembly line robots", "stock chart rising green"]},
    {"category": "nvidia_ai", "label": "BREAKING", "title": "Nvidia: From Gaming to AI King",
     "seed": "Nvidia's GPU business once served gamers. After ChatGPT's launch in late 2022, demand for its H100 and Blackwell AI chips exploded. Revenue tripled in 18 months, and in 2024 Nvidia crossed a $3 trillion market cap, briefly making it the world's most valuable company.",
     "fallback_keywords": ["gpu chip circuit", "ai data center", "server rack lights", "silicon wafer", "microchip close up"]},
    {"category": "black_monday", "label": "CRASH", "title": "Black Monday 1987",
     "seed": "October 19, 1987: the Dow Jones crashed 22.6 percent in a single session — still the largest one-day percentage drop in history. Portfolio insurance and computerized program trading amplified the selling, wiping out $500 billion in global market value in hours.",
     "fallback_keywords": ["stock ticker red", "1980s trading floor", "newspaper headlines crash", "wall street panic", "old computer trading"]},
    {"category": "soros_pound", "label": "LEGENDARY", "title": "Soros Breaks the Bank of England",
     "seed": "On September 16, 1992 — Black Wednesday — George Soros shorted the British pound with leverage of $10 billion. The Bank of England burned through reserves trying to defend the currency, then capitulated. Soros's Quantum Fund banked over $1 billion in a day.",
     "fallback_keywords": ["pound sterling coins", "bank of england building", "currency trading screen", "forex charts green", "london city finance"]},
    {"category": "big_short", "label": "LEGENDARY", "title": "Michael Burry and the Big Short",
     "seed": "In 2005, former doctor Michael Burry spotted that US subprime mortgages were a ticking bomb. He built a $1 billion short position against the housing market via credit default swaps. When the bubble burst in 2008, his fund returned 489 percent.",
     "fallback_keywords": ["housing for sale", "mortgage documents desk", "suburban houses aerial", "wall street analyst screen", "financial report papers"]},
    {"category": "vw_squeeze", "label": "LEGENDARY", "title": "The Volkswagen Infinity Squeeze",
     "seed": "In October 2008, Volkswagen briefly became the world's most valuable company. Porsche had secretly cornered 74 percent of shares. Shorts realized the float was nearly zero, and the price ripped from €200 to over €1,000 in two days — a $200 billion swing.",
     "fallback_keywords": ["volkswagen factory", "german engineering car", "european stock exchange", "porsche showroom", "automotive assembly line"]},
    {"category": "hunt_silver", "label": "HISTORIC", "title": "The Hunt Brothers Silver Corner",
     "seed": "In 1979, Texas oil heirs Nelson and Herbert Hunt accumulated an estimated 200 million ounces of silver — roughly a third of the world's deliverable supply. They drove silver from $6 to $49/oz, until regulators changed margin rules in what became Silver Thursday.",
     "fallback_keywords": ["silver coins pile", "commodities trading floor", "texas oil field", "silver ingots stack", "1980s news headline"]},
    {"category": "ltcm_1998", "label": "CRASH", "title": "The Long-Term Capital Management Blow-Up",
     "seed": "LTCM was run by two Nobel laureates and Wall Street's best quants, leveraged 25-to-1. When Russia defaulted in August 1998, their models broke, and the fund lost $4.6 billion in weeks. The Fed organized a $3.6B bailout to prevent global contagion.",
     "fallback_keywords": ["bond trading desk", "russia moscow skyline", "equation chalkboard math", "federal reserve building", "wall street suits meeting"]},
    {"category": "buffett_start", "label": "LEGENDARY", "title": "How Buffett Built $140 Billion",
     "seed": "Warren Buffett bought his first stock at age 11 — three shares of Cities Service for $38 each. He took over a failing textile mill called Berkshire Hathaway in 1965. Six decades of compounding at roughly 20% per year turned it into a $900 billion conglomerate.",
     "fallback_keywords": ["warren buffett elderly", "annual report book stack", "omaha nebraska city", "classic typewriter letter", "stock certificate vintage"]},
    {"category": "amazon_ipo", "label": "HISTORIC", "title": "Amazon: $18 IPO to $2 Trillion",
     "seed": "On May 15, 1997 Amazon went public at $18 per share with a $438M valuation. Most analysts called it overpriced. After multiple splits, a single IPO share is now worth over $20,000. Amazon crossed a $2 trillion market cap in 2024.",
     "fallback_keywords": ["amazon warehouse boxes", "ecommerce packages", "seattle city skyline", "data center cables", "delivery truck modern"]},
    {"category": "ftx_collapse", "label": "CRASH", "title": "The FTX Implosion",
     "seed": "In November 2022, FTX — the second-largest crypto exchange — collapsed in 10 days. Founder Sam Bankman-Fried, once worth $26 billion and dubbed 'the next Warren Buffett', was exposed for using $8 billion in customer funds. He was sentenced to 25 years.",
     "fallback_keywords": ["bitcoin crypto red", "bahamas beach office", "courtroom justice gavel", "empty trading desk", "crypto exchange screen"]},
    {"category": "archegos_2021", "label": "CRASH", "title": "The Archegos $36 Billion Blow-Up",
     "seed": "In March 2021, family office Archegos quietly built $160 billion in leveraged stock positions via total return swaps. When ViacomCBS fell, margin calls triggered forced liquidation. Credit Suisse lost $5.5B, Nomura $2.9B, and Archegos vaporized in two days.",
     "fallback_keywords": ["stock chart crashing red", "swiss bank zurich", "trading screen loss", "hedge fund office dark", "financial papers falling"]},
    {"category": "livermore_1929", "label": "LEGENDARY", "title": "Jesse Livermore's $100 Million",
     "seed": "Jesse Livermore went short before the 1929 crash and earned an estimated $100 million — over $1.7 billion in today's dollars — in a single month. He went from a shoeshine boy reading ticker tapes to one of the richest men in America by age 52.",
     "fallback_keywords": ["1920s stock ticker", "wall street historic", "newspaper great depression", "old trading floor", "vintage stock certificate"]},
    {"category": "madoff_ponzi", "label": "CRASH", "title": "The Madoff $65 Billion Ponzi",
     "seed": "Bernard Madoff ran the largest Ponzi scheme in history — $64.8 billion in fake profits across 17 years. When the 2008 crisis triggered withdrawals he couldn't meet, he confessed. Madoff was sentenced to 150 years, and thousands of investors lost life savings.",
     "fallback_keywords": ["new york wall street", "courthouse legal documents", "empty office chair", "financial fraud newspaper", "bank vault closed"]},
    {"category": "dotcom_bust", "label": "CRASH", "title": "The Dot-Com Bubble Burst",
     "seed": "The Nasdaq rose from 1,000 to 5,048 between 1995 and March 2000, driven by internet euphoria. Pets.com IPO'd and went bust the same year. By October 2002 the Nasdaq was down 78 percent, wiping out $5 trillion in paper wealth.",
     "fallback_keywords": ["1990s computer screen", "office cubicles empty", "tech startup closed", "silicon valley buildings", "chart crashing red"]},
    {"category": "microstrategy_btc", "label": "HISTORIC", "title": "MicroStrategy's Bitcoin Bet",
     "seed": "In August 2020, Michael Saylor made MicroStrategy the first public company to put its treasury into Bitcoin — $250 million initially. By 2024 MicroStrategy held over 450,000 BTC, and the stock outperformed Nvidia, turning a software company into a BTC proxy.",
     "fallback_keywords": ["bitcoin gold coin", "corporate boardroom meeting", "crypto wallet hardware", "finance executive desk", "treasury documents"]},
    {"category": "gold_ath", "label": "BREAKING", "title": "Gold Breaks $3,000/oz",
     "seed": "Gold crossed $3,000 per ounce for the first time in 2025 after central banks bought a record 1,045 tonnes in 2024. Fears of currency debasement, Middle East tensions and BRICS de-dollarization pushed investors into the oldest safe haven on earth.",
     "fallback_keywords": ["gold bars stacked", "central bank vault", "gold coin macro", "jewelry shop gold", "precious metal mine"]},
    {"category": "barings_leeson", "label": "CRASH", "title": "Nick Leeson Sinks Barings Bank",
     "seed": "In 1995, a single 28-year-old trader named Nick Leeson lost $1.4 billion on unauthorized Nikkei futures bets — more than Barings Bank's entire capital. The 233-year-old bank, which had financed the Louisiana Purchase, collapsed overnight and was sold for £1.",
     "fallback_keywords": ["japanese stock exchange", "old bank building london", "trader panic screens", "singapore financial district", "courtroom handcuffs"]},
    {"category": "enron_scandal", "label": "CRASH", "title": "The Enron Accounting Fraud",
     "seed": "Enron was Fortune's 'most innovative company' six years running. Then in 2001 it emerged that $63.4 billion in assets were partly fictional — hidden in off-balance-sheet entities. The stock fell from $90 to 26 cents, and 20,000 employees lost jobs and pensions.",
     "fallback_keywords": ["corporate office tower", "accounting spreadsheet red", "texas houston skyline", "empty corporate lobby", "shredded documents"]},
    {"category": "flash_crash_2010", "label": "CRASH", "title": "The 2010 Flash Crash",
     "seed": "On May 6, 2010 at 2:32 PM, the Dow Jones dropped 998 points in minutes — nearly 9 percent — then rebounded almost fully. A single trader in London using a spoofing algorithm triggered $1 trillion in market value to vanish and return in under 30 minutes.",
     "fallback_keywords": ["trading screens red", "algorithm code screen", "stock market crash chart", "new york stock exchange", "server room data"]},
    {"category": "china_2015", "label": "CRASH", "title": "China's 2015 Margin Call Crash",
     "seed": "By June 2015, Chinese retail investors had borrowed a record $363 billion to buy stocks on margin. When Shanghai Composite turned, forced liquidations cascaded. The index crashed 30 percent in three weeks, wiping out $3.2 trillion — more than Germany's GDP.",
     "fallback_keywords": ["shanghai city skyline", "chinese trading floor", "asian stock screen red", "yuan currency close", "crowded stock exchange"]},
]


# ---------------------------------------------------------------------------
# Live-news → seed conversion
# ---------------------------------------------------------------------------
def _label_from_headline(title: str) -> str:
    """Pick a banner word (BREAKING / RALLY / CRASH / PROFILE) from headline tone."""
    t = title.lower()
    if any(w in t for w in ("crash", "plunge", "tumble", "rout", "wipe", "bankrupt")):
        return "CRASH"
    if any(w in t for w in ("soar", "surge", "skyrocket", "rally", "record", "all-time high")):
        return "RALLY"
    if any(w in t for w in ("ipo", "merger", "acquir", "buyback", "split")):
        return "BREAKING"
    if any(w in t for w in ("ceo", "founder", "billionaire")):
        return "PROFILE"
    return "BREAKING"


def _fallback_kw_from_text(title: str, summary: str, n: int = 5) -> list[str]:
    """Build n Pexels-search keyword strings from the live story so each
    fallback slide image still feels related to the topic."""
    text = f"{title} {summary}"
    nouns = re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text)
    seen: set[str] = set()
    kw: list[str] = []
    skip = {"the", "this", "that", "with", "from", "after", "before"}
    for w in nouns:
        wl = w.lower()
        if wl in seen or wl in skip:
            continue
        seen.add(wl)
        kw.append(f"{wl} business")
        if len(kw) >= n:
            break
    generics = ["stock market screen", "trading floor", "wall street",
                "skyscraper finance", "stock chart green"]
    i = 0
    while len(kw) < n:
        kw.append(generics[i % len(generics)])
        i += 1
    return kw[:n]


def _live_seed(today: date) -> dict | None:
    """Pull live news, pick first usable candidate, return SEED_STORIES-shaped dict."""
    try:
        from news_feed import fetch_candidates
    except Exception as e:
        log.warning("news_feed import failed (%s) - using curated fallback", e)
        return None

    try:
        candidates = fetch_candidates(today, limit=30)
    except Exception as e:
        log.warning("fetch_candidates raised (%s) - using curated fallback", e)
        return None

    if not candidates:
        log.info("No live candidates available - using curated fallback")
        return None

    pick = candidates[0]
    log.info("Live slideshow seed: %s [%s]", pick.title, pick.source)

    seed_text = pick.title.strip()
    if pick.summary:
        seed_text = f"{seed_text}. {pick.summary.strip()}"

    return {
        "category": f"live_{pick.source}",
        "label": _label_from_headline(pick.title),
        "title": pick.title.strip(),
        "seed": seed_text,
        "fallback_keywords": _fallback_kw_from_text(pick.title, pick.summary),
        "_live_pick": pick,
    }


def _rng_for(today: date) -> random.Random:
    return random.Random(today.toordinal() * 7919)


def pick_slideshow_story(today: date) -> SlideshowStory:
    """Live-first: try RSS, fall back to curated SEED_STORIES rotation."""
    seed = _live_seed(today)
    used_live = seed is not None

    if seed is None:
        idx = today.toordinal() % len(SEED_STORIES)
        seed = SEED_STORIES[idx]
        log.info("Slideshow story (curated) for %s: %s", today, seed["title"])
    else:
        log.info("Slideshow story (live) for %s: %s", today, seed["title"])

    structured = _generate_structured(
        seed_text=seed["seed"],
        topic_title=seed["title"],
        default_label=seed["label"],
        fallback_keywords=seed["fallback_keywords"],
    )

    if used_live and "_live_pick" in seed:
        try:
            from news_feed import mark_used
            mark_used(today, seed["_live_pick"])
        except Exception as e:
            log.warning("mark_used failed (%s) - story may be reused tomorrow", e)

    return SlideshowStory(
        category=seed["category"],
        category_label=structured.get("topic_label") or seed["label"],
        topic_title=seed["title"],
        seed_text=seed["seed"],
        slides=structured["slides"],
    )


# ---------------------------------------------------------------------------
# Gemini structured generation
# ---------------------------------------------------------------------------
GEMINI_PROMPT = """You are a senior content editor for a premium Instagram finance account.
You are writing a 5-SLIDE CAROUSEL telling ONE coherent finance news story.
Style: authoritative, factual, information-dense - like Bloomberg meets @_.daytrading_.

Story seed (use as factual basis - do NOT invent contradicting numbers):
{seed}

Topic label context (use as default, or replace with a short UPPERCASE banner word
like BREAKING / HISTORIC / CRASH / LEGENDARY / RALLY / PROFILE if more fitting): {default_label}

Produce the following structured output:

- topic_label: one UPPERCASE word for the banner on slide 1. Max 12 chars.

- slides: EXACTLY 5 entries. Each entry has:
    - text_html: a single dense paragraph, ALL UPPERCASE, 100 to 180 characters, telling the next beat of the story. Wrap 3 to 6 KEY words (numbers, names, percentages, big verbs) in <span class='h'>WORD</span> for cyan highlighting. Sentence fragments and commas OK. No ending hashtags. No emojis.
    - image_keywords: 2 or 3 words for a Pexels stock-photo search that fits that specific slide's subject. Every slide must have DIFFERENT keywords.

The 5 slides should arc like a news story:
  1. HOOK / HEADLINE: the single most striking fact, with the biggest numbers.
  2. CAUSE: what triggered this, upstream drivers.
  3. KEY DETAIL: a specific mechanism, player, or number inside the story.
  4. IMPACT / WHO WAS HIT: consequences, winners and losers.
  5. OUTLOOK / WHY IT MATTERS: what it means going forward, the lesson.

HARD RULES:
- Every number/date/name MUST be consistent with the seed. Do not invent bigger figures than the seed supports.
- All text UPPERCASE. No emojis. No hashtags inside slides.
- Allowed HTML: only <span class='h'>...</span>. Nothing else.
- Use straight ASCII quotes only. Never curly quotes. Avoid embedded double quotes.
- Each text_html is 100-180 characters INCLUDING the span tags - count carefully.
"""


def _generate_structured(seed_text: str, topic_title: str, default_label: str,
                         fallback_keywords: list[str]) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("No GEMINI_API_KEY - using fallback slideshow content")
        return _fallback_structured(seed_text, default_label, fallback_keywords)

    try:
        import google.generativeai as genai
    except Exception as e:
        log.warning("google-generativeai import failed (%s) - falling back", e)
        return _fallback_structured(seed_text, default_label, fallback_keywords)

    genai.configure(api_key=api_key)
    prompt = GEMINI_PROMPT.format(seed=seed_text, default_label=default_label)

    generation_config = {
        "temperature": 0.7,
        "max_output_tokens": 1800,
        "response_mime_type": "application/json",
        "response_schema": _SlideshowStructure,
    }

    last_err = None
    for model_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        try:
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(prompt, generation_config=generation_config)
            text = (resp.text or "").strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

            try:
                data = json.loads(text)
            except json.JSONDecodeError as je:
                log.warning("Gemini %s: JSON parse error (%s)", model_name, je)
                last_err = je
                continue

            required = {"topic_label", "slides"}
            missing = required - data.keys()
            if missing:
                log.warning("Gemini %s: missing keys %s", model_name, missing)
                last_err = ValueError(f"missing keys {missing}")
                continue
            if not isinstance(data["slides"], list) or len(data["slides"]) != 5:
                log.warning("Gemini %s: slides shape wrong", model_name)
                last_err = ValueError("slides not a 5-item list")
                continue
            bad = False
            for i, sl in enumerate(data["slides"]):
                if not isinstance(sl, dict) or "text_html" not in sl or "image_keywords" not in sl:
                    log.warning("Gemini %s: slide %d malformed", model_name, i)
                    bad = True
                    break
            if bad:
                last_err = ValueError("slide entry malformed")
                continue

            log.info("Gemini (%s) generated valid slideshow structure", model_name)
            return data

        except Exception as e:
            last_err = e
            err_s = str(e).lower()
            if "429" in err_s or "quota" in err_s or "rate" in err_s:
                log.warning("Gemini %s quota hit - trying next model: %s", model_name, e)
                continue
            log.info("Gemini %s failed (%s) - trying next model", model_name, e)
            continue

    log.warning("Gemini slideshow generation failed (%s) - falling back", last_err)
    return _fallback_structured(seed_text, default_label, fallback_keywords)


_PAD_TEXTS = [
    "THE STORY KEEPS DEVELOPING IN REAL TIME.",
    "MARKETS WATCHED CLOSELY AS EVENTS UNFOLDED.",
    "INVESTORS REASSESS POSITIONS AS NEW DATA ARRIVES.",
    "ANALYSTS DEBATE WHAT COMES NEXT FOR THE SECTOR.",
    "THE EPISODE CONTINUES TO RESHAPE THE INDUSTRY.",
]


def _fallback_structured(seed_text: str, default_label: str,
                         fallback_keywords: list[str]) -> dict:
    """Deterministic fallback: chop the seed into 5 uppercase pseudo-slides.

    Pad-texts are *index-specific* so slide 4 never reads the same as slide 5.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", seed_text.strip()) if s.strip()]
    while len(sentences) < 5:
        sentences.append(_PAD_TEXTS[len(sentences) % len(_PAD_TEXTS)])
    slides = []
    for i in range(5):
        s = sentences[i].upper()[:180]
        m = re.search(r"(\$?\d[\d,\.]*%?|\b(19|20)\d{2}\b)", s)
        if m:
            span = f"<span class='h'>{m.group(0)}</span>"
            s = s[:m.start()] + span + s[m.end():]
        slides.append({
            "text_html": s,
            "image_keywords": fallback_keywords[i % len(fallback_keywords)],
        })

    return {"topic_label": default_label, "slides": slides}


# ---------------------------------------------------------------------------
# Caption builder
# ---------------------------------------------------------------------------
HASHTAGS_SLIDESHOW = (
    "#finance #stockmarket #investing #trading #financenews #wallstreet "
    "#wealth #stocks #economy #markets #investor #moneymindset "
    "#financialfreedom #daytrading #crypto"
)


def build_slideshow_caption(story: SlideshowStory, brand_handle: str) -> str:
    lede = _strip_html(story.slides[0]["text_html"])
    close = _strip_html(story.slides[-1]["text_html"])

    parts = [
        story.topic_title, "",
        lede, "",
        close, "",
        f"Follow {brand_handle} for daily markets, money stories and investing insight.", "",
        HASHTAGS_SLIDESHOW, "",
        "Not financial advice. For informational purposes only.",
    ]
    return "\n".join(parts)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()
