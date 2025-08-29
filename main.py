#!/usr/bin/env python3
"""
main.py - Entry point for DCS Mouse Controller
"""

import argparse
import sys
import time
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

from utils.controller.detector import InputDetector
from utils.controller.executor import InputExecutor
from utils.controller.bindings import InputConfig, KeyMapConfig, AxisMapConfig
from utils.file.inireader import IniReader
from utils.controller.keymapper import KeyMapper
from utils.controller.mousecontroller import MouseController
from utils.logger.logger import setup_logger

def check_single_instance(mutex_name="DCSMouseControllerMutex"):
    """Ensure only one instance of this program runs."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, mutex_name)

    # ERROR_ALREADY_EXISTS = 183
    last_error = kernel32.GetLastError()
    if last_error == 183:
        print("Another instance is already running.")
        sys.exit(1)

# ----------------------------------------------------------------------
# Window lister helper
# ----------------------------------------------------------------------
def list_top_level_windows(log):
    user32 = ctypes.windll.user32

    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetClassNameW = user32.GetClassNameW
    IsWindowVisible = user32.IsWindowVisible
    GetWindow = user32.GetWindow
    GetWindowLongW = user32.GetWindowLongW

    GW_OWNER = 4
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def is_top_level_app(hwnd):
        if not IsWindowVisible(hwnd):
            return False
        if GetWindow(hwnd, GW_OWNER):  # has owner
            return False
        ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return False
        return True

    def enum_cb(hwnd, lParam):
        if not is_top_level_app(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(max(1, length + 1))
        GetWindowTextW(hwnd, title_buf, len(title_buf))
        class_buf = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, class_buf, 256)
        log.info(
            f"[WIN] HWND=0x{hwnd:08X}  CLASS='{class_buf.value}'  TITLE='{title_buf.value}'"
        )
        return True

    log.info("[WIN] Listing top-level windows...")
    EnumWindows(EnumWindowsProc(enum_cb), 0)
    log.info("[WIN] Done listing windows.")


# ----------------------------------------------------------------------
# Config selector
# ----------------------------------------------------------------------
def select_config_file(explicit: str | None, log):
    if explicit:
        return explicit

    # Look for *.ini files in current directory
    ini_files = sorted(Path(".").glob("*.ini"))
    if not ini_files:
        log.error("No INI configuration files found in current directory.")
        raise SystemExit(1)

    if len(ini_files) == 1:
        log.info(f"Found only one config: {ini_files[0]}")
        return str(ini_files[0])

    # Multiple INIs → let user choose
    print("\nAvailable config files:")
    for idx, f in enumerate(ini_files, start=1):
        print(f"  {idx}. {f.name}")
    while True:
        try:
            choice = int(input("Select config file [1-{}]: ".format(len(ini_files))))
            if 1 <= choice <= len(ini_files):
                return str(ini_files[choice - 1])
        except Exception:
            pass
        print("Invalid choice, try again.")


# ----------------------------------------------------------------------
# Main runner
# ----------------------------------------------------------------------
def run_main(log, cfgfile):
    cfg = IniReader(cfgfile)

    # List windows at startup
    list_top_level_windows(log)

    input_cfg = InputConfig.from_ini(cfg)
    keymaps = KeyMapConfig.from_ini(cfg, log)
    axismaps = AxisMapConfig.from_ini(cfg, log)

    detector = InputDetector(log, input_cfg, keymaps + axismaps)
    keymapper = KeyMapper(log)
    mouse = MouseController(log)
    executor = InputExecutor(log, keymapper, mouse, input_cfg)

    # Count invalid bindings (device not found)
    invalid = 0
    for bm in keymaps + axismaps:
        js = detector._resolve_device(bm.input)
        if js is None:
            invalid += 1

    log.info(
        f"Loaded {len(keymaps)} key mappings and {len(axismaps)} axis mappings "
        f"({invalid} invalid bindings)"
    )


    frame_dt = 1.0 / max(1, input_cfg.axis_poll_hz)
    while True:
        events = detector.poll()
        for ev in events:
            executor.handle_event(ev)
        executor.update()
        time.sleep(frame_dt)


def main():
    check_single_instance()
    parser = argparse.ArgumentParser(description="DCS Mouse Controller")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="INI config file (default: ask user if multiple exist)",
    )
    args = parser.parse_args()

    log = setup_logger("dcsmouse", logfile="log.log")
    log.info("Starting DCS Mouse Controller")

    cfgfile = select_config_file(args.config, log)
    run_main(log, cfgfile)


if __name__ == "__main__":
    main()
