#!/usr/bin/env python3
# Joystick/Throttle → Mouse Position Repeater (multi-device, GUID-aware, modifier layer, per-monitor/window, recenter)
# Windows-friendly (SendInput), pygame-based
#
# Highlights:
# - Per-binding device selection to mix multiple controllers:
#     devIdx:<index>:button:<btn>[M|:M]       |   dev:<GUID>:button:<btn>[M|:M]
#     devIdx:<index>:axis:<axis>[M|:M]        |   dev:<GUID>:axis:<axis>[M|:M]
#     devIdx:<index>:axis:<a>:<pos|neg|abs>:<thr>[M|:M]
#     dev:<GUID>:axis:<a>:<pos|neg|abs>:<thr>[M|:M]
# - Multiple bindings per action (comma-separated lists in INI):
#     • Buttons/axis-thresholds are OR’ed
#     • Analog axes (axis_x/axis_y) add their contributions together
# - Modifier layer behavior (global modifier button):
#     • Modifier DOWN  → only bindings with M/:M are active
#     • Modifier UP    → only bindings without M/:M are active
#     • No modifier configured → M/:M bindings never activate
# - Hold-acceleration for button/axis-threshold nudges (time-based ramp)
# - Unknown GUID devices are gracefully ignored (bindings skipped with a warning).
# - Optional (Windows-only) window focus + centering/clamping on toggle-ON (see INI).
# - Dedicated OFF binding removed. Use only `button_toggle` (edge-triggered).
#
# Notes:
# - Buttons in INI are 1-based (Windows style). Axes are 0-based (as printed at startup).
# - Append M either as a suffix (…:button:12M) or as a token (…:button:12:M) to require the modifier.
#
# CLI:
#   python DCSMouseController.py --config myprofile.ini
#   DCSMouseController.exe -c myprofile.ini
#
# Requires: pygame, pyautogui
#   pip install pygame pyautogui

import sys
import time
from pathlib import Path
import argparse
import configparser
import ctypes
import ctypes.wintypes as wt
import platform
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List

import pygame
import pyautogui

DEFAULT_CONFIG_FILE = "joystick_mouse.ini"

# ===== Windows virtual desktop + SendInput + Window helpers =====
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

def _enable_dpi_awareness():
    if platform.system().lower() != "windows":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # Per-Monitor V2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()    # System DPI
            except Exception:
                pass

def win_virtual_desktop_rect():
    user32 = ctypes.windll.user32
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return int(vx), int(vy), int(vw), int(vh)

# Monitor enumeration
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
                ("szDevice", ctypes.c_wchar * 32)]

MONITORINFOF_PRIMARY = 0x00000001
HMONITOR = ctypes.c_void_p
HDC = ctypes.c_void_p
LPRECT = ctypes.POINTER(RECT)
LPARAM = ctypes.c_long
MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, HMONITOR, HDC, LPRECT, LPARAM)

def win_enumerate_monitors():
    user32 = ctypes.windll.user32
    monitors = []
    def _cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        x = mi.rcMonitor.left; y = mi.rcMonitor.top
        w = mi.rcMonitor.right - mi.rcMonitor.left
        h = mi.rcMonitor.bottom - mi.rcMonitor.top
        primary = bool(mi.dwFlags & MONITORINFOF_PRIMARY)
        monitors.append({"hmon": hmon, "x": x, "y": y, "w": w, "h": h,
                         "primary": primary, "name": mi.szDevice})
        return 1
    cb = MONITORENUMPROC(_cb)
    if not user32.EnumDisplayMonitors(None, None, cb, 0):
        return []
    for i, m in enumerate(monitors): m["index"] = i
    return monitors

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_cursor_pos_virtual():
    pt = POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

# SendInput structures
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                ("time", ctypes.c_uint), ("dwExtraInfo", ctypes.c_void_p)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("mi", _MOUSEINPUT)]

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN  = 0x0002
MOUSEEVENTF_LEFTUP    = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP   = 0x0010
MOUSEEVENTF_WHEEL     = 0x0800
WHEEL_DELTA = 120

def sendinput_move_absolute_virtual(x_px, y_px):
    vx, vy, vw, vh = win_virtual_desktop_rect()
    nx = int(round((x_px - vx) * 65535 / max(1, vw - 1)))
    ny = int(round((y_px - vy) * 65535 / max(1, vh - 1)))
    inp = _INPUT()
    inp.type = 0
    inp.mi = _MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, None)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

def send_mouse_button(button: str, down: bool, *, use_sendinput: bool):
    btn = button.lower()
    if platform.system().lower() == "windows" and use_sendinput:
        if btn == "left":
            flags = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
        elif btn == "right":
            flags = MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP
        else:
            return
        inp = _INPUT()
        inp.type = 0
        inp.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    else:
        try:
            if down: pyautogui.mouseDown(button=btn)
            else:    pyautogui.mouseUp(button=btn)
        except Exception:
            pass

def send_mouse_wheel(ticks: int, *, use_sendinput: bool):
    if ticks == 0:
        return
    if platform.system().lower() == "windows" and use_sendinput:
        delta = int(ticks) * WHEEL_DELTA
        inp = _INPUT()
        inp.type = 0
        inp.mi = _MOUSEINPUT(0, 0, delta, MOUSEEVENTF_WHEEL, 0, None)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    else:
        try:
            pyautogui.scroll(int(ticks))
        except Exception:
            pass

# ---- Window helpers (Windows only) ------------------------------------------
SW_RESTORE = 9

def _get_title(hwnd):
    buf_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if buf_len < 0:
        buf_len = 0
    buf = ctypes.create_unicode_buffer(buf_len + 1 if buf_len > 0 else 1024)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value

def _get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def _is_visible(hwnd):
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))

def _is_minimized(hwnd):
    return bool(ctypes.windll.user32.IsIconic(hwnd))

def _client_rect_screen(hwnd) -> Optional[Dict[str,int]]:
    rc = RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pts = (POINT * 2)()
    pts[0].x, pts[0].y = rc.left, rc.top
    pts[1].x, pts[1].y = rc.right, rc.bottom
    if ctypes.windll.user32.MapWindowPoints(hwnd, None, ctypes.byref(pts), 2) == 0:
        return None
    x = int(pts[0].x)
    y = int(pts[0].y)
    w = int(pts[1].x - pts[0].x)
    h = int(pts[1].y - pts[0].y)
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}

