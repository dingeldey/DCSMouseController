#!/usr/bin/env python3
"""
loggerutil.py
Utility for logging to console and file with consistent formatting.
File logging overwrites on each run (no append).
"""

import logging
import sys
from pathlib import Path

def setup_logger(
        name: str = "dcsmouse",
        logfile: str = "dcsmouse.log",
        level: int = logging.DEBUG,
        console: bool = True,
) -> logging.Logger:
    """
    Configure and return a logger.
    Logs to both file (overwrite) and console.
    """

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if called twice
    if logger.handlers:
        return logger

    # --- Formatter ---
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- File handler (overwrite mode) ---
    log_path = Path(logfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    # --- Console handler ---
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    return logger
