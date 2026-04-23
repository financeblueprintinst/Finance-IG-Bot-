"""Entry point for scheduled Reel posts.

Has two phases matching the GitHub Actions workflow:

  --render-only   Pick today's content, call Gemini (if needed), TTS, render
                  the MP4, write a sidecar .json with the caption. Skip publish.

  (default)       Same as above, plus publish to Instagram. If a .json sidecar
  --publish-existing
                  for today already exists on disk (from a prior render phase),
                  the cached caption + video are reused — this keeps render
                  and publish phases consistent even if Gemini is stochastic.
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
from reel_generator import render_reel
from tts_generator import generate_speech

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("reel_main")


def _paths_for(today: date) -> tuple[Path, Path, Path]:
    stem = f"reel_{today.isoformat()}"
    return (
        OUTPUT_DIR / f"{stem}.mp3",
        OUTPUT_DIR / f"{stem}.mp4",
        OUTPUT_DIR / f"{stem}.json",
    )


def _write_meta(meta_path: Path, item: ContentItem, caption: str,
                duration: float) -> None:
    meta = {
        "category": item.category,
        "category_label": item.category_label,
        "text": item.text,
        "author": item.author,
        "caption": caption,
        "audio_duration": duration,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")


def _render(today: date) -> tuple[Path, str]:
    audio_path, video_path, meta_path = _paths_for(today)

    item = pick_content(today)
    log.info("Picked: %s / author=%r / %d chars",
             item.category, item.author, len(item.text))
    log.info("Text: %s", item.text)

    duration = generate_speech(item.text, audio_path)
    log.info("Voiceover: %.2fs at %s", duration, audio_path)

    render_reel(item, audio_path, video_path, BRAND_NAME, BRAND_HANDLE)
    caption = build_reel_caption(item)
    log.info("Caption:\n%s", caption)

    _write_meta(meta_path, item, caption, duration)
    log.info("Sidecar metadata: %s", meta_path)

    return video_path, caption


def _load_existing(today: date) -> tuple[Path, str]:
    _, video_path, meta_path = _paths_for(today)
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
                        help="Generate audio + video but skip IG publish.")
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