def _window_rect_screen(hwnd) -> Optional[Dict[str,int]]:
    rc = RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        w = int(rc.right - rc.left); h = int(rc.bottom - rc.top)
        if w > 0 and h > 0:
            return {"x": int(rc.left), "y": int(rc.top), "w": w, "h": h}
    return None

def find_window(target_title_substr: str, target_class: str, debug: bool=False) -> Optional[int]:
    if platform.system().lower() != "windows":
        return None
    u = ctypes.windll.user32
    EnumWindows = u.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    GetWindow = u.GetWindow
    GetWindowLongW = u.GetWindowLongW
    GWL_EXSTYLE = -20
    GW_OWNER = 4
    WS_EX_TOOLWINDOW = 0x00000080

    title_need = (target_title_substr or "").lower()
    class_need = (target_class or "")

    best = {"hwnd": None, "area": -1}

    def is_top_level_app(hwnd):
        if not _is_visible(hwnd): return False
        if GetWindow(hwnd, GW_OWNER): return False
        ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW: return False
        return True

    def cb(hwnd, lparam):
        if not is_top_level_app(hwnd):
            return True
        cls = _get_class(hwnd)
        ttl = _get_title(hwnd)
        if class_need:
            if cls != class_need:
                return True
        elif title_need:
            if title_need not in ttl.lower():
                return True
        rect = _client_rect_screen(hwnd) or _window_rect_screen(hwnd)
        if not rect:
            return True
        area = rect["w"] * rect["h"]
        if area > best["area"]:
            best["hwnd"] = hwnd
            best["area"] = area
            if debug:
                print(f"[WIN] candidate hwnd=0x{hwnd:08X} class='{cls}' title='{ttl}' area={area}")
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    if debug and best["hwnd"]:
        print(f"[WIN] chosen hwnd=0x{best['hwnd']:08X}")
    return best["hwnd"]

def focus_window(hwnd: int, restore_if_minimized: bool, force_foreground: bool, debug: bool=False) -> bool:
    if platform.system().lower() != "windows" or not hwnd:
        return False
    if restore_if_minimized and _is_minimized(hwnd):
        if debug: print("[WIN] Restoring minimized window...")
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
    ok = bool(ctypes.windll.user32.SetForegroundWindow(hwnd))
    if not ok and force_foreground:
        user32 = ctypes.windll.user32
        user32.keybd_event(0x12, 0, 0, 0)          # ALT down
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.keybd_event(0x12, 0, 0x0002, 0)     # ALT up
    if debug:
        print(f"[WIN] SetForegroundWindow → {'OK' if ok else 'FAILED'} (hwnd=0x{hwnd:08X})")
    return ok

# =======================================================

def init_pygame():
    pygame.init(); pygame.joystick.init()
    pygame.event.set_allowed(None)
    pygame.event.set_allowed([
        pygame.QUIT,
        pygame.JOYBUTTONDOWN,
        pygame.JOYBUTTONUP,
        pygame.JOYDEVICEADDED,
        pygame.JOYDEVICEREMOVED
    ])

def list_devices():
    count = pygame.joystick.get_count()
    print(f"[INFO] Found game controllers: {count}")
    devices = []; inst_to_idx = {}
    for i in range(count):
        js = pygame.joystick.Joystick(i); js.init()
        name = js.get_name()
        guid = js.get_guid() if hasattr(js, "get_guid") else "N/A"
        buttons = js.get_numbuttons()
        axes = js.get_numaxes() if hasattr(js, "get_numaxes") else 0
        hats = js.get_numhats() if hasattr(js, "get_numhats") else 0
        try: instance_id = js.get_instance_id()
        except AttributeError: instance_id = js.get_id()
        print(f"  Index={i:2d} | Buttons={buttons:3d} | Axes={axes:2d} | Hats={hats:2d} | GUID={guid} | Name='{name}'")
        if axes > 0:
            print(f"    -> Axis indices: 0 .. {axes-1}")
        devices.append((i, name, guid, buttons, instance_id))
        inst_to_idx[instance_id] = i
    return devices, inst_to_idx

def list_monitors_windows():
    mons = win_enumerate_monitors()
    if not mons:
        print("[WARN] Could not enumerate monitors; using primary from pyautogui.")
        sw, sh = pyautogui.size()
        return [{"index": 0, "x": 0, "y": 0, "w": sw, "h": sh, "primary": True, "name": "PRIMARY"}]
    print("[INFO] Monitors (Windows virtual desktop):")
    for m in mons:
        prim = "Yes" if m["primary"] else "No "
        print(f"  MonIdx={m['index']} | Primary={prim} | x={m['x']} y={m['y']} w={m['w']} h={m['h']} | Name='{m['name']}'")
    return mons

# ---------- Binding parsing ---------------------------------------------------

@dataclass
class Binding:
    kind: str                 # 'button' | 'axisbtn' | 'axis_analog'
    dev: int                  # pygame joystick index (0-based)
    btn: Optional[int] = None # for 'button' (0-based)
    axis: Optional[int] = None# for 'axisbtn'/'axis_analog' (0-based)
    dir: Optional[str] = None # 'pos'|'neg'|'abs' for 'axisbtn'
    thr: Optional[float] = None
    req_mod: bool = False

def _strip_reqmod(s: str) -> Tuple[str, bool]:
    """Accepts suffix 'M' or token ':M' (case-insensitive)."""
    s = s.strip()
    if not s:
        return "", False
    sl = s.lower()
    if sl.endswith(":m"):
        return s[:-2].rstrip(), True
    if sl.endswith("m"):
        return s[:-1].rstrip(), True
    return s, False

def parse_legacy_button_or_axis(value: str, default_dev: int, *, expect_axis_analog: bool=False) -> Optional[Binding]:
    # Legacy formats:
    #   - buttons: '12' or '12M' or '12:M'  (1-based button index on default device)
    #   - axis_x/axis_y: '0' or '0M' or '0:M' (0-based axis index on default device)
    if not value.strip():
        return None
    core, req = _strip_reqmod(value)
    if core == "":
        return None
    if core.isdigit():
        n = int(core)
        if expect_axis_analog:
            return Binding(kind="axis_analog", dev=default_dev, axis=n, req_mod=req)
        else:
            return Binding(kind="button", dev=default_dev, btn=(n-1), req_mod=req)  # 1-based → 0-based
    return None

