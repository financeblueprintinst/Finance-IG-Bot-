"""Render an Instagram Reel via Playwright (HTML → WebM) and ffmpeg (WebM → MP4 + music).

Pipeline:
  1. Fill HTML template with ContentItem + Pexels image URLs.
  2. Launch headless Chromium via Playwright at 1080×1920.
  3. Wait for fonts + background images to load, then record for ~26s.
  4. ffmpeg: trim to exact duration, encode H.264 / yuv420p, mux royalty-free
     music from assets/music/ (pick random; silent if dir empty).
"""
from __future__ import annotations

import logging
import random
import shutil
import subprocess
from pathlib import Path

from content_library import ContentItem
from slideshow_content import SlideshowStory

log = logging.getLogger(__name__)

REEL_W, REEL_H = 1080, 1920
DURATION_S = 25  # must match CSS: 5 scenes × 5s each

_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = _REPO_ROOT / "assets" / "reel_template.html"
SLIDESHOW_TEMPLATE_PATH = _REPO_ROOT / "assets" / "reel_slideshow_template.html"
MUSIC_DIR = _REPO_ROOT / "assets" / "music"


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------
def _render_template(context: dict, template_path: Path | None = None) -> str:
    path = template_path or TEMPLATE_PATH
    html = path.read_text(encoding="utf-8")
    for k, v in context.items():
        html = html.replace("{{" + k + "}}", str(v))
    return html


def _build_context(item: ContentItem, image_urls: list[str],
                   brand_name: str, brand_handle: str) -> dict:
    """Map ContentItem fields to the template placeholders."""
    return {
        "BG1_URL": image_urls[0],
        "BG2_URL": image_urls[1] if len(image_urls) > 1 else image_urls[0],
        "BG3_URL": image_urls[2] if len(image_urls) > 2 else image_urls[0],
        "CATEGORY": item.category_label,
        "BRAND_NAME": brand_name,
        "BRAND_HANDLE": brand_handle,
        "HOOK_KICKER": item.hook_kicker,
        "HOOK_HTML": item.hook_html,
        "BEAT_1_KICKER": item.beats[0]["kicker"],
        "BEAT_1_HTML": item.beats[0]["text_html"],
        "BEAT_2_KICKER": item.beats[1]["kicker"],
        "BEAT_2_HTML": item.beats[1]["text_html"],
        "TAKEAWAY_HTML": item.takeaway_html,
    }


