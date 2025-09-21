#!/usr/bin/env python3
"""
logger.py
Console = compact (INFO), optional colors
File    = detailed (DEBUG), overwritten each run
"""

import colorama
import logging
import sys
from pathlib import Path

def setup_logger(
        name: str = "dcsmouse",
        logfile: str = "dcsmouse.log",
        *,
        console: bool = True,
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        color_console: bool = True,
) -> logging.Logger:

    logger = logging.getLogger(name)
    # Set logger level to the lower of the two so nothing gets filtered too early
    logger.setLevel(min(console_level, file_level))

    # Avoid duplicate handlers if called twice
    if logger.handlers:
        return logger

    # --- Formatters ---
    file_formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_fmt = "%(asctime)s.%(msecs)03d [%(levelname)-5s] %(message)s"
    console_datefmt = "%Y-%m-%d %H:%M:%S"

    # Try to add colors, but fall back silently if unavailable
    console_formatter = None
    if color_console:
        try:
            from colorama import Fore, Style, init as colorama_init
            colorama_init()

            class ColorFormatter(logging.Formatter):
                COLORS = {
                    "DEBUG": Fore.BLUE,
                    "INFO": Fore.GREEN,
                    "WARNING": Fore.YELLOW,
                    "ERROR": Fore.RED,
                    "CRITICAL": Fore.RED + Style.BRIGHT,
                }
                def format(self, record):
                    base = super().format(record)
                    color = self.COLORS.get(record.levelname, "")
                    reset = Style.RESET_ALL
                    return f"{color}{base}{reset}"

            console_formatter = ColorFormatter(console_fmt, datefmt=console_datefmt)
        except Exception:
            pass

    if console_formatter is None:
        console_formatter = logging.Formatter(console_fmt, datefmt=console_datefmt)

    # --- File handler (overwrite) ---
    log_path = Path(logfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(file_level)
    logger.addHandler(file_handler)

    # --- Console handler ---
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(console_level)
        logger.addHandler(console_handler)

    return logger
