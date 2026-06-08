"""Tests for _download_and_store_glb helper."""

import io
import zipfile
from unittest.mock import MagicMock, patch


def _make_zip_bytes(filenames: list[str]) -> bytes:
    """Build an in-memory ZIP with the given (empty-ish) filenames."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in filenames:
            zf.writestr(name, b"fake-glb-data")
    return buf.getvalue()


@patch("app.requests.get")
def test_download_glb_success(mock_get, app, mock_supa):
    zip_bytes = _make_zip_bytes(["model.glb"])

    # First call: getModelZip → returns download URL
    resp_zip_url = MagicMock()
    resp_zip_url.json.return_value = {"data": {"modelUrl": "https://cdn/zip"}}

    # Second call: actual ZIP download
    resp_zip_data = MagicMock(content=zip_bytes)

    mock_get.side_effect = [resp_zip_url, resp_zip_data]
    mock_supa.storage.from_.return_value.upload.return_value = None
    mock_supa.storage.from_.return_value.get_public_url.return_value = "https://cdn/sid.glb"

    result = app._download_and_store_glb("sid-ok")
    assert result == "https://cdn/sid.glb"
    mock_supa.storage.from_.return_value.upload.assert_called_once()


@patch("app.requests.get")
def test_download_glb_no_glb_in_zip(mock_get, app, mock_supa):
    zip_bytes = _make_zip_bytes(["readme.txt"])

    resp_zip_url = MagicMock()
    resp_zip_url.json.return_value = {"data": {"modelUrl": "https://cdn/zip"}}
    resp_zip_data = MagicMock(content=zip_bytes)

    mock_get.side_effect = [resp_zip_url, resp_zip_data]

    result = app._download_and_store_glb("sid-no-glb")
    assert result is None


@patch("app.requests.get")
def test_download_glb_exception(mock_get, app):
    mock_get.side_effect = RuntimeError("network")
    result = app._download_and_store_glb("sid-err")
    assert result is None