def parse_any_binding(s: str, default_dev: int, resolve_dev_token, *,
                      allow_axis_analog: bool=True, allow_axisbtn: bool=True, allow_button: bool=True) -> Optional[Binding]:
    """
    Extended formats (device can be index or GUID):
      devIdx:<dev>:button:<btn>[M|:M]     |   dev:<GUID>:button:<btn>[M|:M]
      devIdx:<dev>:axis:<axis>[M|:M]      |   dev:<GUID>:axis:<axis>[M|:M]
      devIdx:<dev>:axis:<axis>:<pos|neg|abs>:<thr>[M|:M]
      dev:<GUID>:axis:<axis>:<pos|neg|abs>:<thr>[M|:M]
    Plus legacy fallback (see parse_legacy_button_or_axis).
    """
    s = s.strip()
    if not s:
        return None

    legacy = parse_legacy_button_or_axis(s, default_dev, expect_axis_analog=allow_axis_analog and not allow_button and not allow_axisbtn)
    if legacy is not None:
        return legacy

    core, req = _strip_reqmod(s)
    parts = [p.strip() for p in core.split(":") if p.strip()]
    if not parts:
        return None

    def is_dev_tag(tag: str) -> bool:
        t = tag.lower()
        return t in ("dev", "devidx", "index", "device")

    if is_dev_tag(parts[0]) and len(parts) >= 4 and parts[2].lower() == "button" and allow_button:
        dev_token = parts[1]
        dev = resolve_dev_token(dev_token)
        if dev is None:
            return None  # unknown GUID, skip
        btn_1b = int(parts[3])
        return Binding(kind="button", dev=dev, btn=(btn_1b-1), req_mod=req)

    if is_dev_tag(parts[0]) and len(parts) >= 4 and parts[2].lower() == "axis":
        dev_token = parts[1]
        dev = resolve_dev_token(dev_token)
        if dev is None:
            return None  # unknown GUID, skip
        if len(parts) == 4 and allow_axis_analog:
            axis = int(parts[3]); return Binding(kind="axis_analog", dev=dev, axis=axis, req_mod=req)
        if len(parts) == 6 and allow_axisbtn:
            axis = int(parts[3]); direction = parts[4].lower()
            if direction not in ("pos","neg","abs"):
                print(f"[ERROR] Invalid direction '{direction}' in '{s}'. Use pos|neg|abs."); sys.exit(1)
            thr = float(parts[5])
            if not (0.0 <= thr <= 1.0):
                print(f"[ERROR] Threshold out of range in '{s}'. Use 0..1."); sys.exit(1)
            return Binding(kind="axisbtn", dev=dev, axis=axis, dir=direction, thr=thr, req_mod=req)

    print(f"[ERROR] Could not parse binding '{s}'.")
    sys.exit(1)

