"""Tests for GET /api/status/<sid>."""

from unittest.mock import MagicMock, patch


def test_status_db_error(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("DB down")
    )
    resp = client.get("/api/status/sid-1")
    assert resp.status_code == 500
    assert "DB error" in resp.get_json()["error"]


def test_status_not_found(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    resp = client.get("/api/status/sid-unknown")
    assert resp.status_code == 404
    assert "not found" in resp.get_json()["error"].lower()


def test_status_already_ready(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "ready", "glb_url": "https://cdn/model.glb"}])
    )
    resp = client.get("/api/status/sid-ready")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ready"
    assert "ar_url" in data
    assert "qr_url" in data


def test_status_already_failed(client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "failed", "glb_url": None}])
    )
    resp = client.get("/api/status/sid-fail")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "failed"
    assert "message" in data


@patch("app.requests.get")
def test_status_kiri_unreachable(mock_get, client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "processing", "glb_url": None}])
    )
    mock_get.side_effect = RuntimeError("network")
    resp = client.get("/api/status/sid-proc")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "processing"


@patch("app._download_and_store_glb")
@patch("app.requests.get")
def test_status_kiri_ready_glb_ok(mock_get, mock_dl, client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "processing", "glb_url": None}])
    )
    mock_get.return_value = MagicMock()
    mock_get.return_value.json.return_value = {"data": {"status": 2}}
    mock_dl.return_value = "https://cdn/model.glb"

    resp = client.get("/api/status/sid-proc")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ready"


@patch("app._download_and_store_glb")
@patch("app.requests.get")
def test_status_kiri_ready_glb_fail(mock_get, mock_dl, client, mock_supa):
    mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"status": "processing", "glb_url": None}])
    )
    mock_get.return_value = MagicMock()
    mock_get.return_value.json.return_value = {"data": {"status": 2}}
    mock_dl.return_value = None

    resp = client.get("/api/status/sid-proc")
    assert resp.status_code == 500
    assert "failed" in resp.get_json()["status"]


@patch("app.requests.get")
def test_status_kiri_failed_or_expired(mock_get, client, mock_supa):
    for kiri_code in [1, 4]:
        mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"status": "processing", "glb_url": None}])
        )
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = {"data": {"status": kiri_code}}

        resp = client.get("/api/status/sid-proc")
        assert resp.get_json()["status"] == "failed"


@patch("app.requests.get")
def test_status_kiri_other_codes(mock_get, client, mock_supa):
    """Kiri status codes like -1 (uploading), 3 (queuing), 0 (processing)."""
    for kiri_code, label in [(-1, "uploading"), (3, "queuing"), (0, "processing")]:
        mock_supa.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"status": "processing", "glb_url": None}])
        )
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = {"data": {"status": kiri_code}}

        resp = client.get("/api/status/sid-proc")
        assert resp.get_json()["status"] == label
