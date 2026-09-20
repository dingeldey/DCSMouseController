#!/usr/bin/env python3
"""
main.py - Entry point for DCS Mouse Controller
"""

from utils.controller.detector import InputDetector
from utils.controller.executor import InputExecutor
from utils.controller.bindings import InputConfig, KeyMapConfig, AxisMapConfig
from utils.app_paths import app_dir
from utils.file.inireader import IniReader
from utils.controller.keymapper import KeyMapper
from utils.controller.mousecontroller import MouseController
from utils.logger.logger import setup_logger

import sys
import time
import atexit
import configparser
import ctypes
import ctypes.wintypes as wt
from pathlib import Path
import msvcrt
import logging
import argparse


def check_single_instance(mutex_name="DCSMouseControllerMutex"):
    """Ensure only one instance of this program runs."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(None, False, mutex_name)

    # ERROR_ALREADY_EXISTS = 183
    last_error = kernel32.GetLastError()
    if last_error == 183:
        kernel32.CloseHandle(handle)
        print("Another instance is already running.")
        print("Press any key to exit...")
        msvcrt.getch()
        sys.exit(1)

    # Release the mutex deterministically on exit instead of relying on the
    # OS to reclaim it at process teardown.
    atexit.register(kernel32.CloseHandle, handle)

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
def _last_config_marker() -> Path:
    return app_dir() / ".last_config"


def _load_last_config(log) -> str | None:
    try:
        return _last_config_marker().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
    except Exception as e:
        log.debug(f"Could not read last-used config marker: {e}")
        return None


def _save_last_config(path: str, log) -> None:
    try:
        _last_config_marker().write_text(path, encoding="utf-8")
    except Exception as e:
        log.warning(
            f"Could not remember last-used config ({e}); you'll be prompted to "
            f"pick a profile again next run"
        )


def select_config_file(explicit: str | None, log):
    if explicit:
        # Resolve so a relative --config still matches the absolute paths
        # ini_files/last_config compare against on a later run.
        _save_last_config(str(Path(explicit).resolve()), log)
        return explicit

    # Look for *.ini files next to the application
    ini_files = sorted(app_dir().glob("*.ini"))
    if not ini_files:
        log.error(f"No INI configuration files found in {app_dir()}.")
        raise SystemExit(1)

    if len(ini_files) == 1:
        log.info(f"Found only one config: {ini_files[0]}")
        _save_last_config(str(ini_files[0]), log)
        return str(ini_files[0])

    # Multiple INIs → reuse the last-selected one if it's still present
    last = _load_last_config(log)
    if last and any(str(f) == last for f in ini_files):
        log.info(f"Using last-selected config: {last} (pass --config to pick a different one)")
        return last

    # Otherwise let the user choose
    print("\nAvailable config files:")
    for idx, f in enumerate(ini_files, start=1):
        print(f"  {idx}. {f.name}")
    while True:
        try:
            choice = int(input("Select config file [1-{}]: ".format(len(ini_files))))
            if 1 <= choice <= len(ini_files):
                chosen = str(ini_files[choice - 1])
                _save_last_config(chosen, log)
                return chosen
        except Exception:
            pass
        print("Invalid choice, try again.")


# ----------------------------------------------------------------------
# Main runner
# ----------------------------------------------------------------------
def run_main(log, cfgfile):
    try:
        cfg = IniReader(cfgfile, log)
    except (FileNotFoundError, OSError, UnicodeDecodeError, configparser.Error) as e:
        log.error(f"Could not load config file {cfgfile}: {e}")
        raise SystemExit(1)

    # List windows at startup
    list_top_level_windows(log)

    input_cfg = InputConfig.from_ini(cfg, log)
    keymaps = KeyMapConfig.from_ini(cfg, log)
    axismaps = AxisMapConfig.from_ini(cfg, log)

    detector = InputDetector(log, input_cfg, keymaps + axismaps)
    keymapper = KeyMapper(log)
    mouse = MouseController(log, center_mode=input_cfg.center_mode)
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

    # 1) Parse CLI first so `args` exists
    parser = argparse.ArgumentParser(description="DCS Mouse Controller")
    parser.add_argument("--config", "-c", type=str, default=None,
                        help="INI config file (default: pick automatically)")
    args = parser.parse_args()

    # 2) Logger
    log = setup_logger(
        "dcsmouse",
        logfile="log.log",
        console=True,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        color_console=True,
    )
    log.info("Starting DCS Mouse Controller")

    # 3) Claim DPI awareness before anything creates a window (SDL/pygame
    #    included) - Windows only allows this to be set once per process.
    MouseController.set_dpi_awareness()

    # 4) Early device dump (before INI selection)
    try:
        import pygame
        pygame.init()
        pygame.joystick.init()

        count = pygame.joystick.get_count()
        if count == 0:
            log.info("[DEVICE] No controllers detected")
        else:
            for i in range(count):
                js = pygame.joystick.Joystick(i)
                js.init()

                try:
                    guid = js.get_guid()
                except AttributeError:
                    guid = f"index-{i}"

                name = js.get_name()
                log.info(
                    f"[DEVICE] Joystick {i}: name={name!r} GUID={guid} Buttons={js.get_numbuttons()} Axes={js.get_numaxes()}"
                )

                log.info(
                    "[DEVICE] Joystick %d\n"
                    "         Name : %r\n"
                    "         GUID : %s\n"
                    "         Btns : %d  Axes : %d",
                    i,
                    name,
                    guid,
                    js.get_numbuttons(),
                    js.get_numaxes(),
                )
    except Exception as e:
        log.warning(f"[DEVICE] Enumeration failed: {e}")

    # 5) Now select INI and run
    cfgfile = select_config_file(args.config, log)
    run_main(log, cfgfile)


if __name__ == "__main__":
    main()
