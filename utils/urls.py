import os

APP_BASE_URL = os.environ.get("APP_BASE_URL", "")


def build_ar_url(sid: str) -> str:
    return f"{APP_BASE_URL}/api/ar/{sid}"


def build_qr_url(sid: str) -> str:
    return f"{APP_BASE_URL}/api/qr/{sid}"


def build_model_urls(sid: str) -> dict:
    """Return both AR and QR URLs for a given serialize id."""
    return {"ar_url": build_ar_url(sid), "qr_url": build_qr_url(sid)}
