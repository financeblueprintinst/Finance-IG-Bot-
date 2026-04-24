"""Render a 5-slide Instagram Carousel as 5 static JPG images.

Pipeline (much simpler than the reel pipeline):
  1. For each slide (5 total): fill the single-slide HTML template with
     slide-specific content + background image URLs.
  2. Launch headless Chromium via Playwright at 1080×1350 (4:5 portrait).
  3. Wait for fonts + background images to load.
  4. Take a JPG screenshot of the viewport.
  5. Return the list of 5 image paths.

No ffmpeg, no minterpolate, no video — carousel posts are just images, and
Instagram's feed handles the swipe interaction natively.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from slideshow_content import SlideshowStory

log = logging.getLogger(__name__)

# Instagram feed carousel aspect ratio 4:5 (max vertical for carousel posts).
SLIDE_W, SLIDE_H = 1080, 1350

_REPO_ROOT = Path(__file__).resolve().parent.parent
SLIDE_TEMPLATE_PATH = _REPO_ROOT / "assets" / "carousel_slide_template.html"


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------
def _render_template(context: dict) -> str:
    html = SLIDE_TEMPLATE_PATH.read_text(encoding="utf-8")
    for k, v in context.items():
        html = html.replace("{{" + k + "}}", str(v))
    return html


def _body_size_class(text_html: str) -> str:
    """Match reel_slideshow auto-sizing: shrink body text for longer slides."""
    # Strip the HTML span tags to count visible characters only.
    visible = text_html
    for tag in ("<span class='h'>", "<span class=\"h\">", "</span>"):
        visible = visible.replace(tag, "")
    n = len(visible)
    if n > 180:
        return "longer"
    if n > 130:
        return "long"
    return ""


def _build_slide_context(slide_idx: int, total_slides: int,
                        slide: dict, bg_url: str, deco_url: str,
                        badge_label: str, brand_footer: str) -> dict:
    """Build the placeholder dict for one slide."""
    is_first = slide_idx == 0
    is_last = slide_idx == total_slides - 1

    ctx = {
        "BG_URL": bg_url,
        "DECO_URL": deco_url,
        "BADGE_VISIBLE": "inline-block" if is_first else "none",
        "BADGE_LABEL": badge_label if is_first else "",
        "BODY_HTML": slide.get("text_html", ""),
        "BODY_SIZE_CLASS": _body_size_class(slide.get("text_html", "")),
        "PREV_VISIBLE": "none" if is_first else "flex",
        "NEXT_VISIBLE": "none" if is_last else "flex",
        "BRAND_FOOTER": brand_footer,
    }
    # Page pips: "active" on current slide, empty class otherwise.
    for i in range(5):
        ctx[f"PIP_{i}"] = "active" if i == slide_idx else ""
    return ctx


# ---------------------------------------------------------------------------
# Playwright screenshotting
# ---------------------------------------------------------------------------
def _screenshot_slide(html_path: Path, out_jpg: Path) -> None:
    """Open HTML in headless Chromium, take a JPG viewport screenshot."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = browser.new_context(
            viewport={"width": SLIDE_W, "height": SLIDE_H},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle",
                  timeout=60000)

        # Wait for the template's boot script to preload fonts + images.
        page.wait_for_function("window.READY === true", timeout=30000)
        # Small settle before capture so any late font paint lands.
        page.wait_for_timeout(350)

        page.screenshot(
            path=str(out_jpg),
            type="jpeg",
            quality=92,
            full_page=False,
            clip={"x": 0, "y": 0, "width": SLIDE_W, "height": SLIDE_H},
        )
        context.close()
        browser.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render_carousel_images(story: SlideshowStory, image_urls: list[str],
                           out_dir: Path, stem: str,
                           brand_name: str, brand_handle: str) -> list[Path]:
    """Render a 5-slide carousel as 5 JPG files.

    Args:
      story: SlideshowStory with 5 slides (each a dict with text_html + image_keywords).
      image_urls: exactly 5 background image URLs, one per slide.
      out_dir: directory to write the JPGs into (typically OUTPUT_DIR).
      stem: filename stem, e.g. "carousel_2026-04-24". Output files will be
            stem_1.jpg ... stem_5.jpg (1-indexed for human readability).
      brand_name, brand_handle: for the brand footer on every slide.

    Returns:
      Ordered list of 5 absolute JPG paths.
    """
    # Defensive: cycle if Pexels/fallback returned <5 URLs.
    imgs = list(image_urls)
    while len(imgs) < 5:
        imgs.append(imgs[len(imgs) % max(1, len(imgs))] if imgs else "")

    handle_clean = (brand_handle or "").lstrip("@").strip()
    brand_footer = (handle_clean or brand_name).upper()
    badge_label = story.category_label or "BREAKING"

    tmp_dir = out_dir / f"_{stem}_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []

    for i in range(5):
        slide = story.slides[i]
        # Deco image cycles through the other slides' backgrounds so every
        # slide's top-left circle shows a different complementary photo.
        deco_url = imgs[(i + 1) % 5]
        ctx = _build_slide_context(
            slide_idx=i,
            total_slides=5,
            slide=slide,
            bg_url=imgs[i],
            deco_url=deco_url,
            badge_label=badge_label,
            brand_footer=brand_footer,
        )
        html = _render_template(ctx)
        html_path = tmp_dir / f"slide_{i+1}.html"
        html_path.write_text(html, encoding="utf-8")

        out_jpg = out_dir / f"{stem}_{i+1}.jpg"
        log.info("Rendering slide %d/5: %s", i + 1, out_jpg.name)
        _screenshot_slide(html_path, out_jpg)
        log.info("  → %.0f KB", out_jpg.stat().st_size / 1024)
        out_paths.append(out_jpg)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_paths
