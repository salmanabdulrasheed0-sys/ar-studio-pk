"""Tests for POST /api/upload."""

import io
from unittest.mock import MagicMock, patch

import requests as real_requests


# ── helpers ──────────────────────────────────────────────────────
def _video_data():
    return {"video": (io.BytesIO(b"fake-video-bytes"), "test.mp4")}


# ── tests ────────────────────────────────────────────────────────
def test_upload_missing_video(client):
    resp = client.post("/api/upload")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Video file required"


@patch("app.requests.post")
def test_upload_kiri_timeout(mock_post, client):
    mock_post.side_effect = real_requests.exceptions.Timeout
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 408
    assert "Timeout" in resp.get_json()["error"]


@patch("app.requests.post")
def test_upload_kiri_generic_exception(mock_post, client):
    mock_post.side_effect = RuntimeError("boom")
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 500
    assert "Upload error" in resp.get_json()["error"]


@patch("app.requests.post")
def test_upload_kiri_non_ok_response(mock_post, client):
    mock_post.return_value = MagicMock(ok=False, text="bad request")
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 500
    assert "Kiri Engine error" in resp.get_json()["error"]


@patch("app.requests.post")
def test_upload_kiri_credits_exhausted(mock_post, client):
    mock_post.return_value = MagicMock(
        ok=True,
        json=lambda: {"ok": False, "code": 4011},
    )
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 403
    assert "credits" in resp.get_json()["error"].lower()


@patch("app.requests.post")
def test_upload_kiri_bad_format(mock_post, client):
    mock_post.return_value = MagicMock(
        ok=True,
        json=lambda: {"ok": False, "code": 4001},
    )
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "format" in resp.get_json()["error"].lower()


@patch("app.requests.post")
def test_upload_kiri_unknown_rejection(mock_post, client):
    mock_post.return_value = MagicMock(
        ok=True,
        json=lambda: {"ok": False, "code": 9999},
    )
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Kiri rejected" in resp.get_json()["error"]


@patch("app.requests.post")
def test_upload_db_insert_error(mock_post, client, mock_supa):
    mock_post.return_value = MagicMock(
        ok=True,
        json=lambda: {"ok": True, "data": {"serialize": "sid-123"}},
    )
    mock_supa.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")
    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 500
    assert "DB error" in resp.get_json()["error"]


@patch("app.requests.post")
def test_upload_success(mock_post, client, mock_supa):
    mock_post.return_value = MagicMock(
        ok=True,
        json=lambda: {"ok": True, "data": {"serialize": "sid-abc"}},
    )
    mock_supa.table.return_value.insert.return_value.execute.return_value = None

    resp = client.post("/api/upload", data=_video_data(), content_type="multipart/form-data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["serialize_id"] == "sid-abc"
    assert "ar_url" in data
    assert "qr_url" in data
