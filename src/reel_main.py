"""Entry point for scheduled Reel posts (animated + slideshow).

Two-phase workflow (matches GitHub Actions):

  --render-only   Pick today's content, pull Pexels images, render the MP4,
                  write JSON sidecar with caption. No publish.

  --publish-existing  Reuse the MP4 + sidecar from a prior render phase.
                      Publish to Instagram. Keeps render and publish
                      deterministic across the 2-phase CI job.

  (default, no flags)  Do both in one go (useful for local full-runs).

  --slideshow     Render the news-slideshow Reel (5 scenes + crossfade +
                  royalty-free music) instead of the animated reel.
                  Used by the Mon/Wed/Fri workflow.
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
from reel_renderer import render_reel, render_slideshow
from slideshow_content import (
    SlideshowStory,
    build_slideshow_caption,
    pick_slideshow_story,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("reel_main")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def _reel_paths(today: date) -> tuple[Path, Path]:
    stem = f"reel_{today.isoformat()}"
    return OUTPUT_DIR / f"{stem}.mp4", OUTPUT_DIR / f"{stem}.json"


def _slideshow_paths(today: date) -> tuple[Path, Path]:
    """Returns (slideshow reel mp4 path, sidecar json path).

    Mo/Mi/Fr output: one Slideshow-Reel MP4 + its sidecar. No carousel JPGs
    - the story IS the reel.
    """
    stem = f"slideshow_{today.isoformat()}"
    return OUTPUT_DIR / f"{stem}.mp4", OUTPUT_DIR / f"{stem}.json"


# ---------------------------------------------------------------------------
# Metadata writers
# ---------------------------------------------------------------------------
def _write_meta_reel(meta_path: Path, item: ContentItem, image_urls: list[str],
                     caption: str, duration: float) -> None:
    meta = {
        "kind": "animated_reel",
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


def _write_meta_slideshow(meta_path: Path, story: SlideshowStory,
                          image_urls: list[str], caption: str,
                          duration: float) -> None:
    meta = {
        "kind": "slideshow_reel",
        "category": story.category,
        "category_label": story.category_label,
        "topic_title": story.topic_title,
        "seed_text": story.seed_text,
        "slides": story.slides,
        "image_urls": image_urls,
        "caption": caption,
        "duration": duration,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")


# ---------------------------------------------------------------------------
# Render phases
# ---------------------------------------------------------------------------
def _render_animated(today: date) -> tuple[Path, str]:
    """Animated reel pipeline (Tue/Thu/Sat/Sun)."""
    video_path, meta_path = _reel_paths(today)

    item = pick_content(today)
    log.info("Content: category=%s author=%s keywords=%r",
             item.category, item.author, item.image_keywords)
    log.info("Hook: %s", item.hook_html)
    log.info("Beat 1 [%s]: %s", item.beats[0]["kicker"], item.beats[0]["text_html"])
    log.info("Beat 2 [%s]: %s", item.beats[1]["kicker"], item.beats[1]["text_html"])
    log.info("Takeaway: %s", item.takeaway_html)

    image_urls = search_portrait_images(item.image_keywords, count=3)
    log.info("Background images: %s", image_urls)

    duration = render_reel(
        item, image_urls, video_path, BRAND_NAME, BRAND_HANDLE,
    )

    caption = build_reel_caption(item)
    log.info("Caption:\n%s", caption)

    _write_meta_reel(meta_path, item, image_urls, caption, duration)
    log.info("Sidecar metadata: %s", meta_path)

    return video_path, caption


def _render_slideshow(today: date) -> tuple[Path, str]:
    """Slideshow-Reel pipeline (Mon/Wed/Fri).

    One MP4 (1080x1920, ~25s) from a 5-beat SlideshowStory + Pexels images,
    crossfade scenes, royalty-free music muxed in. This IS the carousel -
    swipeable feed carousels are replaced by a single video Reel.
    """
    video_path, meta_path = _slideshow_paths(today)

    story = pick_slideshow_story(today)
    log.info("Slideshow story: %s (label=%s)", story.topic_title, story.category_label)
    for i, sl in enumerate(story.slides, 1):
        log.info("  Slide %d [%s]: %s",
                 i, sl.get("image_keywords", "?"), sl.get("text_html", ""))

    # One Pexels search per slide so every scene has its own themed background.
    image_urls: list[str] = []
    for i, sl in enumerate(story.slides, 1):
        kw = sl.get("image_keywords") or story.topic_title
        urls = search_portrait_images(kw, count=1)
        image_urls.append(urls[0])
        log.info("  Slide %d bg: %s -> %s", i, kw, urls[0])

    # Render the slideshow reel MP4 (Playwright + ffmpeg + music from assets/music/).
    log.info("Rendering slideshow reel MP4: %s", video_path.name)
    duration = render_slideshow(
        story, image_urls, video_path, BRAND_NAME, BRAND_HANDLE,
    )
    log.info("Reel MP4 written: %s (%.1fs)", video_path, duration)

    caption = build_slideshow_caption(story, BRAND_HANDLE)
    log.info("Caption:\n%s", caption)

    _write_meta_slideshow(meta_path, story, image_urls, caption, duration)
    log.info("Sidecar metadata: %s", meta_path)

    return video_path, caption


# ---------------------------------------------------------------------------
# Load previously-rendered artefacts (publish phase of 2-phase flow)
# ---------------------------------------------------------------------------
def _load_existing_reel(today: date) -> tuple[Path, str]:
    video_path, meta_path = _reel_paths(today)
    if not video_path.exists():
        raise SystemExit(f"No rendered reel found for {today} at {video_path}")
    if not meta_path.exists():
        raise SystemExit(f"No sidecar metadata at {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    log.info("Reusing rendered reel %s with cached caption", video_path)
    return video_path, meta["caption"]


def _load_existing_slideshow(today: date) -> tuple[Path, str]:
    video_path, meta_path = _slideshow_paths(today)
    if not video_path.exists():
        raise SystemExit(f"No slideshow reel MP4 for {today} at {video_path}")
    if not meta_path.exists():
        raise SystemExit(f"No sidecar metadata at {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    log.info("Reusing slideshow reel %s with cached caption", video_path)
    return video_path, meta["caption"]


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def run(dry_run: bool, render_only: bool, publish_existing: bool,
        slideshow: bool = False) -> int:
    today = date.today()

    if slideshow:
        if publish_existing:
            video_path, caption = _load_existing_slideshow(today)
        else:
            video_path, caption = _render_slideshow(today)

        if render_only or dry_run:
            log.info("Skipping Instagram publish (render_only=%s dry_run=%s).",
                     render_only, dry_run)
            return 0

        try:
            media_id = publish_reel(video_path, caption, dry_run=False)
            log.info("Published slideshow reel media_id=%s", media_id)
            return 0
        except Exception as e:
            log.error("Slideshow reel publish failed: %s", e)
            return 1

    if publish_existing:
        video_path, caption = _load_existing_reel(today)
    else:
        video_path, caption = _render_animated(today)

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
                        help="Generate output but skip IG publish.")
    parser.add_argument("--render-only", action="store_true",
                        help="Render phase of the 2-phase workflow (no publish).")
    parser.add_argument("--publish-existing", action="store_true",
                        help="Publish phase: reuse artefacts rendered earlier today.")
    parser.add_argument("--slideshow", action="store_true",
                        help="Use the news-slideshow Reel pipeline (5 scenes + "
                             "crossfade + music, one MP4). Used on Mon/Wed/Fri "
                             "when the animated reel workflow does not run.")
    args = parser.parse_args()
    return run(
        dry_run=args.dry_run or DRY_RUN,
        render_only=args.render_only,
        publish_existing=args.publish_existing,
        slideshow=args.slideshow,
    )


if __name__ == "__main__":
    sys.exit(main())