def parse_binding_list(raw: str, default_dev: int, resolve_dev_token, *,
                       allow_axis_analog: bool, allow_axisbtn: bool, allow_button: bool) -> List[Binding]:
    """
    Accept a comma-separated list of bindings. Whitespace is ignored around commas.
    Empty input → empty list.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    items = [tok.strip() for tok in raw.split(",") if tok.strip()]
    result: List[Binding] = []
    for tok in items:
        b = parse_any_binding(tok, default_dev, resolve_dev_token,
                              allow_axis_analog=allow_axis_analog, allow_axisbtn=allow_axisbtn, allow_button=allow_button)
        if b is not None:
            result.append(b)
    return result

# ---------- Axis-as-button helper --------------------------------------------

def axis_to_button(js, axis_index, *, direction="pos", threshold=0.6,
                   hysteresis=0.1, prev_pressed=False) -> Tuple[bool, bool, bool, float]:
    """Return (pressed, edge_down, edge_up, value)."""
    try:
        v = float(js.get_axis(axis_index))
    except Exception:
        v = 0.0

    thr = float(max(0.0, min(1.0, threshold)))
    hys = float(max(0.0, min(thr, hysteresis)))

    def pressed_pos(val, prev):
        return val >= (thr if not prev else (thr - hys))
    def pressed_neg(val, prev):
        return val <= (-(thr) if not prev else -(thr - hys))
    def pressed_abs(val, prev):
        lim = thr if not prev else (thr - hys)
        return abs(val) >= lim

    if direction == "pos":
        pressed = pressed_pos(v, prev_pressed)
    elif direction == "neg":
        pressed = pressed_neg(v, prev_pressed)
    else:
        pressed = pressed_abs(v, prev_pressed)

    return pressed, (pressed and not prev_pressed), ((not pressed) and prev_pressed), v

# ---------- Config loading ----------------------------------------------------

def load_config(path: str, devices: List[tuple]) -> Dict[str, Any]:
    """
    devices: list of tuples (index, name, guid, buttons, instance_id) from list_devices()
    """
    p = Path(path).expanduser()
    if not p.exists():
        print(f"[ERROR] Config file '{p}' not found."); sys.exit(1)

    cfgp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None, strict=False)
    cfgp.read(p, encoding="utf-8")
    if "input" not in cfgp: print("[ERROR] Missing [input] section."); sys.exit(1)
    sec = cfgp["input"]

    def getbool(k, d): return sec.get(k, str(d)).strip().lower() in ("1","true","yes","y","on")
    def getint_or_none(k):
        v = sec.get(k, "").strip()
        return int(v) if (v and v.lstrip("+-").isdigit()) else None
    def f_or_none(k):
        s = sec.get(k, "").strip()
        if s == "": return None
        try: return float(s)
        except: print(f"[ERROR] '{k}' must be float."); sys.exit(1)

    # Build GUID → index map
    guid_to_index: Dict[str, int] = {}
    for idx, _name, guid, _buttons, _iid in devices:
        if isinstance(guid, str):
            guid_to_index[guid.lower()] = idx

    def resolve_dev_token_optional(token: str) -> Optional[int]:
        """Map numeric string → index; otherwise GUID → index if known.
           Unknown GUID → None (binding will be ignored)."""
        t = token.strip()
        if t.lstrip("+-").isdigit():
            return int(t)  # numeric devIdx as-is
        key = t.lower()
        if key in guid_to_index:
            return guid_to_index[key]
        print(f"[WARN] Unknown device GUID '{token}'; binding will be ignored.")
        return None

    # There is no primary device in the INI; default 0 is used only for legacy numeric entries.
    default_device_for_legacy = 0

    # Modifier (advanced only). Optional: if omitted, entries with 'M' will never activate.
    modifier_sel = sec.get("modifier", "").strip()
    modifier_dev = None
    modifier_button = None
    if modifier_sel:
        # Allow and ignore a trailing M / :M on the modifier line
        modifier_core, _ = _strip_reqmod(modifier_sel)
        parts = [s.strip() for s in modifier_core.split(":")]
        if len(parts) == 4 and parts[2].lower() == "button" and parts[0].lower() in ("dev","devidx","index"):
            dev_opt = resolve_dev_token_optional(parts[1])
            if dev_opt is None:
                print(f"[WARN] Modifier device '{parts[1]}' not found; modifier disabled.")
                modifier_dev = None
                modifier_button = None
            else:
                modifier_dev = dev_opt
                modifier_button_1b = int(parts[3])
                modifier_button = (modifier_button_1b - 1)
        else:
            print(f"[ERROR] modifier must be 'devIdx:<dev>:button:<btn>' or 'dev:<GUID>:button:<btn>'. Got '{modifier_sel}'."); sys.exit(1)

    # Helper for lists
    def PL(name, *, allow_axis_analog=False, allow_axisbtn=True, allow_button=True) -> List[Binding]:
        return parse_binding_list(
            sec.get(name, "").strip(),
            default_dev=default_device_for_legacy,
            resolve_dev_token=resolve_dev_token_optional,
            allow_axis_analog=allow_axis_analog,
            allow_axisbtn=allow_axisbtn,
            allow_button=allow_button
        )

    # Actions (NO dedicated 'off' anymore)
    lst_toggle = PL("button_toggle", allow_axisbtn=True, allow_button=True)
    if len(lst_toggle) == 0:
        print("[ERROR] 'button_toggle' is required."); sys.exit(1)

    lst_inc_x  = PL("button_inc_x", allow_axisbtn=True, allow_button=True)
    lst_dec_x  = PL("button_dec_x", allow_axisbtn=True, allow_button=True)
    lst_inc_y  = PL("button_inc_y", allow_axisbtn=True, allow_button=True)
    lst_dec_y  = PL("button_dec_y", allow_axisbtn=True, allow_button=True)

    lst_mouse_l = PL("button_mouse_left",  allow_axisbtn=True, allow_button=True)
    lst_mouse_r = PL("button_mouse_right", allow_axisbtn=True, allow_button=True)

    lst_wheel_up   = PL("button_wheel_up",   allow_axisbtn=True, allow_button=True)
    lst_wheel_down = PL("button_wheel_down", allow_axisbtn=True, allow_button=True)

    # Analog axis movement for X/Y (lists)
    lst_ax_x = PL("axis_x", allow_axis_analog=True, allow_axisbtn=False, allow_button=False)
    lst_ax_y = PL("axis_y", allow_axis_analog=True, allow_axisbtn=False, allow_button=False)

    # Per-axis deadzones/invert/velocity
    axis_deadzone_global = sec.getfloat("axis_deadzone", fallback=0.15)
    adx = f_or_none("axis_deadzone_x"); ady = f_or_none("axis_deadzone_y")
    axis_deadzone_x = float(adx if adx is not None else axis_deadzone_global)
    axis_deadzone_y = float(ady if ady is not None else axis_deadzone_global)
    axis_invert_x = getbool("axis_invert_x", False)
    axis_invert_y = getbool("axis_invert_y", False)
    axis_velocity = sec.getint("axis_velocity_px_s", fallback=800)

    axis_button_hysteresis = sec.getfloat("axis_button_hysteresis", fallback=0.10)

    # --- Hold-acceleration (buttons/axis-thresholds only) ---
    hold_accel_enable   = getbool("hold_accel_enable", False)
    hold_accel_after_ms = sec.getint("hold_accel_after_ms", fallback=400)
    hold_accel_ramp_ms  = sec.getint("hold_accel_ramp_ms",  fallback=1500)
    hold_accel_max      = sec.getfloat("hold_accel_max",    fallback=3.0)

    monitor_index = sec.getint("monitor_index", fallback=0)
    def f_or_none_pair(k):
        s = sec.get(k, "").strip()
        if s == "": return None
        try: return float(s)
        except: print(f"[ERROR] '{k}' must be float."); sys.exit(1)
    x_frac = f_or_none_pair("x_frac"); y_frac = f_or_none_pair("y_frac")
    x_px = getint_or_none("x"); y_px = getint_or_none("y")
    use_frac = (x_frac is not None and y_frac is not None)
    use_px = (x_px is not None and y_px is not None)
    if not (use_frac or use_px):
        print("[ERROR] Provide x_frac & y_frac or x & y."); sys.exit(1)

    poll_hz = max(10, sec.getint("poll_hz", fallback=250))
    startup_grace_ms = max(0, sec.getint("startup_grace_ms", fallback=200))
    repeat_ms = max(1, sec.getint("repeat_ms", fallback=1000))
    nudge_velocity = max(1, sec.getint("nudge_velocity_px_s", fallback=600))

    clamp_space = sec.get("clamp_space", "monitor").strip().lower()
    if clamp_space not in ("monitor", "virtual", "window"):
        clamp_space = "monitor"

    restore_on_off = getbool("restore_on_off", False)
    wiggle_one_pixel = getbool("wiggle_one_pixel", False)
    use_sendinput = getbool("use_sendinput", platform.system().lower()=="windows")
    toggle_feedback = getbool("toggle_feedback", True)
    log_apply = getbool("log_apply", False)
    debug_buttons = getbool("debug_buttons", False)
    debug_io = getbool("debug_io", False)

    wheel_rate = sec.getint("wheel_ticks_per_second", fallback=30)

    # Window targeting (Windows only)
    focus_on_toggle = getbool("focus_on_toggle", False)
    focus_window_title = sec.get("focus_window_title", fallback="").strip()
    focus_window_class = sec.get("focus_window_class", fallback="").strip()
    window_restore_if_minimized = getbool("window_restore_if_minimized", True)
    window_force_foreground = getbool("window_force_foreground", False)
    center_in_window_on_toggle = getbool("center_in_window_on_toggle", False)
    debug_window = getbool("debug_window", False)
    wx_frac = f_or_none("window_x_frac"); wy_frac = f_or_none("window_y_frac")
    wx_px = getint_or_none("window_x");  wy_px = getint_or_none("window_y")

    # Enforcement: if clamping to window, you MUST specify a target window
    if clamp_space == "window" and (not focus_window_title) and (not focus_window_class):
        print("[ERROR] clamp_space=window requires either 'focus_window_class' or 'focus_window_title' in the INI.")
        input("Press Enter to exit...")
        sys.exit(1)

    return {
        "modifier_dev": modifier_dev,
        "modifier_button": modifier_button,

        "bindings": {
            "toggle": lst_toggle,
            "inc_x": lst_inc_x, "dec_x": lst_dec_x,
            "inc_y": lst_inc_y, "dec_y": lst_dec_y,
            "mouse_left":  lst_mouse_l,
            "mouse_right": lst_mouse_r,
            "wheel_up":    lst_wheel_up,
            "wheel_down":  lst_wheel_down,
            "axis_x": lst_ax_x,
            "axis_y": lst_ax_y,
        },

        "axis_deadzone_x": float(axis_deadzone_x),
        "axis_deadzone_y": float(axis_deadzone_y),
        "axis_invert_x": bool(axis_invert_x),
        "axis_invert_y": bool(axis_invert_y),
        "axis_velocity": int(axis_velocity),
        "axis_button_hysteresis": float(axis_button_hysteresis),

        # Hold-accel config
        "hold_accel_enable": bool(hold_accel_enable),
        "hold_accel_after_ms": int(hold_accel_after_ms),
        "hold_accel_ramp_ms": int(hold_accel_ramp_ms),
        "hold_accel_max": float(hold_accel_max),

        "monitor_index": int(monitor_index),
        "x_frac": x_frac, "y_frac": y_frac, "x": x_px, "y": y_px,

        "poll_hz": poll_hz, "startup_grace_ms": startup_grace_ms, "repeat_ms": repeat_ms,
        "nudge_velocity": nudge_velocity,
        "clamp_space": clamp_space,  # 'monitor' | 'virtual' | 'window'
        "restore_on_off": restore_on_off,

        "wiggle_one_pixel": wiggle_one_pixel,
        "use_sendinput": use_sendinput,
        "toggle_feedback": toggle_feedback,
        "log_apply": log_apply,
        "debug_buttons": debug_buttons,
        "debug_io": debug_io,

        "wheel_rate": int(wheel_rate),

        # Window targeting:
        "focus_on_toggle": focus_on_toggle,
        "focus_window_title": focus_window_title,
        "focus_window_class": focus_window_class,
        "window_restore_if_minimized": window_restore_if_minimized,
        "window_force_foreground": window_force_foreground,
        "center_in_window_on_toggle": center_in_window_on_toggle,
        "debug_window": debug_window,
        "window_x_frac": wx_frac, "window_y_frac": wy_frac,
        "window_x": wx_px, "window_y": wy_px,
    }

# ---------- Runtime -----------------------------------------------------------

def clamp_target(x, y, mon, clamp_space: str, window_rect: Optional[Dict[str,int]]):
    if clamp_space == "virtual":
        if platform.system().lower() == "windows":
            vx, vy, vw, vh = win_virtual_desktop_rect()
            x = max(vx, min(vx + vw - 1, x))
            y = max(vy, min(vy + vh - 1, y))
        else:
            sw, sh = pyautogui.size()
            x = max(0, min(sw - 1, x))
            y = max(0, min(sh - 1, y))
    elif clamp_space == "window" and window_rect:
        x = max(window_rect["x"], min(window_rect["x"] + window_rect["w"] - 1, x))
        y = max(window_rect["y"], min(window_rect["y"] + window_rect["h"] - 1, y))
    else:  # monitor
        x = max(mon["x"], min(mon["x"] + mon["w"] - 1, x))
        y = max(mon["y"], min(mon["y"] + mon["h"] - 1, y))
    return x, y

def parse_args():
    p = argparse.ArgumentParser(add_help=True, description="Joystick/Throttle → Mouse controller")
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG_FILE, metavar="INI",
                   help=f"Path to configuration INI (default: {DEFAULT_CONFIG_FILE})")
    return p.parse_args()

def main():
    args = parse_args()
    ini_path = Path(args.config).expanduser()

    _enable_dpi_awareness()
    pyautogui.FAILSAFE = False
    init_pygame()

    print("========================================================================")
    print("  Joystick/Throttle → Mouse Position Repeater (multi-device, GUID-ready)")
    print("========================================================================")
    print(f"Config: {ini_path}")
    print("Pick a different INI at launch, e.g.:  DCSMouseController.exe --config myprofile.ini\n")

    devices, inst_to_idx = list_devices(); print()
    cfg = load_config(str(ini_path), devices)
    print("[OK] Loaded config.")

    # Monitors
    if platform.system().lower() == "windows":
        monitors = list_monitors_windows()
    else:
        sw, sh = pyautogui.size()
        monitors = [{"index": 0, "x": 0, "y": 0, "w": sw, "h": sh, "primary": True, "name": "PRIMARY"}]
        print("[INFO] Non-Windows: using primary screen only.")
    if not monitors: print("[ERROR] No monitors found."); sys.exit(1)

    mon_idx = cfg["monitor_index"]
    if not (0 <= mon_idx < len(monitors)):
        print(f"[WARN] monitor_index={mon_idx} out of range. Using 0."); mon_idx = 0
    mon = monitors[mon_idx]

    # -------- Open all referenced devices --------
    used_devs = set()
    for blist in cfg["bindings"].values():
        for b in blist:
            if isinstance(b, Binding):
                used_devs.add(b.dev)
    if cfg["modifier_button"] is not None and cfg["modifier_dev"] is not None:
        used_devs.add(cfg["modifier_dev"])

    if not used_devs:
        print("[ERROR] No devices referenced in bindings or modifier. Please specify devIdx:<n> or dev:<GUID> in your INI.")
        sys.exit(1)

    js_map: Dict[int, pygame.joystick.Joystick] = {}
    for dev in sorted(used_devs):
        try:
            j = pygame.joystick.Joystick(dev); j.init()
            js_map[dev] = j
        except Exception:
            print(f"[ERROR] Could not open device index {dev}."); sys.exit(1)

    # Modifier device object
    js_mod = js_map.get(cfg["modifier_dev"]) if cfg["modifier_button"] is not None else None

    print(f"[OK] Using monitor: MonIdx={mon['index']} ({'Primary' if mon['primary'] else 'Secondary'}) "
          f"x={mon['x']} y={mon['y']} w={mon['w']} h={mon['h']} Name='{mon['name']}'")

    # Base target (monitor-based initial)
    if cfg["x_frac"] is not None and cfg["y_frac"] is not None:
        base_x = int(round(mon["x"] + cfg["x_frac"] * mon["w"]))
        base_y = int(round(mon["y"] + cfg["y_frac"] * mon["h"]))
    else:
        base_x = int(mon["x"] + cfg["x"])
        base_y = int(mon["y"] + cfg["y"])
    base_x, base_y = clamp_target(base_x, base_y, mon, cfg["clamp_space"], None)
    target_x, target_y = base_x, base_y

    print(f"[OK] Base target: ({base_x}, {base_y}) | repeat {cfg['repeat_ms']} ms")
    print(f"[OK] Clamp space: {cfg['clamp_space']} "
          f"({'virtual desktop' if cfg['clamp_space']=='virtual' else ('window client area' if cfg['clamp_space']=='window' else 'selected monitor')})\n")

    # State
    pygame.event.clear()
    grace_until = time.monotonic() + (cfg["startup_grace_ms"] / 1000.0)
    repeat_interval = cfg["repeat_ms"] / 1000.0
    last_apply = time.monotonic()
    active = False
    saved_cursor = None
    wiggle_flip = False
    last_toggle = time.monotonic(); debounce_s = 0.15

    # --- Helper: modifier gating (layer behavior)
    def modifier_is_down():
        if cfg["modifier_button"] is None: return False
        try: return bool(js_mod.get_button(cfg["modifier_button"]))
        except Exception: return False

    def binding_active(b: Binding) -> bool:
        """Only allow non-mod bindings when modifier is UP, and only mod-required bindings when modifier is DOWN."""
        if not isinstance(b, Binding):
            return False
        if cfg["modifier_button"] is None:
            return not b.req_mod
        mod = modifier_is_down()
        return b.req_mod if mod else (not b.req_mod)

    # --- Button hold states per binding (since multiple bindings per action)
    btn_hold_state: Dict[Tuple[str,int], bool] = {}
    axbtn_prev: Dict[Tuple[str,int], bool] = {}  # previous pressed states for axis-as-button

    # Hold-accel timers (per direction)
    hold_started_at: Dict[str, Optional[float]] = {"inc_x": None, "dec_x": None, "inc_y": None, "dec_y": None}

    # Mouse & wheel
    wheel_accum = 0.0

    # Window targeting (active handle & rect)
    active_hwnd: Optional[int] = None
    active_winrect: Optional[Dict[str,int]] = None

    # Initialize per-binding states
    for name, blist in cfg["bindings"].items():
        for i, b in enumerate(blist):
            if b.kind == "button":
                btn_hold_state[(name, i)] = False
            elif b.kind == "axisbtn":
                axbtn_prev[(name, i)] = False

    def apply_cursor():
        x = target_x + (1 if (cfg["wiggle_one_pixel"] and wiggle_flip) else 0)
        y = target_y
        if cfg["use_sendinput"] and platform.system().lower() == "windows":
            sendinput_move_absolute_virtual(x, y)
        else:
            pyautogui.moveTo(x, y)

    def mouse_reconcile(side: str, want_down: bool):
        # side: "left" | "right"
        state = getattr(mouse_reconcile, "state", {"left": False, "right": False})
        prev = state[side]
        if want_down != prev:
            send_mouse_button(side, want_down, use_sendinput=cfg["use_sendinput"])
            state[side] = want_down
            if cfg["toggle_feedback"] or cfg["debug_io"]:
                print(f"[MOUSE] {side.upper()} {'DOWN' if want_down else 'UP'}")
        setattr(mouse_reconcile, "state", state)

    def compute_window_target(rect: Dict[str,int]) -> Tuple[int,int]:
        if cfg["window_x_frac"] is not None and cfg["window_y_frac"] is not None:
            wx = int(round(rect["x"] + cfg["window_x_frac"] * rect["w"]))
            wy = int(round(rect["y"] + cfg["window_y_frac"] * rect["h"]))
            return wx, wy
        if cfg["window_x"] is not None and cfg["window_y"] is not None:
            wx = int(rect["x"] + cfg["window_x"])
            wy = int(rect["y"] + cfg["window_y"])
            return wx, wy
        return rect["x"] + rect["w"]//2, rect["y"] + rect["h"]//2

    def toggle_on():
        nonlocal active, saved_cursor, last_apply, wiggle_flip, target_x, target_y
        nonlocal active_hwnd, active_winrect, base_x, base_y
        if active: return
        # capture cursor for optional restore
        if platform.system().lower() == "windows":
            saved_cursor = get_cursor_pos_virtual()
        else:
            pos = pyautogui.position(); saved_cursor = (int(pos[0]), int(pos[1]))

        # Try window targeting (Windows only)
        active_hwnd = None
        active_winrect = None
        if platform.system().lower() == "windows" and (cfg["focus_on_toggle"] or cfg["center_in_window_on_toggle"] or cfg["clamp_space"] == "window"):
            hwnd = find_window(cfg["focus_window_title"], cfg["focus_window_class"], debug=cfg.get("debug_window", False))
            if hwnd:
                if cfg["focus_on_toggle"]:
                    focus_window(hwnd, cfg["window_restore_if_minimized"], cfg["window_force_foreground"], debug=cfg.get("debug_window", False))
                    time.sleep(0.05)  # let it settle before reading rect
                rect = _client_rect_screen(hwnd) or _window_rect_screen(hwnd)
                if rect:
                    active_hwnd = hwnd
                    active_winrect = rect
                    if cfg.get("debug_window", False):
                        print(f"[WIN] client rect: x={rect['x']} y={rect['y']} w={rect['w']} h={rect['h']}")
                else:
                    if cfg.get("debug_window", False):
                        print("[WIN] Could not read client/window rect.")
            else:
                if cfg.get("debug_window", False):
                    print("[WIN] No matching window found.")

        # ALWAYS recenter when turning on
        if (cfg["clamp_space"] == "window" or cfg["center_in_window_on_toggle"]) and active_winrect is not None:
            bx, by = compute_window_target(active_winrect)
            base_x, base_y = clamp_target(bx, by, mon, "window", active_winrect)
        else:
            if cfg["x_frac"] is not None and cfg["y_frac"] is not None:
                bx = int(round(mon["x"] + cfg["x_frac"] * mon["w"]))
                by = int(round(mon["y"] + cfg["y_frac"] * mon["h"]))
            else:
                bx = int(mon["x"] + cfg["x"]); by = int(mon["y"] + cfg["y"])
            base_x, base_y = clamp_target(bx, by, mon, cfg["clamp_space"], active_winrect)

        target_x, target_y = base_x, base_y
        active = True
        if cfg["toggle_feedback"]: print("[TOGGLE] ACTIVE (recentered)")
        apply_cursor(); last_apply = time.monotonic(); wiggle_flip = not wiggle_flip

    def toggle_off():
        nonlocal active, last_apply, wiggle_flip, active_hwnd, active_winrect
        if not active: return
        active = False
        if cfg["toggle_feedback"]:
            print("[TOGGLE] INACTIVE" + (" (restoring)" if cfg["restore_on_off"] else ""))
        if cfg["restore_on_off"] and (saved_cursor is not None):
            x0, y0 = saved_cursor
            if platform.system().lower() == "windows" and cfg["use_sendinput"]:
                sendinput_move_absolute_virtual(x0, y0)
            else:
                pyautogui.moveTo(x0, y0)
        active_hwnd = None
        active_winrect = None
        last_apply = time.monotonic(); wiggle_flip = False

    def get_js_for(b: Binding) -> Optional[pygame.joystick.Joystick]:
        return js_map.get(b.dev) if isinstance(b, Binding) else None

    prev_time = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            dt = now - prev_time
            prev_time = now

            # ---------------- Button event processing ----------------
            toggled_this_event = False
            for event in pygame.event.get():
                if now < grace_until:
                    continue

                if event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                    ev_dev_id = getattr(event, "instance_id", getattr(event, "joy", None))
                    dev_idx = inst_to_idx.get(ev_dev_id, None)
                    if dev_idx is None:
                        continue
                    if cfg["debug_buttons"]:
                        edge = "DOWN" if event.type == pygame.JOYBUTTONDOWN else "UP  "
                        print(f"[DBG] {edge}: dev_index={dev_idx} btn={(event.button + 1) if hasattr(event,'button') else '?'} mod={'ON' if modifier_is_down() else 'off'}")

                    is_down = (event.type == pygame.JOYBUTTONDOWN)

                    # Walk every action that has button-type bindings
                    for name, blist in cfg["bindings"].items():
                        for i, b in enumerate(blist):
                            if b.kind != "button":
                                continue
                            if b.dev == dev_idx and hasattr(event, "button") and (event.button == b.btn):
                                if not binding_active(b):
                                    continue
                                if name == "toggle":
                                    if is_down and not toggled_this_event and (now - last_toggle) >= debounce_s:
                                        (toggle_off() if active else toggle_on()); last_toggle = now
                                        toggled_this_event = True
                                else:
                                    btn_hold_state[(name, i)] = is_down

                elif event.type == pygame.JOYDEVICEREMOVED:
                    ev_dev_id = getattr(event, "instance_id", None)
                    dev_idx = inst_to_idx.get(ev_dev_id, None)
                    if dev_idx in js_map:
                        print(f"[WARN] Device index {dev_idx} removed. Exiting.")
                        return

            # ---------- Axis-as-button polling (toggle/nudges/mouse/wheel)
            hys = cfg["axis_button_hysteresis"]

            toggled_this_tick = False
            def poll_axbtn_any(name: str) -> bool:
                nonlocal last_toggle, toggled_this_tick
                any_pressed = False
                for i, b in enumerate(cfg["bindings"].get(name, [])):
                    if b.kind != "axisbtn":
                        continue
                    if not binding_active(b):
                        axbtn_prev[(name, i)] = False
                        continue
                    js = get_js_for(b)
                    if js is None:
                        continue
                    prev_p = axbtn_prev.get((name, i), False)
                    pressed, ed, eu, val = axis_to_button(js, b.axis, direction=b.dir, threshold=b.thr,
                                                          hysteresis=hys, prev_pressed=prev_p)
                    axbtn_prev[(name, i)] = pressed
                    if cfg["debug_io"] and (ed or eu):
                        print(f"[AXBTN] {name}[{i}] {('DOWN' if ed else 'UP  ')} dev={b.dev} axis={b.axis} dir={b.dir} thr={b.thr:.2f} val={val:+.3f}")
                    if name == "toggle" and ed and not toggled_this_tick and (time.monotonic()-last_toggle) >= debounce_s:
                        (toggle_off() if active else toggle_on()); last_toggle = time.monotonic()
                        toggled_this_tick = True
                    any_pressed = any_pressed or pressed
                return any_pressed

            _ = poll_axbtn_any("toggle")

            hold_inc_x_axb = poll_axbtn_any("inc_x")
            hold_dec_x_axb = poll_axbtn_any("dec_x")
            hold_inc_y_axb = poll_axbtn_any("inc_y")
            hold_dec_y_axb = poll_axbtn_any("dec_y")

            mouse_axis_left  = poll_axbtn_any("mouse_left")
            mouse_axis_right = poll_axbtn_any("mouse_right")

            wheel_axis_up   = poll_axbtn_any("wheel_up")
            wheel_axis_down = poll_axbtn_any("wheel_down")

            # ---------- Aggregate button-hold states per action
            def any_btn(name: str) -> bool:
                return any(btn_hold_state.get((name, i), False)
                           for i, b in enumerate(cfg["bindings"].get(name, []))
                           if b.kind == "button")

            hold_inc_x_btn = any_btn("inc_x")
            hold_dec_x_btn = any_btn("dec_x")
            hold_inc_y_btn = any_btn("inc_y")
            hold_dec_y_btn = any_btn("dec_y")

            mouse_btn_left  = any_btn("mouse_left")
            mouse_btn_right = any_btn("mouse_right")

            wheel_btn_up   = any_btn("wheel_up")
            wheel_btn_down = any_btn("wheel_down")

            # ---------- Combined hold flags (button OR axis-threshold)
            hold_flags = {
                "inc_x": (hold_inc_x_btn or hold_inc_x_axb),
                "dec_x": (hold_dec_x_btn or hold_dec_x_axb),
                "inc_y": (hold_inc_y_btn or hold_inc_y_axb),
                "dec_y": (hold_dec_y_btn or hold_dec_y_axb),
            }

            # Update hold timers for acceleration
            for key, held in hold_flags.items():
                if held:
                    if hold_started_at[key] is None:
                        hold_started_at[key] = now
                else:
                    hold_started_at[key] = None

            # Helper to compute accel multiplier for a given direction key
            def accel_mult_for(key: str) -> float:
                if not cfg["hold_accel_enable"]:
                    return 1.0
                t0 = hold_started_at.get(key)
                if t0 is None:
                    return 1.0
                ms = (now - t0) * 1000.0
                if ms <= cfg["hold_accel_after_ms"]:
                    return 1.0
                ramp_ms = max(1.0, float(cfg["hold_accel_ramp_ms"]))
                prog = min(1.0, (ms - cfg["hold_accel_after_ms"]) / ramp_ms)
                return 1.0 + (cfg["hold_accel_max"] - 1.0) * prog

            # ---------- BUTTON-BASED MOVEMENT with acceleration
            vx = (1 if hold_flags["inc_x"] else 0) - (1 if hold_flags["dec_x"] else 0)
            vy = (1 if hold_flags["inc_y"] else 0) - (1 if hold_flags["dec_y"] else 0)

            mult_x = 1.0
            if vx > 0:   mult_x = accel_mult_for("inc_x")
            elif vx < 0: mult_x = accel_mult_for("dec_x")

            mult_y = 1.0
            if vy > 0:   mult_y = accel_mult_for("inc_y")
            elif vy < 0: mult_y = accel_mult_for("dec_y")

            step_x_btn = int(round(vx * cfg["nudge_velocity"] * mult_x * dt))
            step_y_btn = int(round(vy * cfg["nudge_velocity"] * mult_y * dt))

            # ---------- AXIS-BASED MOVEMENT (analog) — sum contributions (no accel)
            step_x_axis = 0
            step_y_axis = 0

            for b in cfg["bindings"].get("axis_x", []):
                if b.kind != "axis_analog" or not binding_active(b):
                    continue
                js = get_js_for(b)
                if js is None:
                    continue
                try:
                    axv = float(js.get_axis(b.axis))
                    if cfg["axis_invert_x"]: axv = -axv
                    if abs(axv) < cfg["axis_deadzone_x"]: axv = 0.0
                    step = int(round(axv * cfg["axis_velocity"] * dt))
                    step_x_axis += step
                    if cfg["debug_io"] and step != 0:
                        print(f"[AXIS] X dev={b.dev} axis={b.axis} val={axv:+.3f} step={step}")
                except Exception:
                    pass

            for b in cfg["bindings"].get("axis_y", []):
                if b.kind != "axis_analog" or not binding_active(b):
                    continue
                js = get_js_for(b)
                if js is None:
                    continue
                try:
                    ayv = float(js.get_axis(b.axis))
                    if cfg["axis_invert_y"]: ayv = -ayv
                    if abs(ayv) < cfg["axis_deadzone_y"]: ayv = 0.0
                    step = int(round(ayv * cfg["axis_velocity"] * dt))
                    step_y_axis += step
                    if cfg["debug_io"] and step != 0:
                        print(f"[AXIS] Y dev={b.dev} axis={b.axis} val={ayv:+.3f} step={step}")
                except Exception:
                    pass

            # If clamping to window and active, refresh window rect (window may move/resize)
            if cfg["clamp_space"] == "window" and active and platform.system().lower() == "windows" and active_hwnd:
                rect = _client_rect_screen(active_hwnd) or _window_rect_screen(active_hwnd)
                if rect:
                    active_winrect = rect

            # ---------- APPLY MOVEMENT
            step_x = step_x_btn + step_x_axis
            step_y = step_y_btn + step_y_axis
            if step_x != 0 or step_y != 0:
                target_x += step_x; target_y += step_y
                target_x, target_y = clamp_target(target_x, target_y, mon, cfg["clamp_space"], active_winrect)
                if cfg["debug_io"]:
                    print(f"[MOVE] dx={step_x:+d} dy={step_y:+d} → target=({target_x},{target_y})")
                if active:
                    apply_cursor(); last_apply = now; wiggle_flip = not wiggle_flip

            # ---------- MOUSE BUTTONS (aggregate axis+button)
            mouse_reconcile("left",  mouse_btn_left  or mouse_axis_left)
            mouse_reconcile("right", mouse_btn_right or mouse_axis_right)

            # ---------- WHEEL (continuous while held; aggregate axis+button)
            net_rate = 0.0
            if wheel_btn_up or wheel_axis_up:     net_rate += cfg["wheel_rate"]
            if wheel_btn_down or wheel_axis_down: net_rate -= cfg["wheel_rate"]
            if net_rate != 0.0:
                wheel_accum += net_rate * dt
                ticks = int(wheel_accum)
                if ticks != 0:
                    send_mouse_wheel(ticks, use_sendinput=cfg["use_sendinput"])
                    if cfg["debug_io"]:
                        print(f"[WHEEL] ticks={ticks} (accum={wheel_accum:.2f})")
                    wheel_accum -= ticks

            # ---------- Periodic re-apply
            if active and (now - last_apply) >= repeat_interval:
                apply_cursor(); last_apply = now; wiggle_flip = not wiggle_flip
                if cfg["log_apply"]:
                    shown_x = target_x + (1 if (cfg["wiggle_one_pixel"] and wiggle_flip) else 0)
                    print(f"[APPLY] {shown_x},{target_y} @ {now:.3f}")

            time.sleep(1.0 / float(cfg["poll_hz"]))

    except KeyboardInterrupt:
        print("\n[EXIT] User aborted.")
    finally:
        pygame.joystick.quit(); pygame.quit()

if __name__ == "__main__":
    main()
