"""Supabase model-table helpers — eliminates repeated query + error handling."""

from __future__ import annotations

import os
from typing import Optional

from supabase import create_client, Client

from utils.responses import db_error_response, error_response

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client: Optional[Client] = None


def get_supabase() -> Client:
    """Lazy-initialised Supabase client (avoids crash when env vars are empty
    during import)."""
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Read helpers ────────────────────────────────────────────────

def get_model(sid: str, columns: str = "*"):
    """Fetch a single model row by serialize_id.

    Returns ``(record_dict, None)`` on success, or
    ``(None, flask_response)`` on failure.
    """
    try:
        result = (
            get_supabase()
            .table("models")
            .select(columns)
            .eq("serialize_id", sid)
            .execute()
        )
    except Exception as e:
        return None, db_error_response(e)

    if not result.data:
        return None, error_response("Task not found", 404)

    return result.data[0], None


# ── Write helpers ───────────────────────────────────────────────

def create_model(sid: str):
    """Insert a new model row in *processing* state.

    Returns ``None`` on success, or a Flask error response on failure.
    """
    try:
        get_supabase().table("models").insert(
            {"serialize_id": sid, "status": "processing", "glb_url": None}
        ).execute()
    except Exception as e:
        return db_error_response(e)
    return None


def update_model_status(
    sid: str,
    status: str,
    glb_url: Optional[str] = None,
):
    """Update the status (and optionally glb_url) for a model row."""
    data: dict = {"status": status}
    if glb_url is not None:
        data["glb_url"] = glb_url
    get_supabase().table("models").update(data).eq("serialize_id", sid).execute()
