"""Supabase model-table helpers — eliminates repeated query + error handling."""

from __future__ import annotations

import logging
import os
from typing import Optional

from supabase import create_client, Client

from utils.responses import db_error_response, error_response

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_client: Optional[Client] = None

_REQUIRED_ENV = {"SUPABASE_URL": SUPABASE_URL, "SUPABASE_KEY": SUPABASE_KEY}
_missing = [k for k, v in _REQUIRED_ENV.items() if not v]
if _missing:
    logger.warning("Missing Supabase env vars: %s — database calls will fail.", ", ".join(_missing))


def get_supabase() -> Client:
    """Lazy-initialised Supabase client (avoids crash when env vars are empty
    during import)."""
    global _client
    if _client is None:
        try:
            _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.error("Failed to initialise Supabase client: %s", e)
            raise
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
        logger.error("DB query failed for model %s: %s", sid, e)
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
        logger.error("DB insert failed for model %s: %s", sid, e)
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
