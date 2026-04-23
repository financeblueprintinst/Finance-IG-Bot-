"""Entry point for scheduled Reel posts (v2, premium-style).

Two-phase workflow (matches GitHub Actions):

  --render-only   Pick today's content, call Gemini for structured output,
                  pull Pexels images, render the MP4 via Playwright+ffmpeg,
                  write JSON sidecar with caption. No publish.

  --publish-existing  Reuse the MP4 + sidecar from a prior render phase.
                      Publish it to Instagram. Keeps render and publish
                      deterministic across the 2-phase CI job.

  (default, no flags)  Do both in one go (useful for local full-runs).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from config import BRAND_HANDLE, BRAND_NAME, DRY_RUN, OUTPUT_DIR
from content_library import ContentItem, build_reel_caption, pick_content
from instagram_publisher import publish_reel
from pexels_client import search_portrait_images
from reel_renderer import render_reel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("reel_main")


def _paths_for(today: date) -> tuple[Path, Path]:
    stem = f"reel_{today.isoformat()}"
    return (
        OUTPUT_DIR / f"{stem}.mp4",
        OUTPUT_DIR / f"{stem}.json",
    )


def _write_meta(meta_path: Path, item: ContentItem, image_urls: list[str],
                caption: str, duration: float) -> None:
    meta = {
        "category": item.category,
        "category_label": item.category_label,
        "source_text": item.source_text,
        "author": item.author,
        "hook_kicker": item.hook_kicker,
        "hook_html": item.hook_html,
        "beats": item.beats,
        "takeaway_html": item.takeaway_html,
        "image_keywords": item.image_keywords,
        "image_urls": image_urls,
        "caption": caption,
        "duration": duration,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")


def _render(today: date) -> tuple[Path, str]:
    video_path, meta_path = _paths_for(today)

    item = pick_content(today)
    log.info("Content: category=%s author=%s keywords=%r",
             item.category, item.author, item.image_keywords)
    log.info("Hook: %s", item.hook_html)
    log.info("Beat 1 [%s]: %s", item.beats[0]["kicker"], item.beats[0]["text_html"])
    log.info("Beat 2 [%s]: %s", item.beats[1]["kicker"], item.beats[1]["text_html"])
    log.info("Takeaway: %s", item.takeaway_html)

    image_urls = search_portrait_images(item.image_keywords, count=3)
    log.info("Background images: %s", image_urls)

    duration = render_reel(item, image_urls, video_path, BRAND_NAME, BRAND_HANDLE)

    caption = build_reel_caption(item)
    log.info("Caption:\n%s", caption)

    _write_meta(meta_path, item, image_urls, caption, duration)
    log.info("Sidecar metadata: %s", meta_path)

    return video_path, caption


def _load_existing(today: date) -> tuple[Path, str]:
    video_path, meta_path = _paths_for(today)
    if not video_path.exists():
        raise SystemExit(f"No rendered reel found for {today} at {video_path}")
    if not meta_path.exists():
        raise SystemExit(f"No sidecar metadata at {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    caption = meta["caption"]
    log.info("Reusing rendered reel %s with cached caption", video_path)
    return video_path, caption


def run(dry_run: bool, render_only: bool, publish_existing: bool) -> int:
    today = date.today()

    if publish_existing:
        video_path, caption = _load_existing(today)
    else:
        video_path, caption = _render(today)

    if render_only or dry_run:
        log.info("Skipping Instagram publish (render_only=%s dry_run=%s).",
                 render_only, dry_run)
        return 0

    try:
        media_id = publish_reel(video_path, caption, dry_run=False)
        log.info("Published reel media_id=%s", media_id)
        return 0
    except Exception as e:
        log.error("Reel publish failed: %s", e)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate the reel but skip IG publish.")
    parser.add_argument("--render-only", action="store_true",
                        help="Render phase of the 2-phase workflow (no publish).")
    parser.add_argument("--publish-existing", action="store_true",
                        help="Publish phase: reuse the reel rendered earlier today.")
    args = parser.parse_args()
    return run(
        dry_run=args.dry_run or DRY_RUN,
        render_only=args.render_only,
        publish_existing=args.publish_existing,
    )


if __name__ == "__main__":
    sys.exit(main())
