#!/usr/bin/env python3
"""
app_paths.py - Locate application files whether running from source or frozen.

Under a PyInstaller one-file build the bundled sources are extracted to a
temporary directory, so ``__file__`` no longer points anywhere near the user's
profiles. The executable's own directory is the stable anchor instead.
"""

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory holding the INI profiles and the log file.

    Frozen: the folder containing the .exe. From source: the project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)
