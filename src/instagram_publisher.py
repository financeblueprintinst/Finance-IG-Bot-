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

GRAPH_BASE = "https://graph.facebook.com/v20.0"


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
    r = requests.post(
        f"{GRAPH_BASE}/{account_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    if not r.ok:
        raise InstagramPublisherError(f"Publish failed: {r.status_code} {r.text}")
    return r.json()["id"]


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
