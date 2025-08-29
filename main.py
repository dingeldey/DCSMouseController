from utils.controller.detector import InputDetector
from utils.controller.executor import InputExecutor
from utils.controller.bindings import InputConfig, KeyMapConfig, AxisMapConfig
from utils.file.inireader import IniReader
from utils.controller.keymapper import KeyMapper
from utils.controller.mousecontroller import MouseController
from utils.logger.logger import setup_logger
import time


import ctypes
import ctypes.wintypes as wt

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

def run_main(log):
    # Init configs, devices

    cfg = IniReader("default.ini")
    input_cfg = InputConfig.from_ini(cfg)
    keymaps = KeyMapConfig.from_ini(cfg)
    axismaps = AxisMapConfig.from_ini(cfg)

    detector = InputDetector(log, input_cfg, keymaps + axismaps)

    # Now also list windows
    list_top_level_windows(log)

    keymapper = KeyMapper(log)
    mouse = MouseController(log)
    executor = InputExecutor(log, keymapper, mouse, input_cfg)

    log.info(f"Loaded {len(keymaps)} key mappings and {len(axismaps)} axis mappings")

    # Main loop
    frame_dt = 1.0 / max(1, input_cfg.axis_poll_hz)
    while True:
        events = detector.poll()
        for ev in events:
            executor.handle_event(ev)

        # IMPORTANT: update once per frame to drive wheel hold-to-scroll
        executor.update()
        time.sleep(frame_dt)

def main():
    log = setup_logger("dcsmouse", logfile="log.log")
    log.info("Starting DCS Mouse Controller")

    run_main(log)

if __name__ == "__main__":
    main()