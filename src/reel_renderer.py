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

log = logging.getLogger(__name__)

REEL_W, REEL_H = 1080, 1920
DURATION_S = 25  # must match CSS: 5 scenes × 5s each

_REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = _REPO_ROOT / "assets" / "reel_template.html"
MUSIC_DIR = _REPO_ROOT / "assets" / "music"


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------
def _render_template(context: dict) -> str:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
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
        browser = p.chromium.launch(
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                # Force GPU compositing + ANGLE for smoother CSS animations
                # even without real hardware GPU on CI runners.
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
                "--ignore-gpu-blocklist",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                # Avoid throttling of animations when tab is "backgrounded".
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

    # Quality-oriented encode for 1080x1920 portrait content:
    #   - CRF 18 keeps text/edges crisp (22 was producing ~840 kbps which
    #     softened type noticeably)
    #   - -maxrate / -bufsize cap peak bitrate so Instagram's ingestion
    #     doesn't re-transcode aggressively
    #   - preset slow costs ~15s more render time but gives ~20% better
    #     perceptual quality at the same bitrate
    common = [
        "-t", str(DURATION_S),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-maxrate", "10M",
        "-bufsize", "16M",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-r", "30",
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
                brand_name: str, brand_handle: str) -> float:
    """Render a reel from a structured ContentItem + 3 background image URLs.

    Returns the final video duration in seconds.
    """
    tmp_dir = out_mp4.parent / f"_{out_mp4.stem}_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    ctx = _build_context(item, image_urls, brand_name, brand_handle)
    html = _render_template(ctx)
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
