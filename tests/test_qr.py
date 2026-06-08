"""Tests for GET /api/qr/<sid> (QR code generation)."""


def test_qr_returns_png(client):
    resp = client.get("/api/qr/sid-test")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    # PNG magic bytes
    assert resp.data[:4] == b"\x89PNG"


def test_qr_different_sids_produce_different_images(client):
    resp1 = client.get("/api/qr/sid-aaa")
    resp2 = client.get("/api/qr/sid-bbb")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.data != resp2.data
