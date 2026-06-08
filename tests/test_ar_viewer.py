"""Tests for GET /api/ar/<sid> (AR viewer page)."""

from unittest.mock import MagicMock


def test_ar_viewer_db_error(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("DB down")
    )
    resp = client.get("/api/ar/sid-err")
    assert resp.status_code == 500


def test_ar_viewer_not_found(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    resp = client.get("/api/ar/sid-missing")
    assert resp.status_code == 404


def test_ar_viewer_processing(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "processing", "glb_url": None}])
    )
    resp = client.get("/api/ar/sid-proc")
    assert resp.status_code == 202
    html = resp.data.decode()
    assert "Processing" in html or "Ban Raha" in html


def test_ar_viewer_ready_without_glb_url(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "ready", "glb_url": None}])
    )
    resp = client.get("/api/ar/sid-no-url")
    assert resp.status_code == 202  # falls into waiting page


def test_ar_viewer_ready(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "ready", "glb_url": "https://cdn/model.glb"}])
    )
    resp = client.get("/api/ar/sid-ready")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "model-viewer" in html
    assert "https://cdn/model.glb" in html
    assert "AR Studio PK" in html
