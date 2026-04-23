"""Render Instagram Reels (1080x1920 MP4) using matplotlib + moviepy.

Pipeline:
  1. Render a single branded portrait frame as a PNG (matplotlib).
  2. Combine the static frame with the TTS audio into a video (moviepy).
  3. Apply gentle fade in/out so the clip feels composed, not jarring.
  4. Export H.264 MP4 with AAC audio — Instagram-Reels-compatible.

Duration is driven by the TTS audio length, padded slightly so the last word
doesn't get clipped. The frame layout scales font size to text length so long
generated content and short punchy quotes both look balanced.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt

from config import COLORS
from content_library import ContentItem

log = logging.getLogger(__name__)

REEL_W, REEL_H = 1080, 1920  # Instagram Reels portrait format (9:16)


def _font_size_for_length(char_count: int) -> tuple[int, int]:
    """Map text length to (font_size_pt, wrap_width_chars).

    Short punchy quotes get large type; long explainers scale down so they
    still fit without clipping.
    """
    if char_count < 70:
        return 62, 19
    elif char_count < 120:
        return 52, 22
    elif char_count < 180:
        return 44, 26
    elif char_count < 240:
        return 38, 30
    else:
        return 33, 34


def _wrap(text: str, width: int) -> str:
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def render_reel_frame(item: ContentItem, out_path: Path,
                      brand_name: str, brand_handle: str) -> None:
    """Render the static portrait frame (1080x1920) as a PNG."""
    # DPI=100 → figure inches * 100 = pixels
    fig = plt.figure(figsize=(REEL_W / 100, REEL_H / 100), dpi=100,
                     facecolor=COLORS["bg"])
    ax = fig.add_axes([0, 0, 1, 1])  # full bleed
    ax.set_facecolor(COLORS["bg"])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Brand header (top)
    ax.text(0.5, 0.92, brand_name.upper(),
            fontsize=28, color=COLORS["accent"], weight="bold",
            ha="center", va="center", family="sans-serif")

    # Category label
    ax.text(0.5, 0.87, f"\u00B7  {item.category_label}  \u00B7",
            fontsize=16, color=COLORS["muted"], weight="bold",
            ha="center", va="center", family="sans-serif")

    # Main text with dynamic sizing
    font_size, wrap_w = _font_size_for_length(len(item.text))
    wrapped = _wrap(item.text, wrap_w)
    # Stylised quote marks for attributed quotes
    display = f"\u201C{wrapped}\u201D" if item.author else wrapped

    text_y = 0.55 if item.author else 0.50
    ax.text(0.5, text_y, display,
            fontsize=font_size, color=COLORS["fg"], weight="regular",
            ha="center", va="center", linespacing=1.32,
            family="sans-serif")

    # Author attribution (if present)
    if item.author:
        ax.text(0.5, 0.22, f"\u2014 {item.author}",
                fontsize=28, color=COLORS["accent"], style="italic",
                ha="center", va="center", family="sans-serif")

    # Footer: handle
    ax.text(0.5, 0.085, brand_handle,
            fontsize=19, color=COLORS["muted"],
            ha="center", va="center", family="sans-serif")

    # Disclaimer (very subtle)
    ax.text(0.5, 0.04, "Not financial advice. For information only.",
            fontsize=11, color=COLORS["muted"], alpha=0.55,
            ha="center", va="center", family="sans-serif")

    fig.savefig(out_path, dpi=100, facecolor=COLORS["bg"],
                bbox_inches=None, pad_inches=0)
    plt.close(fig)


def render_reel(item: ContentItem, audio_path: Path, out_path: Path,
                brand_name: str, brand_handle: str) -> float:
    """Compile the Reel MP4. Returns the final video duration in seconds."""
    from moviepy.editor import AudioFileClip, ImageClip

    # 1. Render the static frame
    frame_path = out_path.parent / f"_{out_path.stem}_frame.png"
    render_reel_frame(item, frame_path, brand_name, brand_handle)
    log.info("Reel frame rendered: %s", frame_path)

    # 2. Audio
    audio = AudioFileClip(str(audio_path))
    duration = audio.duration + 0.8  # tail so last word isn't cut

    # 3. Video = static image + audio + gentle fade
    clip = (
        ImageClip(str(frame_path), duration=duration)
        .set_fps(30)
        .fadein(0.7)
        .fadeout(0.4)
        .set_audio(audio)
    )

    # 4. Export — H.264 + AAC, pix_fmt yuv420p for IG compatibility
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="4500k",
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None,
        verbose=False,
    )

    # Cleanup
    clip.close()
    audio.close()
    if frame_path.exists():
        frame_path.unlink()

    log.info("Reel video written: %s (%.2fs)", out_path, duration)
    return duration
