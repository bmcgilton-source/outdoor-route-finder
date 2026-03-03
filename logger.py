"""
Logging configuration for TrailOps.

Usage in any module:
    from logger import get_logger
    log = get_logger(__name__)

Logger hierarchy:
    trailops                    ← root logger for this project
    trailops.tools.nws          ← tool wrappers
    trailops.agents.intelligence_agent
    trailops.orchestrator
    ...

Console handler: WARNING and above (keeps terminal clean during normal use).
File handler:    DEBUG and above, rotating at 5 MB, 3 backups.

Set LOG_LEVEL=DEBUG in .env to see all messages on the console (useful during dev).
"""

import logging
import logging.handlers
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_CONSOLE_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING)

_FILE_FORMAT    = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_CONSOLE_FORMAT = "%(asctime)s [%(levelname)-7s] %(module)s: %(message)s"
_DATE_FORMAT    = "%Y-%m-%d %H:%M:%S"


def _configure() -> None:
    root = logging.getLogger("trailops")
    if root.handlers:
        return  # already configured (e.g. module imported twice)

    root.setLevel(logging.DEBUG)  # handlers control what actually gets written

    # ── Console: WARNING and above by default ────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(_CONSOLE_LEVEL)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(console)

    # ── File: DEBUG and above, rotating ──────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "trailops.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the trailops namespace."""
    # Strip leading package path so names stay readable in logs
    # e.g. "agents.intelligence_agent" → "trailops.agents.intelligence_agent"
    return logging.getLogger(f"trailops.{name}")


_configure()
