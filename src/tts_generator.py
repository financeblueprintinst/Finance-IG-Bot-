"""Text-to-speech using Microsoft Edge TTS — free, no API key.

Edge-TTS hits Microsoft's public Edge browser speech endpoint. Quality is very
close to paid services; there's no hard rate limit for reasonable use. We use
a mature, warm-authoritative male voice that fits the FinanceBlueprint brand.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import edge_tts

log = logging.getLogger(__name__)

# Voice picks (all male, US/UK English). ChristopherNeural = mature,
# confident, slight warmth. Swap VOICE to any of these if you want variety:
#   en-US-ChristopherNeural  — mature, warm, authoritative (default)
#   en-US-GuyNeural          — friendly, approachable, everyman
#   en-US-DavisNeural        — deep, studio-announcer
#   en-GB-RyanNeural         — British, professional
VOICE = "en-US-ChristopherNeural"

# Slight rate slowdown + small pitch drop for gravitas on short clips.
RATE = "-5%"
PITCH = "-2Hz"


async def _synthesize(text: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await communicate.save(str(out_path))


def generate_speech(text: str, out_path: Path) -> float:
    """Synthesize ``text`` to an MP3 at ``out_path``.

    Returns the audio duration in seconds (measured via moviepy after writing).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Generating speech: voice=%s, rate=%s, pitch=%s, chars=%d",
             VOICE, RATE, PITCH, len(text))
    asyncio.run(_synthesize(text, out_path))

    # Measure duration
    from moviepy.editor import AudioFileClip
    clip = AudioFileClip(str(out_path))
    duration = clip.duration
    clip.close()
    log.info("Generated %s (%.2fs)", out_path, duration)
    return duration
