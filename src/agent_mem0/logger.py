"""Logging module for agent-mem0."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logger: logging.Logger | None = None


def setup_logger(config: dict) -> logging.Logger:
    """Setup and return the global logger with rotating file handler."""
    global _logger
    if _logger is not None:
        return _logger

    log_cfg = config.get("log", {})
    level_str = log_cfg.get("level", "info").upper()
    max_bytes = log_cfg.get("max_size_mb", 10) * 1024 * 1024
    max_files = log_cfg.get("max_files", 3)
    from agent_mem0.config import LOG_DIR  # Lazy: avoid circular import
    default_log = str(LOG_DIR / "agent-mem0.log")
    log_path = Path(log_cfg.get("path", default_log)).expanduser()

    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("agent_mem0")
    logger.setLevel(getattr(logging, level_str, logging.INFO))
    logger.handlers.clear()

    handler = RotatingFileHandler(
        str(log_path),
        maxBytes=max_bytes,
        backupCount=max_files,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Get the global logger. Falls back to a basic logger if not yet setup."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("agent_mem0")
        if not _logger.handlers:
            _logger.addHandler(logging.NullHandler())
    return _logger


def log_memory_op(op: str, project: str, detail: str = "") -> None:
    """Log a memory operation (ADD/UPDATE/DELETE/SEARCH/NOOP)."""
    logger = get_logger()
    msg = f"MEMORY {op:8s} project={project}"
    if detail:
        msg += f"  {detail}"
    logger.info(msg)


def log_conflict(old_memory: str, new_memory: str, action: str) -> None:
    """Log a memory conflict resolution."""
    logger = get_logger()
    logger.info(f"CONFLICT action={action}  old=\"{old_memory}\"  new=\"{new_memory}\"")


def log_error(msg: str) -> None:
    """Log an error."""
    get_logger().error(msg)


def log_debug(msg: str) -> None:
    """Log debug information (MCP details, LLM timing, etc.)."""
    get_logger().debug(msg)
