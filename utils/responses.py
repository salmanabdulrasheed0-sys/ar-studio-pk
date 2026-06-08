from flask import jsonify


def error_response(message: str, status_code: int = 400, detail=None):
    """Standardised JSON error envelope."""
    payload = {"error": message}
    if detail is not None:
        payload["detail"] = detail
    return jsonify(payload), status_code


def db_error_response(exc: Exception):
    """Shorthand for database-layer errors."""
    return error_response(f"DB error: {exc}", status_code=500)
