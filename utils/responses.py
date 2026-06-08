import logging

from flask import jsonify

logger = logging.getLogger(__name__)


def error_response(message: str, status_code: int = 400):
    """Standardised JSON error envelope."""
    return jsonify({"error": message}), status_code


def db_error_response(exc: Exception):
    """Shorthand for database-layer errors.  Logs the real exception
    server-side but returns a generic message to the client."""
    logger.exception("Database error")
    return error_response("Database error. Please try again later.", status_code=500)
