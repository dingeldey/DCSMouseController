#!/usr/bin/env python3
"""
mousecontroller.py
Utility for controlling the mouse (absolute, relative, monitor/window aware).
Windows-only. Supports VR by sending relative deltas via SendInput, including
an opt-in relative centering mode for games that integrate mouse deltas.
"""

import ctypes
import ctypes.wintypes as wt
import os
import time
import win32api

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wt.HWND

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
    def __init__(self, log=None, center_mode: str = "absolute"):
        """center_mode selects how CenterMouse places the cursor:

        "absolute" - a single SetCursorPos warp (default, cheapest).
        "relative" - synthesise the placement from SendInput relative moves,
                     so a game that integrates raw mouse deltas for its own
                     cursor (DCS in VR) follows along; see center_at_pixels.

        Anything unrecognised falls back to "absolute" - this class is also
        constructed without an InputConfig to validate the value first.
        """
        self.log = log
        mode = str(center_mode).strip().lower() if center_mode is not None else ""
        self.center_mode = "relative" if mode == "relative" else "absolute"
        self.set_dpi_awareness()

    @staticmethod
    def set_dpi_awareness():
        """Make this process DPI-aware so window rects reported by other
        processes (e.g. DCS) are accurate on multi-monitor / mixed-DPI setups.

        Prefers per-monitor-v2 (Windows 10 1703+) and falls back through the
        older APIs for earlier Windows versions.

        Windows only lets a process set its DPI awareness once; call this as
        early as possible (main.py does, before pygame.init()), since SDL's
        video subsystem may otherwise claim a less accurate setting first.
        Safe to call again here for callers that construct MouseController
        without going through main.py - a second call is a harmless no-op.
        """
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except (AttributeError, OSError):
            pass
        try:
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            if ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                return
        except (AttributeError, OSError):
            pass
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

    def button_down(self, button: str):
        mapping = {
            "MB1": 0x0002,  # LEFTDOWN
            "MB2": 0x0008,  # RIGHTDOWN
            "MB3": 0x0020,  # MIDDLEDOWN
            "MB4": 0x0080,  # XDOWN (XBUTTON1)
            "MB5": 0x0100,  # XDOWN (XBUTTON2)
        }
        flag = mapping.get(button)
        if not flag:
            return
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, 0, flag, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def button_up(self, button: str):
        mapping = {
            "MB1": 0x0004,  # LEFTUP
            "MB2": 0x0010,  # RIGHTUP
            "MB3": 0x0040,  # MIDDLEUP
            "MB4": 0x0100,  # XUP (XBUTTON1)
            "MB5": 0x0200,  # XUP (XBUTTON2)
        }
        flag = mapping.get(button)
        if not flag:
            return
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, 0, flag, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def set_position_window_px(self, hwnd=None, title=None, class_name=None, x=0, y=0):
        """Move mouse to absolute pixel coordinates inside a specific window's client area."""
        if hwnd is None:
            hwnd = self.find_window(title=title, class_name=class_name)
        if not hwnd:
            return
        wx, wy, ww, wh = self.get_client_rect_screen(hwnd)
        if ww <= 0 or wh <= 0:
            if self.log:
                self.log.warning(f"[MOUSE] Window {hwnd} has no client area (minimized or gone)")
            return
        abs_x = int(wx + min(max(x, 0), ww - 1))
        abs_y = int(wy + min(max(y, 0), wh - 1))
        self.center_at_pixels(abs_x, abs_y)

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
            self.center_at_pixels(abs_x, abs_y)

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
            self.center_at_pixels(abs_x, abs_y)


    # --- Virtual desktop positioning ---
    def set_position_pixels(self, x: int, y: int):
        """Absolute move to desktop pixel coords."""
        user32.SetCursorPos(x, y)
        if self.log:
            self.log.debug(f"[MOUSE] Set position pixels: ({x},{y})")

    def set_position_frac(self, fx: float, fy: float):
        """Absolute move to fraction [0..1] of virtual desktop."""
        x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        abs_x = int(x + fx * w)
        abs_y = int(y + fy * h)
        self.center_at_pixels(abs_x, abs_y)

    # --- Relative movement (VR safe) ---
    def move_relative(self, dx: int, dy: int):
        """Send relative mouse movement (like a real mouse)."""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    # --- Centering (honours center_mode) ---
    def center_at_pixels(self, x: int, y: int):
        """Place the cursor at desktop pixel coords for a CenterMouse action.

        Unlike set_position_pixels (a bare SetCursorPos, still used by the
        absolute axis mode, wiggle and increments), this honours center_mode
        so VR users can opt into a placement the game actually sees.
        """
        if self.center_mode != "relative":
            self.set_position_pixels(x, y)
        else:
            self._center_relative(x, y)

    def _read_cursor(self):
        """Return the OS cursor position, once queued input has been applied.

        SendInput returns as soon as the events are queued, not once they have
        moved the cursor, so a GetCursorPos issued straight after a move still
        reports the old position. The short sleep lets the input thread drain
        the queue first. Both callers are edge-triggered (one placement per
        button press), so this is not in a hot path.

        Raises OSError if GetCursorPos fails - e.g. when this process is not
        on the input desktop. That has to raise rather than be ignored: on
        failure the POINT is left at (0, 0), and treating that as the cursor
        position would inject a large bogus relative move.

        No error code is included: user32 here is a plain ctypes.windll handle
        (not use_last_error), so there is no code saved for us to read, and a
        GetLastError() issued afterwards could report an unrelated error.
        """
        time.sleep(0.002)
        pt = wt.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            raise OSError("GetCursorPos failed")
        return pt

    def _center_relative(self, x: int, y: int):
        """Place the cursor at (x, y) using only relative SendInput moves.

        SetCursorPos warps the OS cursor without emitting any input event, so
        a game that tracks its own cursor by integrating raw mouse deltas
        never sees it. Here we instead:

          1. Slam far toward the top-left, so both the OS cursor and the
             delta-integrating consumer clamp at their respective origins.
          2. Read where the OS cursor actually landed (that origin may be the
             game window, if the game confines the cursor).
          3. Send one delta from there to the target.

        There is deliberately no correction loop: with Windows "Enhance
        pointer precision" on, the applied delta is scaled non-linearly, and
        driving the OS cursor onto the target with further corrections would
        push the consumer's cursor further off. We warn instead.

        Called from the main input loop, which has no exception handling, so
        this must not raise; on failure we fall back to the absolute warp.
        """
        tx, ty = int(x), int(y)
        try:
            w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

            # 2x tolerates a consumer running at 0.5x sensitivity; the +200
            # covers a degenerate metric. Chunked so no single event carries
            # an implausibly large delta.
            chunks = 4
            dx_chunk = -(2 * int(w) + 200) // chunks
            dy_chunk = -(2 * int(h) + 200) // chunks
            for _ in range(chunks):
                self.move_relative(dx_chunk, dy_chunk)

            pt = self._read_cursor()
            dx = tx - pt.x
            dy = ty - pt.y
            self.move_relative(dx, dy)

            after = self._read_cursor()
            err_x = tx - after.x
            err_y = ty - after.y

            if self.log:
                self.log.debug(
                    f"[MOUSE] Relative center: target=({tx},{ty}) "
                    f"origin=({pt.x},{pt.y}) delta=({dx},{dy})"
                )
            if abs(err_x) > 2 or abs(err_y) > 2:
                if self.log:
                    self.log.warning(
                        f"[MOUSE] Relative center landed off target: "
                        f"target=({tx},{ty}) landed=({after.x},{after.y}); "
                        f"likely causes are Windows 'Enhance pointer precision' "
                        f"(pointer acceleration) being on, the pointer speed "
                        f"slider not at its default middle notch, or the target "
                        f"lying outside the screen or the game's cursor clip "
                        f"rect - or set center_mode = absolute in [input]"
                    )
        except Exception as e:
            if self.log:
                self.log.warning(
                    f"[MOUSE] Relative center failed ({e}); falling back to absolute"
                )
            self.set_position_pixels(tx, ty)

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
    def click(self, button: str, hold_ms: int = 30):
        """
        Simulate a full click (DOWN+UP) for MB1–MB5.
        MB1 = left, MB2 = right, MB3 = middle, MB4 = X1, MB5 = X2.
        hold_ms = how long to hold the button down before releasing (default 30 ms).
        """
        btn = button.upper()

        if btn == "MB1":
            down, up, data = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0
        elif btn == "MB2":
            down, up, data = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0
        elif btn == "MB3":
            down, up, data = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0
        elif btn == "MB4":
            down, up, data = 0x0800, 0x1000, 0x0001  # XDOWN/XUP + XBUTTON1
        elif btn == "MB5":
            down, up, data = 0x0800, 0x1000, 0x0002  # XDOWN/XUP + XBUTTON2
        else:
            if self.log:
                self.log.warning(f"[MOUSE] Unsupported button: {button}")
            return

        # send DOWN
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, data, down, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # keep it pressed for hold_ms
        time.sleep(hold_ms / 1000.0)

        # send UP
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, data, up, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        if self.log:
            self.log.debug(f"[MOUSE] Clicked {btn} (held {hold_ms}ms)")

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
    def find_window(self, title: str = None, class_name: str = None):
        """Find a window by title and/or class name.

        Tries an exact match first (fast path). If that fails, falls back to
        a case-insensitive scan across all top-level windows - preferring an
        exact (case-insensitive) match, then a substring match - since the
        real window class/title (see the "[WIN] CLASS=... TITLE=..." lines
        logged at startup) often differs slightly from whatever was typed
        into the INI. This is a common reason CenterMouse/FocusWindow do
        nothing against a game window. The fallback scan skips windows
        belonging to this process, so it can't grab our own console; the
        exact-match fast path above has no such exclusion.
        """
        if not title and not class_name:
            if self.log:
                self.log.warning("[MOUSE] find_window called with no title or class_name")
            return None

        hwnd = user32.FindWindowW(class_name, title)
        if hwnd:
            return hwnd

        title_l = title.lower() if title else None
        class_l = class_name.lower() if class_name else None
        own_pid = os.getpid()

        exact, partial = [], []
        for cand_hwnd, cand_class, cand_title in self.list_windows():
            cand_class_l = cand_class.lower()
            cand_title_l = cand_title.lower()

            if class_l and class_l not in cand_class_l:
                continue
            if title_l and title_l not in cand_title_l:
                continue

            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(cand_hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                continue

            candidate = (cand_hwnd, cand_class, cand_title)
            if (class_l is None or class_l == cand_class_l) and (title_l is None or title_l == cand_title_l):
                exact.append(candidate)
            else:
                partial.append(candidate)

        candidates = exact or partial
        if not candidates:
            if self.log:
                self.log.warning(
                    f"[MOUSE] No window found matching class={class_name!r} title={title!r}"
                )
            return None

        chosen_hwnd, chosen_class, chosen_title = candidates[0]
        if self.log:
            if len(candidates) > 1:
                self.log.warning(
                    f"[MOUSE] Multiple windows match class={class_name!r} title={title!r}; "
                    f"using hwnd={chosen_hwnd} class={chosen_class!r} title={chosen_title!r}"
                )
            else:
                self.log.debug(
                    f"[MOUSE] Matched window hwnd={chosen_hwnd} class={chosen_class!r} title={chosen_title!r}"
                )
        return chosen_hwnd

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
    def get_client_rect_screen(hwnd):
        """Return (x, y, w, h) of the window's client area in screen coords.

        This excludes the title bar and borders, so a 0.5/0.5 fraction lands
        in the middle of the actual play area.
        """
        rect = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = wt.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return (pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top)

    def set_position_window_frac(self, hwnd=None, title=None, class_name=None, fx=0.5, fy=0.5):
        """Move mouse to a fraction of a specific window's client area."""
        if hwnd is None:
            hwnd = self.find_window(title=title, class_name=class_name)
        if not hwnd:
            return
        x, y, w, h = self.get_client_rect_screen(hwnd)
        if w <= 0 or h <= 0:
            if self.log:
                self.log.warning(f"[MOUSE] Window {hwnd} has no client area (minimized or gone)")
            return
        abs_x = int(x + fx * w)
        abs_y = int(y + fy * h)
        self.center_at_pixels(abs_x, abs_y)

