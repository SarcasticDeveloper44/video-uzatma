"""Centralized logging — rotating file + console."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup(log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger("video_extender")
    if root.handlers:
        return root
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "video_extender.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(fh)
    return root


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"video_extender.{name}")
