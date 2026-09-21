"""Structured application logging and ASGI request diagnostics.

Supports LOG_LEVEL (debug | info | error) and file logging to data/logs/cem-master-backend/app.log.
"""
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

# 1. Resolve Log Level (support LOG_LEVEL=debug|info|error and legacy DEBUG=true)
_raw_debug = os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
_raw_level = os.getenv("LOG_LEVEL", "").strip().lower()

if _raw_debug or _raw_level == "debug":
    LOG_LEVEL = logging.DEBUG
    DEBUG = True
elif _raw_level == "error":
    LOG_LEVEL = logging.ERROR
    DEBUG = False
else:
    LOG_LEVEL = logging.INFO
    DEBUG = False

# 2. Setup Logger
_logger = logging.getLogger("cem.master")
_logger.setLevel(LOG_LEVEL)
_logger.propagate = False

_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 3. Add Stdout StreamHandler
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in _logger.handlers):
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(LOG_LEVEL)
    stream_handler.setFormatter(_formatter)
    _logger.addHandler(stream_handler)

# 4. Add Persistent FileHandler under /data/logs/cem-master-backend/app.log
_log_dir = Path(os.getenv("LOG_DIR", "/data/logs/cem-master-backend"))
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / "app.log"
    file_handler = logging.FileHandler(_log_file, encoding="utf-8")
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(_formatter)
    _logger.addHandler(file_handler)
except Exception:
    # Graceful fallback: stdout logging remains active even if log directory is not mounted/writeable
    pass


def _format_event(event: str, fields: dict) -> str:
    if fields:
        return f"{event} {json.dumps(fields, default=str, sort_keys=True)}"
    return event


def debug(event: str, **fields) -> None:
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(_format_event(event, fields))


def info(event: str, **fields) -> None:
    if _logger.isEnabledFor(logging.INFO):
        _logger.info(_format_event(event, fields))


def error(event: str, **fields) -> None:
    if _logger.isEnabledFor(logging.ERROR):
        _logger.error(_format_event(event, fields))


class DebugRequests:
    """Observe ASGI status/timing without reading bodies or buffering audio."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not DEBUG or scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex[:12]
        started = perf_counter()
        status = 500
        debug("http.start", request_id=request_id, method=scope["method"])

        async def observe(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception as exc:
            error("http.error", request_id=request_id, error=type(exc).__name__, message=str(exc))
            raise
        finally:
            route = getattr(scope.get("route"), "path", "<unmatched>")
            debug(
                "http.finish",
                request_id=request_id,
                method=scope["method"],
                route=route,
                status=status,
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
            )
