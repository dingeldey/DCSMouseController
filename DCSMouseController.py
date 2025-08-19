#!/usr/bin/env python3
# Joystick/Throttle → Mouse Position Repeater (multi-device, GUID-aware, modifier, per-monitor, recenter)
# Windows-friendly (SendInput), pygame-based
#
# Highlights:
# - Per-binding device selection to mix multiple controllers:
#     devIdx:<index>:button:<btn>[M]       |   dev:<GUID>:button:<btn>[M]
#     devIdx:<index>:axis:<axis>[M]        |   dev:<GUID>:axis:<axis>[M]
#     devIdx:<index>:axis:<axis>:<pos|neg|abs>:<thr>[M]
#     dev:<GUID>:axis:<axis>:<pos|neg|abs>:<thr>[M]
# - Explicit modifier definition (advanced only):
#     modifier = devIdx:<index>:button:<btn>
#     modifier = dev:<GUID>:button:<btn>
# - No global "primary device" in the INI. (Legacy numeric-only entries default to device 0.)
# - Dedicated OFF binding removed. Use only `button_toggle` (edge-triggered).
#
# Notes:
# - Buttons in INI are 1-based (Windows style). Axes are 0-based (as printed at startup).
# - Append 'M' to any binding to require the modifier to be held.
#
# Requires: pygame, pyautogui
#   pip install pygame pyautogui

import sys
import time
from pathlib import Path
import configparser
import ctypes
import platform
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List

import pygame
import pyautogui

CONFIG_FILE = "joystick_mouse.ini"

# ===== Windows virtual desktop + SendInput helpers =====
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

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
    s = s.strip()
    if not s: return "", False
    if s[-1].lower() == 'm':
        return s[:-1], True
    return s, False

