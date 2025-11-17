import contextvars
import logging
import logging.config
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Context variable to store request ID per request
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        # Attach current request id to the record
        rid = request_id_var.get("-")
        record.request_id = rid
        return True


def setup_logging(*, level: str = "INFO", to_file: bool = True, file_path: str = "logs/app.log", max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    # Clear existing handlers configured by uvicorn or basicConfig
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(RequestIdFilter())
    root.addHandler(console)

    if to_file:
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count)
            fh.setFormatter(formatter)
            fh.addFilter(RequestIdFilter())
            root.addHandler(fh)
        except Exception as e:
            # Fallback if file handler fails
            logging.getLogger(__name__).warning("Failed to setup file logging: %s", e)

    # Make common noisy loggers less verbose and avoid duplicate access logs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for noisy in ("uvicorn", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(getattr(logging, level.upper(), logging.INFO))


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Adds X-Request-ID to every request and logs basic request/response details."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = logging.getLogger("request")

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        # Get or generate request id
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            self.logger.info("%s %s from %s", request.method, request.url.path, request.client.host if request.client else "-")
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = rid
            self.logger.info("%s %s -> %s in %.1fms", request.method, request.url.path, response.status_code, duration_ms)
            return response
        except Exception:
            self.logger.exception("Unhandled error during request processing")
            raise
        finally:
            # Reset context var
            request_id_var.reset(token)
