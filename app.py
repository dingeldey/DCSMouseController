#!/usr/bin/env python3
"""
app.py - Single entry point bundling the GUI and the mapper runtime.

The one-file executable contains both halves. Started normally it opens the
profile editor; started with the ``--run-mapper`` sentinel as the first
argument it runs the mapper instead, which is how the GUI re-launches itself
as a child process (see ``ControllerMapperApp.toggle_runtime``).
"""

import sys

RUN_MAPPER_FLAG = "--run-mapper"


def _attach_console() -> None:
    """Give the frozen mapper a console for its device dump and prompts.

    A windowed build starts with no console and ``sys.stdout`` set to None, so
    the runtime's prints and ``msvcrt.getch()`` would have nowhere to go.
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32
    if kernel32.GetConsoleWindow():
        return
    if not kernel32.AllocConsole():
        return

    sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == RUN_MAPPER_FLAG:
        del sys.argv[1]  # hide the sentinel from the runtime's argparse
        if getattr(sys, "frozen", False):
            _attach_console()
        import main as runtime

        runtime.main()
    else:
        import gui

        gui.main()


if __name__ == "__main__":
    main()