# ---------------------------------------------------------------------------
# Playwright recording
# ---------------------------------------------------------------------------
def _record_video(html_path: Path, tmp_dir: Path) -> Path:
    """Open HTML in headless Chromium and record a WebM of the playing timeline."""
    from playwright.sync_api import sync_playwright

    tmp_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Minimal flag set only — experimenting with GPU/ANGLE acceleration
        # (swiftshader, gpu-rasterization) backfired on GitHub runners: it
        # made Chromium 5–10x slower, which starved setInterval so scenes
        # never advanced inside the 25s recording window. Plain software
        # rendering is actually faster here.
        browser = p.chromium.launch(
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ]
        )
        context = browser.new_context(
            viewport={"width": REEL_W, "height": REEL_H},
            record_video_dir=str(tmp_dir),
            record_video_size={"width": REEL_W, "height": REEL_H},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle", timeout=60000)

        # Wait for the template's load script to signal it has preloaded fonts + BG images
        page.wait_for_function("window.READY === true", timeout=30000)
        # Small additional settle time before we start counting the reel duration
        page.wait_for_timeout(300)

        # Record the full reel + a safety tail so final scene has time to breathe
        page.wait_for_timeout((DURATION_S + 1) * 1000)

        context.close()
        browser.close()

    webms = sorted(tmp_dir.glob("*.webm"))
    if not webms:
        raise RuntimeError("Playwright did not produce a video")
    return webms[-1]


# ---------------------------------------------------------------------------
# ffmpeg finalisation
# ---------------------------------------------------------------------------
def _pick_music() -> Path | None:
    if not MUSIC_DIR.exists():
        return None
    tracks: list[Path] = []
    for ext in ("*.mp3", "*.m4a", "*.wav"):
        tracks.extend(MUSIC_DIR.glob(ext))
    if not tracks:
        return None
    return random.choice(tracks)


def _finalize(video_webm: Path, music: Path | None, out_mp4: Path) -> None:
    """Convert WebM → MP4 at exact DURATION_S, muxing music if provided."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    # Quality-oriented encode for 1080x1920 portrait content.
    #
    # Motion interpolation (minterpolate, mi_mode=mci) synthesises fully
    # motion-compensated intermediate frames so 25 fps Playwright output
    # becomes buttery-smooth 60 fps. Tradeoff: costs ~10-15 min of CI
    # compute per render, but the user explicitly preferred waiting over
    # any quality regression. fps=30 then brings it back to the target
    # output rate without losing the smoothness.
    #
    # Rate control: pure CRF was producing ~1 Mbps on mostly-dark frames
    # which makes gradients band and text look soft. We force a higher
    # target bitrate so Instagram's re-encode has more to work with.
    vf_filter = (
        "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:"
        "vsbmc=1,fps=30,format=yuv420p"
    )
    common = [
        "-t", str(DURATION_S),
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "17",
        "-b:v", "6M",
        "-maxrate", "9M",
        "-bufsize", "14M",
        "-movflags", "+faststart",
        "-profile:v", "high",
        "-level", "4.1",
    ]

    if music:
        # Audio fades: gentle in over 0.8s, out over last 1s, volume at 60%
        afilter = (
            f"afade=t=in:st=0:d=0.8,"
            f"afade=t=out:st={DURATION_S - 1.0}:d=1.0,"
            f"volume=0.6"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_webm),
            "-i", str(music),
            *common,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:a", "aac", "-b:a", "128k",
            "-af", afilter,
            "-shortest",
            str(out_mp4),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_webm),
            *common,
            "-an",
            str(out_mp4),
        ]

    log.info("ffmpeg finalize: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("ffmpeg stderr:\n%s", result.stderr)
        raise RuntimeError(f"ffmpeg failed with code {result.returncode}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render_reel(item: ContentItem, image_urls: list[str], out_mp4: Path,
                brand_name: str, brand_handle: str,
                template_path: Path | None = None) -> float:
    """Render a reel from a structured ContentItem + 3 background image URLs.

    `template_path` lets the caller swap the HTML template (e.g. the
    slideshow variant) while keeping the rest of the pipeline identical —
    same placeholder names, same Playwright flow, same ffmpeg finalisation.

    Returns the final video duration in seconds.
    """
    tmp_dir = out_mp4.parent / f"_{out_mp4.stem}_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    ctx = _build_context(item, image_urls, brand_name, brand_handle)
    html = _render_template(ctx, template_path=template_path)
    html_path = tmp_dir / "reel.html"
    html_path.write_text(html, encoding="utf-8")
    log.info("Template rendered: %s", html_path)

    log.info("Recording Playwright video (%dx%d, ~%ds)…", REEL_W, REEL_H, DURATION_S + 1)
    webm = _record_video(html_path, tmp_dir)
    log.info("Recorded %s (%.1f MB)", webm.name, webm.stat().st_size / 1e6)

    music = _pick_music()
    if music:
        log.info("Music track picked: %s", music.name)
    else:
        log.info("No music tracks in assets/music/ — rendering silent")

    _finalize(webm, music, out_mp4)
    log.info("Final reel written: %s", out_mp4)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return float(DURATION_S)


# ---------------------------------------------------------------------------
# Slideshow pipeline (news-carousel style). Different content shape than the
# animated reel (5 independent slides + 5 independent images), so it builds
# its own context dict and uses its own template — but reuses the same
# Playwright recording + ffmpeg finalisation path.
# ---------------------------------------------------------------------------
def _build_slideshow_context(story: SlideshowStory, image_urls: list[str],
                             brand_footer: str) -> dict:
    """Map a SlideshowStory + 5 Pexels images onto the slideshow template."""
    # Defensive: if Pexels/fallback returned <5 URLs, cycle.
    imgs = list(image_urls)
    while len(imgs) < 5:
        imgs.append(imgs[len(imgs) % max(1, len(imgs))] if imgs else "")

    slides = story.slides
    ctx = {
        "BADGE_LABEL": story.category_label,
        "BRAND_FOOTER": brand_footer,
    }
    for i in range(5):
        ctx[f"BG_{i+1}_URL"] = imgs[i]
        ctx[f"SLIDE_{i+1}_HTML"] = slides[i]["text_html"]
    return ctx


def render_slideshow(story: SlideshowStory, image_urls: list[str], out_mp4: Path,
                     brand_name: str, brand_handle: str) -> float:
    """Render a news-carousel slideshow reel.

    `image_urls` must contain exactly 5 entries (one per slide). Each slide
    also carries its own `image_keywords` on the SlideshowStory, so the
    caller is expected to have searched Pexels per-slide before calling in.

    Brand footer prefers BRAND_HANDLE without the leading '@' (uppercase),
    falling back to BRAND_NAME. That matches the "DAYTRADING.CO" aesthetic.
    """
    handle_clean = (brand_handle or "").lstrip("@").strip()
    brand_footer = (handle_clean or brand_name).upper()

    tmp_dir = out_mp4.parent / f"_{out_mp4.stem}_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    ctx = _build_slideshow_context(story, image_urls, brand_footer)
    html = _render_template(ctx, template_path=SLIDESHOW_TEMPLATE_PATH)
    html_path = tmp_dir / "reel.html"
    html_path.write_text(html, encoding="utf-8")
    log.info("Slideshow template rendered: %s", html_path)

    log.info("Recording Playwright video (%dx%d, ~%ds)…",
             REEL_W, REEL_H, DURATION_S + 1)
    webm = _record_video(html_path, tmp_dir)
    log.info("Recorded %s (%.1f MB)", webm.name, webm.stat().st_size / 1e6)

    music = _pick_music()
    if music:
        log.info("Music track picked: %s", music.name)
    else:
        log.info("No music tracks in assets/music/ — rendering silent")

    _finalize(webm, music, out_mp4)
    log.info("Final slideshow reel written: %s", out_mp4)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return float(DURATION_S)
