#!/usr/bin/env python3
"""
mousecontroller.py
Utility for controlling the mouse (absolute, relative, monitor/window aware).
Windows-only. Supports VR by sending relative deltas via SendInput.
"""

import ctypes
import ctypes.wintypes as wt
import win32api

user32 = ctypes.windll.user32

# --- Constants for input ---
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

MOUSEEVENTF_LEFTDOWN   = 0x0002
MOUSEEVENTF_LEFTUP     = 0x0004
MOUSEEVENTF_RIGHTDOWN  = 0x0008
MOUSEEVENTF_RIGHTUP    = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP   = 0x0040
MOUSEEVENTF_WHEEL      = 0x0800
MOUSEEVENTF_HWHEEL     = 0x01000

INPUT_MOUSE = 0
DWORD = ctypes.wintypes.DWORD
LONG = ctypes.wintypes.LONG
ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

# --- Structs ---
class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", LONG),
                ("dy", LONG),
                ("mouseData", DWORD),
                ("dwFlags", DWORD),
                ("time", DWORD),
                ("dwExtraInfo", ULONG_PTR))

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", DWORD),
                ("_input", _INPUT)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


# --- Mouse Controller ---
class MouseController:
    def __init__(self, log=None):
        self.log = log
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    # existing set_position_pixels, set_position_frac, etc.

    @staticmethod
    def get_monitor_handle(index: int):
        """Return handle to the monitor by index (0-based)."""
        monitors = []

        def callback(hmon, hdc, lprect, lparam):
            monitors.append(hmon)
            return True

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.wintypes.HMONITOR,
            ctypes.wintypes.HDC, ctypes.POINTER(RECT),
            ctypes.wintypes.LPARAM
        )
        user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(callback), 0)

        if 0 <= index < len(monitors):
            return monitors[index]
        return None

    def set_position_monitor_frac(self, monitor_index: int, fx: float, fy: float):
        """Move mouse to fraction of a specific monitor."""
        hmon = self.get_monitor_handle(monitor_index)
        if not hmon:
            return
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            x0, y0 = mi.rcMonitor.left, mi.rcMonitor.top
            w = mi.rcMonitor.right - x0
            h = mi.rcMonitor.bottom - y0
            abs_x = int(x0 + fx * w)
            abs_y = int(y0 + fy * h)
            self.set_position_pixels(abs_x, abs_y)

    def set_position_monitor_px(self, monitor_index: int, px: int, py: int):
        """Move mouse to absolute pixel offset inside a specific monitor."""
        hmon = self.get_monitor_handle(monitor_index)
        if not hmon:
            return
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            x0, y0 = mi.rcMonitor.left, mi.rcMonitor.top
            w = mi.rcMonitor.right - x0
            h = mi.rcMonitor.bottom - y0
            abs_x = int(x0 + min(max(px, 0), w - 1))
            abs_y = int(y0 + min(max(py, 0), h - 1))
            self.set_position_pixels(abs_x, abs_y)


    # --- Virtual desktop positioning ---
    def set_position_pixels(self, x: int, y: int):
        """Absolute move to desktop pixel coords."""
        user32.SetCursorPos(x, y)
        self.log.debug(f"[MOUSE] Set position pixels: ({x},{y})")

    def set_position_frac(self, fx: float, fy: float):
        """Absolute move to fraction [0..1] of virtual desktop."""
        x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        abs_x = int(x + fx * w)
        abs_y = int(y + fy * h)
        self.set_position_pixels(abs_x, abs_y)

    # --- Relative movement (VR safe) ---
    def move_relative(self, dx: int, dy: int):
        """Send relative mouse movement (like a real mouse)."""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    # --- New helper: move along one axis ---
    def move_axis(self, axis: str, amount: int = 5):
        """Move mouse a little along one axis (used for bindings)."""
        if axis.lower() == "x":
            self.move_relative(amount, 0)
        elif axis.lower() == "y":
            self.move_relative(0, amount)
        else:
            self.log.warning(f"[MOUSE] Unsupported move axis: {axis}")

    # --- Click buttons ---
    def click(self, button: str):
        mapping = {
            "MB1": 0x0002,  # MOUSEEVENTF_LEFTDOWN
            "MB2": 0x0008,  # MOUSEEVENTF_RIGHTDOWN
            "MB3": 0x0020,  # MOUSEEVENTF_MIDDLEDOWN
            "MB4": 0x0080,  # MOUSEEVENTF_XDOWN (XBUTTON1)
            "MB5": 0x0100,  # MOUSEEVENTF_XDOWN (XBUTTON2)
        }
        up_mapping = {
            "MB1": 0x0004,  # LEFTUP
            "MB2": 0x0010,  # RIGHTUP
            "MB3": 0x0040,  # MIDDLEUP
            "MB4": 0x0100,  # XUP (XBUTTON1)
            "MB5": 0x0200,  # XUP (XBUTTON2)
        }

        down_flag = mapping.get(button)
        up_flag   = up_mapping.get(button)
        if not down_flag:
            return

        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, 0, down_flag, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        inp.mi = MOUSEINPUT(0, 0, 0, up_flag, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


    # --- Wheel scroll ---
    def wheel(self, direction: str):
        """Simulate mouse wheel scroll."""
        if direction == "WheelUp":
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, 120, 0)
        elif direction == "WheelDown":
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -120, 0)
        else:
            self.log.warning(f"[MOUSE] Unsupported wheel direction: {direction}")
            return
        self.log.debug(f"[MOUSE] Wheel {direction}")

    # --- Window helpers ---
    @staticmethod
    def find_window(title: str = None, class_name: str = None):
        """Find a window by title and/or class name."""
        if not title and not class_name:
            raise ValueError("Need at least title or class_name")
        hwnd = user32.FindWindowW(class_name, title)
        return hwnd if hwnd else None

    @staticmethod
    def list_windows():
        """Return list of (hwnd, class_name, title) for all top-level windows."""
        windows = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, ctypes.POINTER(ctypes.c_int))
        def foreach_window(hwnd, lParam):
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)

            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)

            windows.append((hwnd, class_buf.value, title_buf.value))
            return True

        user32.EnumWindows(foreach_window, 0)
        return windows

    @staticmethod
    def get_window_rect(hwnd):
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def set_position_window_frac(self, hwnd=None, title=None, class_name=None, fx=0.5, fy=0.5):
        if hwnd is None:
            hwnd = self.find_window(title=title, class_name=class_name)
        if not hwnd:
            return
        x,y,w,h = self.get_window_rect(hwnd)
        abs_x = int(x + fx * w)
        abs_y = int(y + fy * h)
        self.set_position_pixels(abs_x, abs_y)