def parse_legacy_button_or_axis(value: str, default_dev: int, *, expect_axis_analog: bool=False) -> Optional[Binding]:
    # Legacy formats:
    #   - buttons: '12' or '12M'  (1-based button index on default device)
    #   - axis_x/axis_y: '0' or '0M' (0-based axis index on default device)
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
      devIdx:<dev>:button:<btn>[M]     |   dev:<GUID>:button:<btn>[M]
      devIdx:<dev>:axis:<axis>[M]      |   dev:<GUID>:axis:<axis>[M]
      devIdx:<dev>:axis:<axis>:<pos|neg|abs>:<thr>[M]
      dev:<GUID>:axis:<axis>:<pos|neg|abs>:<thr>[M]
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
        btn_1b = int(parts[3])
        return Binding(kind="button", dev=dev, btn=(btn_1b-1), req_mod=req)

    if is_dev_tag(parts[0]) and len(parts) >= 4 and parts[2].lower() == "axis":
        dev_token = parts[1]
        dev = resolve_dev_token(dev_token)
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
    if not Path(path).exists():
        print(f"[ERROR] Config file '{path}' not found."); sys.exit(1)
    cfgp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None, strict=False)
    cfgp.read(path, encoding="utf-8")
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

    def resolve_dev_token(token: str) -> int:
        """Map numeric string → index; otherwise treat as GUID (exact, case-insensitive)."""
        t = token.strip()
        if t.lstrip("+-").isdigit():
            return int(t)
        key = t.lower()
        if key in guid_to_index:
            return guid_to_index[key]
        print(f"[ERROR] Unknown device token '{token}'. Not a number or known GUID.")
        sys.exit(1)

    # There is no primary device in the INI; default 0 is used only for legacy numeric entries.
    default_device_for_legacy = 0

    # Modifier (advanced only). Optional: if omitted, entries with 'M' will never activate.
    modifier_sel = sec.get("modifier", "").strip()
    modifier_dev = None
    modifier_button = None
    if modifier_sel:
        parts = [s.strip() for s in modifier_sel.split(":")]
        if len(parts) == 4 and parts[2].lower() == "button" and parts[0].lower() in ("dev","devidx","index"):
            modifier_dev = resolve_dev_token(parts[1])
            modifier_button_1b = int(parts[3])
            modifier_button = (modifier_button_1b - 1)
        else:
            print(f"[ERROR] modifier must be 'devIdx:<dev>:button:<btn>' or 'dev:<GUID>:button:<btn>'. Got '{modifier_sel}'."); sys.exit(1)

    # Axis analog movement (support legacy or extended)
    axis_x_raw = sec.get("axis_x", "").strip()
    axis_y_raw = sec.get("axis_y", "").strip()

    def PA(name, *, allow_axis_analog=False, allow_axisbtn=True, allow_button=True):
        return parse_any_binding(
            sec.get(name, "").strip(),
            default_dev=default_device_for_legacy,
            resolve_dev_token=resolve_dev_token,
            allow_axis_analog=allow_axis_analog,
            allow_axisbtn=allow_axisbtn,
            allow_button=allow_button
        )

    # Actions (NO dedicated 'off' anymore)
    b_toggle = PA("button_toggle", allow_axisbtn=True, allow_button=True)
    if b_toggle is None:
        print("[ERROR] 'button_toggle' is required."); sys.exit(1)

    b_inc_x  = PA("button_inc_x", allow_axisbtn=True, allow_button=True)
    b_dec_x  = PA("button_dec_x", allow_axisbtn=True, allow_button=True)
    b_inc_y  = PA("button_inc_y", allow_axisbtn=True, allow_button=True)
    b_dec_y  = PA("button_dec_y", allow_axisbtn=True, allow_button=True)

    b_mouse_l = PA("button_mouse_left",  allow_axisbtn=True, allow_button=True)
    b_mouse_r = PA("button_mouse_right", allow_axisbtn=True, allow_button=True)

    b_wheel_up   = PA("button_wheel_up",   allow_axisbtn=True, allow_button=True)
    b_wheel_down = PA("button_wheel_down", allow_axisbtn=True, allow_button=True)

    # Analog axis movement for X/Y (accept legacy or extended)
    def parse_axis_analog(raw: str):
        if not raw: return None
        if raw.strip().lower().startswith(("dev:", "devidx:", "index:", "device:")):
            return parse_any_binding(raw, default_dev=default_device_for_legacy,
                                     resolve_dev_token=resolve_dev_token,
                                     allow_axis_analog=True, allow_axisbtn=False, allow_button=False)
        else:
            return parse_legacy_button_or_axis(raw, default_device_for_legacy, expect_axis_analog=True)

    ax_x = parse_axis_analog(axis_x_raw)
    ax_y = parse_axis_analog(axis_y_raw)

    # Per-axis deadzones/invert/velocity
    axis_deadzone_global = sec.getfloat("axis_deadzone", fallback=0.15)
    adx = f_or_none("axis_deadzone_x"); ady = f_or_none("axis_deadzone_y")
    axis_deadzone_x = float(adx if adx is not None else axis_deadzone_global)
    axis_deadzone_y = float(ady if ady is not None else axis_deadzone_global)
    axis_invert_x = getbool("axis_invert_x", False)
    axis_invert_y = getbool("axis_invert_y", False)
    axis_velocity = sec.getint("axis_velocity_px_s", fallback=800)

    axis_button_hysteresis = sec.getfloat("axis_button_hysteresis", fallback=0.10)

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
    if clamp_space not in ("monitor", "virtual"):
        clamp_space = "monitor"

    restore_on_off = getbool("restore_on_off", False)
    wiggle_one_pixel = getbool("wiggle_one_pixel", False)
    use_sendinput = getbool("use_sendinput", platform.system().lower()=="windows")
    toggle_feedback = getbool("toggle_feedback", True)
    log_apply = getbool("log_apply", False)
    debug_buttons = getbool("debug_buttons", False)
    debug_io = getbool("debug_io", False)

    wheel_rate = sec.getint("wheel_ticks_per_second", fallback=30)

    return {
        "modifier_dev": modifier_dev,
        "modifier_button": modifier_button,

        "bindings": {
            "toggle": b_toggle,
            "inc_x": b_inc_x, "dec_x": b_dec_x,
            "inc_y": b_inc_y, "dec_y": b_dec_y,
            "mouse_left":  b_mouse_l,
            "mouse_right": b_mouse_r,
            "wheel_up":    b_wheel_up,
            "wheel_down":  b_wheel_down,
            "axis_x": ax_x,
            "axis_y": ax_y,
        },

        "axis_deadzone_x": float(axis_deadzone_x),
        "axis_deadzone_y": float(axis_deadzone_y),
        "axis_invert_x": bool(axis_invert_x),
        "axis_invert_y": bool(axis_invert_y),
        "axis_velocity": int(axis_velocity),
        "axis_button_hysteresis": float(axis_button_hysteresis),

        "monitor_index": int(monitor_index),
        "x_frac": x_frac, "y_frac": y_frac, "x": x_px, "y": y_px,

        "poll_hz": poll_hz, "startup_grace_ms": startup_grace_ms, "repeat_ms": repeat_ms,
        "nudge_velocity": nudge_velocity,
        "clamp_space": clamp_space, "clamp_virtual": (clamp_space == "virtual"),
        "restore_on_off": restore_on_off,

        "wiggle_one_pixel": wiggle_one_pixel,
        "use_sendinput": use_sendinput,
        "toggle_feedback": toggle_feedback,
        "log_apply": log_apply,
        "debug_buttons": debug_buttons,
        "debug_io": debug_io,

        "wheel_rate": int(wheel_rate),
    }

