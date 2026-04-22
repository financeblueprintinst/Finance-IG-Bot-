"""Entry point. Picks a post type by weekday, builds the post, publishes."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from caption_generator import generate_caption
from chart_generator import (
    render_commodities_forex,
    render_gainers_losers,
    render_market_recap,
    render_news_digest,
    render_weekly_recap,
)
from config import DRY_RUN, ROTATION
from data_fetcher import (
    fetch_commodities,
    fetch_forex,
    fetch_gainers_losers,
    fetch_indices,
    fetch_news,
    fetch_weekly_indices,
)
from instagram_publisher import publish_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _post_market_recap() -> tuple[Path, str]:
    quotes = fetch_indices()
    if not quotes:
        raise RuntimeError("No index data available")
    path = render_market_recap(quotes)
    context = "\n".join(
        f"- {q.name} ({q.ticker}): {q.price:,.2f}, {q.change_pct:+.2f}%"
        for q in quotes
    )
    caption = generate_caption("market_recap", context)
    return path, caption


def _post_gainers_losers() -> tuple[Path, str]:
    gainers, losers = fetch_gainers_losers(top_n=5)
    if not gainers and not losers:
        raise RuntimeError("No gainers/losers data available")
    path = render_gainers_losers(gainers, losers)
    context_lines = ["GAINERS:"]
    context_lines += [f"  {q.ticker}: {q.change_pct:+.2f}% at ${q.price:,.2f}" for q in gainers]
    context_lines.append("LOSERS:")
    context_lines += [f"  {q.ticker}: {q.change_pct:+.2f}% at ${q.price:,.2f}" for q in losers]
    caption = generate_caption("gainers_losers", "\n".join(context_lines))
    return path, caption


def _post_commodities_forex() -> tuple[Path, str]:
    commodities = fetch_commodities()
    forex = fetch_forex()
    if not commodities and not forex:
        raise RuntimeError("No commodities/forex data available")
    path = render_commodities_forex(commodities, forex)
    rows = [f"- {q.name}: {q.price:,.4f} ({q.change_pct:+.2f}%)"
            for q in commodities + forex]
    caption = generate_caption("commodities_forex", "\n".join(rows))
    return path, caption


def _post_weekly_recap() -> tuple[Path, str]:
    quotes = fetch_weekly_indices()
    if not quotes:
        raise RuntimeError("No weekly data available")
    path = render_weekly_recap(quotes)
    context = "\n".join(
        f"- {q.name}: last close {q.price:,.2f} ({q.change_pct:+.2f}% vs prev day)"
        for q in quotes
    )
    caption = generate_caption("weekly_recap", context)
    return path, caption


def _post_news_digest() -> tuple[Path, str]:
    items = fetch_news(limit=5, hours=24)
    if not items:
        raise RuntimeError("No news items available")
    path = render_news_digest(items)
    context = "\n".join(f"- [{n.source}] {n.title}" for n in items)
    caption = generate_caption("news_digest", context)
    return path, caption


DISPATCH = {
    "market_recap": _post_market_recap,
    "gainers_losers": _post_gainers_losers,
    "commodities_forex": _post_commodities_forex,
    "weekly_recap": _post_weekly_recap,
    "news_digest": _post_news_digest,
}


def run(post_type: str | None, dry_run: bool) -> int:
    if not post_type:
        post_type = ROTATION[datetime.now().weekday()]
    log.info("Post type for today: %s", post_type)

    if post_type not in DISPATCH:
        log.error("Unknown post type: %s", post_type)
        return 2

    path, caption = DISPATCH[post_type]()
    log.info("Rendered image: %s", path)
    log.info("Caption preview:\n%s", caption)

    if dry_run:
        log.info("Dry-run: skipping publish.")
        return 0

    try:
        media_id = publish_image(path, caption, dry_run=False)
        log.info("Published media_id=%s", media_id)
        return 0
    except Exception as e:
        log.error("Publish failed: %s", e)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", dest="post_type", default=None,
                        choices=list(DISPATCH.keys()),
                        help="Override today's post type")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render image + caption, skip Instagram publish")
    args = parser.parse_args()
    return run(args.post_type, dry_run=args.dry_run or DRY_RUN)


if __name__ == "__main__":
    sys.exit(main())
