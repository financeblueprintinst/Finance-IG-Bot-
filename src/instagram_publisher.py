"""Publish a single image post to Instagram via the Graph API.

Flow:
  1. Create a media container with a public image URL + caption.
  2. Poll container status until FINISHED.
  3. Publish the container.

The image URL must be publicly reachable by Meta's servers. For free-tier
hosting, we commit the PNG into the repo (output/ folder) and serve it via
raw.githubusercontent.com. The GitHub Actions workflow handles the commit.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.instagram.com/v21.0"


class InstagramPublisherError(RuntimeError):
    pass


def build_public_url(image_path: Path) -> str:
    """Turn a local PNG path into a raw.githubusercontent.com URL.

    Requires env vars:
      GITHUB_REPO      e.g. "your-user/finance-ig-bot"
      GITHUB_REF_NAME  e.g. "main"
    """
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    # image_path is absolute; we want the path relative to repo root.
    # Assumes the repo root is the parent of src/ and output/.
    repo_root = Path(__file__).resolve().parent.parent
    rel = image_path.resolve().relative_to(repo_root)
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel.as_posix()}"


def _create_container(account_id: str, token: str, image_url: str, caption: str) -> str:
    r = requests.post(
        f"{GRAPH_BASE}/{account_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        raise InstagramPublisherError(f"Create container failed: {r.status_code} {r.text}")
    return r.json()["id"]


def _wait_ready(container_id: str, token: str, timeout_s: int = 120) -> None:
    # Initial grace period: IG needs a few seconds even before the status endpoint
    # starts reporting anything meaningful. Skipping this often yields FINISHED
    # immediately but the publish endpoint then errors with "Media not ready".
    time.sleep(5)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        if r.ok:
            status = r.json().get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise InstagramPublisherError(f"Container errored: {r.json()}")
        time.sleep(3)
    raise InstagramPublisherError("Container did not become FINISHED in time")


def _publish(account_id: str, token: str, container_id: str) -> str:
    # Retry with backoff: even after status=FINISHED, the publish endpoint can
    # transiently return "Media ID is not available" (code 9007) while IG's
    # internals catch up. Retry a few times before giving up.
    last_err = None
    for attempt in range(6):
        r = requests.post(
            f"{GRAPH_BASE}/{account_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=30,
        )
        if r.ok:
            return r.json()["id"]
        last_err = f"{r.status_code} {r.text}"
        # Only retry on the specific "not ready yet" transient error
        try:
            err = r.json().get("error", {})
            if err.get("code") == 9007 or "not ready" in err.get("message", "").lower():
                log.info("Publish not ready yet (attempt %d/6), retrying in %ds",
                         attempt + 1, 5 + attempt * 3)
                time.sleep(5 + attempt * 3)
                continue
        except Exception:
            pass
        break
    raise InstagramPublisherError(f"Publish failed: {last_err}")


def publish_image(image_path: Path, caption: str, dry_run: bool = False) -> str | None:
    """Publish a single image. Returns the IG media ID, or None on dry-run."""
    image_url = build_public_url(image_path)
    log.info("Public image URL: %s", image_url)

    if dry_run:
        log.info("DRY_RUN=1 — skipping Instagram publish.")
        log.info("Caption:\n%s", caption)
        return None

    token = os.environ["IG_ACCESS_TOKEN"]
    account_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    container_id = _create_container(account_id, token, image_url, caption)
    log.info("Created container %s", container_id)
    _wait_ready(container_id, token)
    media_id = _publish(account_id, token, container_id)
    log.info("Published media %s", media_id)
    return media_id


# ---------------------------------------------------------------------------
# Reels publishing
# ---------------------------------------------------------------------------
def _create_reel_container(account_id: str, token: str, video_url: str,
                           caption: str) -> str:
    r = requests.post(
        f"{GRAPH_BASE}/{account_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        },
        timeout=60,
    )
    if not r.ok:
        raise InstagramPublisherError(
            f"Create reel container failed: {r.status_code} {r.text}"
        )
    return r.json()["id"]


def publish_reel(video_path: Path, caption: str, dry_run: bool = False) -> str | None:
    """Publish a video as an Instagram Reel.

    Reels go through the same container → wait → publish dance, but the
    processing window is much longer (video transcoding can take 30–120s
    on IG's side), so we bump the status-polling timeout to 10 minutes.
    """
    video_url = build_public_url(video_path)
    log.info("Public video URL: %s", video_url)

    if dry_run:
        log.info("DRY_RUN=1 — skipping Instagram reel publish.")
        log.info("Caption:\n%s", caption)
        return None

    token = os.environ["IG_ACCESS_TOKEN"]
    account_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    container_id = _create_reel_container(account_id, token, video_url, caption)
    log.info("Created reel container %s", container_id)
    _wait_ready(container_id, token, timeout_s=600)
    media_id = _publish(account_id, token, container_id)
    log.info("Published reel %s", media_id)
    return media_id
