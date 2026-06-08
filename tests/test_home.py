"""Tests for the health-check route (/)."""


def test_home_returns_status(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "status" in data
    assert "running" in data["status"].lower() or "AR Studio" in data["status"]
