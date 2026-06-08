"""Thin wrapper around the Kiri Engine REST API.

Centralises base-URL, auth header, and timeout so callers don't repeat
boilerplate.
"""

from __future__ import annotations

import os
from typing import Any

import requests

KIRI_API_KEY = os.environ.get("KIRI_API_KEY", "")
KIRI_BASE = "https://api.kiriengine.app/api/v1/open"
KIRI_HEADERS = {"Authorization": f"Bearer {KIRI_API_KEY}"}


def kiri_request(
    method: str,
    endpoint: str,
    *,
    timeout: int = 30,
    **kwargs: Any,
) -> requests.Response:
    """Send a request to the Kiri Engine API.

    Parameters
    ----------
    method : str
        HTTP verb (``"GET"``, ``"POST"``, …).
    endpoint : str
        Path relative to the Kiri base URL, e.g. ``"/photo/video"``.
    timeout : int
        Request timeout in seconds (default 30).
    **kwargs
        Forwarded to :func:`requests.request` (``data``, ``files``, ``params``, …).
    """
    url = f"{KIRI_BASE}{endpoint}"
    return requests.request(
        method,
        url,
        headers=KIRI_HEADERS,
        timeout=timeout,
        **kwargs,
    )


def upload_video(video_file, quality: str = "1") -> requests.Response:
    """Upload a video to Kiri Engine for 3-D reconstruction."""
    return kiri_request(
        "POST",
        "/photo/video",
        timeout=300,
        files={"videoFile": (video_file.filename, video_file.read(), "video/mp4")},
        data={
            "modelQuality": quality,
            "textureQuality": "1",
            "fileFormat": "glb",
            "isMask": "1",
            "textureSmoothing": "0",
        },
    )


def get_status(sid: str) -> requests.Response:
    """Get the processing status for a serialize id."""
    return kiri_request("GET", "/model/getStatus", params={"serialize": sid})


def get_model_zip_url(sid: str) -> requests.Response:
    """Get the download URL for the finished model ZIP."""
    return kiri_request("GET", "/model/getModelZip", params={"serialize": sid})
