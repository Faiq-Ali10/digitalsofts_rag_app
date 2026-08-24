"""Structured logging configuration using structlog.

All logs are JSON-formatted in production for machine parsing.
Human-readable in development. Sensitive data is automatically filtered.
"""

from __future__ import annotations

import logging
import re
import sys

import structlog

# Patterns for secrets that should never appear in logs
SENSITIVE_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|password|token|authorization)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"(sk-|pk-|gsk_|AIza)\S+", re.IGNORECASE),
]


def redact_sensitive(_, __, event_dict: dict) -> dict:
    """Structlog processor that redacts sensitive values from log entries."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            for pattern in SENSITIVE_PATTERNS:
                value = pattern.sub("[REDACTED]", value)
            event_dict[key] = value
        if any(
            secret_key in key.lower()
            for secret_key in ("password", "secret", "api_key", "token", "authorization")
        ):
            event_dict[key] = "[REDACTED]"
    return event_dict


def setup_logging(log_level: str = "INFO", json_format: bool = False) -> None:
    """Configure structlog for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        json_format: If True, output JSON logs (for production).
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        redact_sensitive,
    ]

    if json_format:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)
