"""Shared fixtures for ar-studio-pk tests."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Set required env vars so module-level code doesn't fail."""
    monkeypatch.setenv("KIRI_API_KEY", "test-kiri-key")
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-supa-key")
    monkeypatch.setenv("APP_BASE_URL", "https://example.com")


@pytest.fixture()
def mock_supa():
    """Return a MagicMock that replaces the Supabase client."""
    return MagicMock()


@pytest.fixture()
def app(mock_supa):
    """Import (or re-import) app.py with Supabase mocked out."""
    with patch("supabase.create_client", return_value=mock_supa):
        # Force re-import so module-level code picks up the mock
        if "app" in sys.modules:
            del sys.modules["app"]
        import app as app_module

    app_module.supa = mock_supa  # make sure route code uses the mock
    app_module.app.config["TESTING"] = True
    yield app_module


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.app.test_client()