# ---------- Runtime -----------------------------------------------------------

def clamp_target(x, y, mon, clamp_virtual):
    if clamp_virtual:
        if platform.system().lower() == "windows":
            vx, vy, vw, vh = win_virtual_desktop_rect()
            x = max(vx, min(vx + vw - 1, x))
            y = max(vy, min(vy + vh - 1, y))
        else:
            sw, sh = pyautogui.size()
            x = max(0, min(sw - 1, x))
            y = max(0, min(sh - 1, y))
    else:
        x = max(mon["x"], min(mon["x"] + mon["w"] - 1, x))
        y = max(mon["y"], min(mon["y"] + mon["h"] - 1, y))
    return x, y

def main():
    pyautogui.FAILSAFE = False
    init_pygame()

    print("========================================================================")
    print("  Joystick/Throttle → Mouse Position Repeater (multi-device, GUID-ready)")
    print("========================================================================")
    print("Pick a different INI at launch:  DCSMouseController.exe --config myprofile.ini\n")
    devices, inst_to_idx = list_devices(); print()

    cfg = load_config(CONFIG_FILE, devices)

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
    for b in cfg["bindings"].values():
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

    # Base target
    if cfg["x_frac"] is not None and cfg["y_frac"] is not None:
        base_x = int(round(mon["x"] + cfg["x_frac"] * mon["w"]))
        base_y = int(round(mon["y"] + cfg["y_frac"] * mon["h"]))
    else:
        base_x = int(mon["x"] + cfg["x"])
        base_y = int(mon["y"] + cfg["y"])
    base_x, base_y = clamp_target(base_x, base_y, mon, cfg["clamp_virtual"])
    target_x, target_y = base_x, base_y

    print(f"[OK] Base target: ({base_x}, {base_y}) | repeat {cfg['repeat_ms']} ms")
    print(f"[OK] Clamp space: {'virtual desktop' if cfg['clamp_virtual'] else 'selected monitor'}\n")

    # State
    pygame.event.clear()
    grace_until = time.monotonic() + (cfg["startup_grace_ms"] / 1000.0)
    repeat_interval = cfg["repeat_ms"] / 1000.0
    last_apply = time.monotonic()
    active = False
    saved_cursor = None
    wiggle_flip = False
    last_toggle = time.monotonic(); debounce_s = 0.15

    # Movement hold flags (from button and axisbtn)
    hold_inc_x_btn = hold_dec_x_btn = hold_inc_y_btn = hold_dec_y_btn = False
    hold_inc_x_axb = hold_dec_x_axb = hold_inc_y_axb = hold_dec_y_axb = False

    # Mouse and wheel aggregate states
    mouse_down_sent = {"left": False, "right": False}
    mouse_axis_pressed = {"left": False, "right": False}
    mouse_btn_pressed  = {"left": False, "right": False}
    wheel_axis_hold = {"up": False, "down": False}
    wheel_btn_hold  = {"up": False, "down": False}
    wheel_accum = 0.0

    # axis-as-button pressed states (per binding) for hysteresis
    axbtn_prev: Dict[Tuple[str], bool] = {}

    def modifier_is_down():
        if cfg["modifier_button"] is None: return False
        try: return bool(js_mod.get_button(cfg["modifier_button"]))
        except Exception: return False

    def apply_cursor():
        x = target_x + (1 if (cfg["wiggle_one_pixel"] and wiggle_flip) else 0)
        y = target_y
        if cfg["use_sendinput"] and platform.system().lower() == "windows":
            sendinput_move_absolute_virtual(x, y)
        else:
            pyautogui.moveTo(x, y)

    def mouse_reconcile(button: str, want_down: bool):
        if want_down and not mouse_down_sent[button]:
            send_mouse_button(button, True, use_sendinput=cfg["use_sendinput"])
            mouse_down_sent[button] = True
            if cfg["toggle_feedback"] or cfg["debug_io"]:
                print(f"[MOUSE] {button.upper()} DOWN")
        elif (not want_down) and mouse_down_sent[button]:
            send_mouse_button(button, False, use_sendinput=cfg["use_sendinput"])
            mouse_down_sent[button] = False
            if cfg["toggle_feedback"] or cfg["debug_io"]:
                print(f"[MOUSE] {button.upper()} UP")

    def toggle_on():
        nonlocal active, saved_cursor, last_apply, wiggle_flip, target_x, target_y
        if active: return
        if platform.system().lower() == "windows":
            saved_cursor = get_cursor_pos_virtual()
        else:
            pos = pyautogui.position(); saved_cursor = (int(pos[0]), int(pos[1]))
        target_x, target_y = base_x, base_y  # recenter on ON
        active = True
        if cfg["toggle_feedback"]: print("[TOGGLE] ACTIVE (recentered)")
        apply_cursor(); last_apply = time.monotonic(); wiggle_flip = not wiggle_flip

    def toggle_off():
        nonlocal active, last_apply, wiggle_flip
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
        last_apply = time.monotonic(); wiggle_flip = False

    def get_js_for(b: Binding) -> Optional[pygame.joystick.Joystick]:
        return js_map.get(b.dev) if isinstance(b, Binding) else None

    prev_time = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            dt = now - prev_time
            prev_time = now

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

                    for name, b in cfg["bindings"].items():
                        if not isinstance(b, Binding) or b.kind != "button": continue
                        if b.dev == dev_idx and hasattr(event, "button") and (event.button == b.btn):
                            if b.req_mod and not modifier_is_down():
                                continue
                            if name == "toggle":
                                if is_down and (now - last_toggle) >= debounce_s:
                                    (toggle_off() if active else toggle_on()); last_toggle = now
                            elif name == "inc_x":   hold_inc_x_btn = is_down
                            elif name == "dec_x":   hold_dec_x_btn = is_down
                            elif name == "inc_y":   hold_inc_y_btn = is_down
                            elif name == "dec_y":   hold_dec_y_btn = is_down
                            elif name == "mouse_left":
                                mouse_btn_pressed["left"] = is_down
                                mouse_reconcile("left", mouse_btn_pressed["left"] or mouse_axis_pressed["left"])
                            elif name == "mouse_right":
                                mouse_btn_pressed["right"] = is_down
                                mouse_reconcile("right", mouse_btn_pressed["right"] or mouse_axis_pressed["right"])
                            elif name == "wheel_up":
                                wheel_btn_hold["up"] = is_down
                            elif name == "wheel_down":
                                wheel_btn_hold["down"] = is_down

                elif event.type == pygame.JOYDEVICEREMOVED:
                    ev_dev_id = getattr(event, "instance_id", None)
                    dev_idx = inst_to_idx.get(ev_dev_id, None)
                    if dev_idx in js_map:
                        print(f"[WARN] Device index {dev_idx} removed. Exiting.")
                        return

            # ---------- Axis-as-button polling (toggle/nudges/mouse/wheel)
            hys = cfg["axis_button_hysteresis"]
            def poll_axbtn(name: str) -> bool:
                nonlocal last_toggle, active
                b = cfg["bindings"].get(name)
                if not isinstance(b, Binding) or b.kind != "axisbtn": return False
                if b.req_mod and not modifier_is_down():
                    axbtn_prev[(name,)] = False
                    return False
                js = get_js_for(b)
                if js is None: return False
                prev_p = axbtn_prev.get((name,), False)
                pressed, ed, eu, val = axis_to_button(js, b.axis, direction=b.dir, threshold=b.thr,
                                                      hysteresis=hys, prev_pressed=prev_p)
                axbtn_prev[(name,)] = pressed
                if cfg["debug_io"] and (ed or eu):
                    print(f"[AXBTN] {name} {('DOWN' if ed else 'UP  ')} dev={b.dev} axis={b.axis} dir={b.dir} thr={b.thr:.2f} val={val:+.3f}")
                if name == "toggle" and ed and (time.monotonic()-last_toggle) >= debounce_s:
                    (toggle_off() if active else toggle_on()); last_toggle = time.monotonic()
                return pressed

            _ = poll_axbtn("toggle")

            hold_inc_x_axb = poll_axbtn("inc_x")
            hold_dec_x_axb = poll_axbtn("dec_x")
            hold_inc_y_axb = poll_axbtn("inc_y")
            hold_dec_y_axb = poll_axbtn("dec_y")

            mouse_axis_pressed["left"]  = poll_axbtn("mouse_left")
            mouse_axis_pressed["right"] = poll_axbtn("mouse_right")
            mouse_reconcile("left",  mouse_btn_pressed["left"]  or mouse_axis_pressed["left"])
            mouse_reconcile("right", mouse_btn_pressed["right"] or mouse_axis_pressed["right"])

            wheel_axis_hold["up"]   = poll_axbtn("wheel_up")
            wheel_axis_hold["down"] = poll_axbtn("wheel_down")

            # ---------- BUTTON-BASED MOVEMENT
            vx = (1 if (hold_inc_x_btn or hold_inc_x_axb) else 0) - (1 if (hold_dec_x_btn or hold_dec_x_axb) else 0)
            vy = (1 if (hold_inc_y_btn or hold_inc_y_axb) else 0) - (1 if (hold_dec_y_btn or hold_dec_y_axb) else 0)
            step_x_btn = int(round(vx * cfg["nudge_velocity"] * dt))
            step_y_btn = int(round(vy * cfg["nudge_velocity"] * dt))

            # ---------- AXIS-BASED MOVEMENT (analog)
            step_x_axis = 0
            step_y_axis = 0

            ax_x = cfg["bindings"].get("axis_x")
            if isinstance(ax_x, Binding) and ax_x.kind == "axis_analog":
                js = get_js_for(ax_x)
                if js is not None and (not ax_x.req_mod or modifier_is_down()):
                    try:
                        ax = float(js.get_axis(ax_x.axis))
                        if cfg["axis_invert_x"]: ax = -ax
                        if abs(ax) < cfg["axis_deadzone_x"]: ax = 0.0
                        step_x_axis = int(round(ax * cfg["axis_velocity"] * dt))
                        if cfg["debug_io"] and step_x_axis != 0:
                            print(f"[AXIS] X dev={ax_x.dev} axis={ax_x.axis} val={ax:+.3f} step={step_x_axis}")
                    except Exception:
                        pass

            ax_y = cfg["bindings"].get("axis_y")
            if isinstance(ax_y, Binding) and ax_y.kind == "axis_analog":
                js = get_js_for(ax_y)
                if js is not None and (not ax_y.req_mod or modifier_is_down()):
                    try:
                        ay = float(js.get_axis(ax_y.axis))
                        if cfg["axis_invert_y"]: ay = -ay
                        if abs(ay) < cfg["axis_deadzone_y"]: ay = 0.0
                        step_y_axis = int(round(ay * cfg["axis_velocity"] * dt))
                        if cfg["debug_io"] and step_y_axis != 0:
                            print(f"[AXIS] Y dev={ax_y.dev} axis={ax_y.axis} val={ay:+.3f} step={step_y_axis}")
                    except Exception:
                        pass

            # ---------- APPLY MOVEMENT
            step_x = step_x_btn + step_x_axis
            step_y = step_y_btn + step_y_axis
            if step_x != 0 or step_y != 0:
                target_x += step_x; target_y += step_y
                target_x, target_y = clamp_target(target_x, target_y, mon, cfg["clamp_virtual"])
                if cfg["debug_io"]:
                    print(f"[MOVE] dx={step_x:+d} dy={step_y:+d} → target=({target_x},{target_y})")
                if active:
                    apply_cursor(); last_apply = now; wiggle_flip = not wiggle_flip

            # ---------- WHEEL (continuous while held)
            net_rate = 0.0
            if wheel_btn_hold["up"]   or wheel_axis_hold["up"]:   net_rate += cfg["wheel_rate"]
            if wheel_btn_hold["down"] or wheel_axis_hold["down"]: net_rate -= cfg["wheel_rate"]
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
