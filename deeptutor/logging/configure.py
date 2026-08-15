"""DeepTutor logging bootstrap."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .config import LoggingConfig, load_logging_config
from .formatters import ConsoleFormatter, ContextFilter, JsonlFormatter
from .loguru_bridge import install_loguru_bridge

_CONFIGURED = False
_MANAGED_ATTR = "_deeptutor_managed"
_BLUEWAY_EVENT_LOGGER = "deeptutor.integrations.blueway.observability"


class _ConfiguredLevelOrBlueWayEvent(logging.Filter):
    """Keep product threshold semantics while retaining the audit event stream."""

    def __init__(self, configured_level: int) -> None:
        super().__init__()
        self.configured_level = configured_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.configured_level or (
            record.name == _BLUEWAY_EVENT_LOGGER and record.levelno >= logging.INFO
        )


def _level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(getattr(logging, str(value).upper(), logging.INFO))


def _managed(
    handler: logging.Handler, *, configured_level: int | None = None,
) -> logging.Handler:
    setattr(handler, _MANAGED_ATTR, True)
    handler.addFilter(ContextFilter())
    if configured_level is not None:
        handler.addFilter(_ConfiguredLevelOrBlueWayEvent(configured_level))
    return handler


def _remove_managed_handlers(root: logging.Logger) -> None:
    for handler in list(root.handlers):
        if getattr(handler, _MANAGED_ATTR, False):
            root.removeHandler(handler)
            handler.close()


def configure_logging(force: bool = False) -> LoggingConfig:
    """Configure stdlib logging once for the whole process."""
    global _CONFIGURED

    config = load_logging_config()
    root = logging.getLogger()
    if _CONFIGURED and not force:
        return config

    if force:
        _remove_managed_handlers(root)

    level = _level(config.level)
    root.setLevel(logging.DEBUG)

    if config.console_output:
        console = _managed(
            logging.StreamHandler(sys.stdout), configured_level=level,
        )
        console.setLevel(logging.DEBUG)
        console.setFormatter(ConsoleFormatter())
        root.addHandler(console)

    if config.file_output:
        log_dir = Path(config.log_dir) if config.log_dir else Path("data/user/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = _managed(
            RotatingFileHandler(
                log_dir / "deeptutor.jsonl",
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
            ),
            configured_level=level,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonlFormatter())
        root.addHandler(file_handler)

    logging.getLogger("deeptutor").setLevel(logging.DEBUG)
    logging.getLogger("deeptutor").propagate = True
    install_loguru_bridge(logging.DEBUG)
    _CONFIGURED = True
    return config
