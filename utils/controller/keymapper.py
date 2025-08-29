#!/usr/bin/env python3
"""
keymapper.py - Send keyboard events using Windows SendInput
Supports combos like: "A", "F1", "Ctrl+Shift+F5", "Alt+Tab"
"""

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

# --- constants ---
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# pick correct ULONG_PTR
if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]

class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wt.DWORD),
        ("u", _INPUTUNION),
    ]


# --- Helpers for mapping strings to VK codes ---
def _vk_from_str(key: str) -> int:
    """Map a string like 'A', 'F1', 'Ctrl' to a Windows virtual-key code."""
    k = key.upper()

    # single letters A–Z
    if len(k) == 1 and "A" <= k <= "Z":
        return ord(k)

    # digits 0–9
    if len(k) == 1 and "0" <= k <= "9":
        return ord(k)

    # function keys F1–F24
    if k.startswith("F") and k[1:].isdigit():
        n = int(k[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)

    mapping = {
        "CTRL": 0x11,
        "CONTROL": 0x11,
        "ALT": 0x12,
        "SHIFT": 0x10,
        "WIN": 0x5B,   # Left Windows key
        "LWIN": 0x5B,
        "RWIN": 0x5C,

        "ENTER": 0x0D,
        "RETURN": 0x0D,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "SPACE": 0x20,
        "TAB": 0x09,
        "BACKSPACE": 0x08,
        "BKSP": 0x08,
        "DEL": 0x2E,
        "DELETE": 0x2E,
        "INS": 0x2D,
        "INSERT": 0x2D,
        "HOME": 0x24,
        "END": 0x23,
        "PGUP": 0x21,
        "PAGEUP": 0x21,
        "PGDN": 0x22,
        "PAGEDOWN": 0x22,
        "LEFT": 0x25,
        "RIGHT": 0x27,
        "UP": 0x26,
        "DOWN": 0x28,
    }
    return mapping.get(k, 0)


# --- Main class ---
class KeyMapper:
    def __init__(self, log=None):
        self.log = log

    def tap(self, combo: str, hold_ms: int = 30):
        """Press + release a combo with optional hold time (default 30 ms)."""
        self.key_down(combo)
        time.sleep(hold_ms / 1000.0)
        self.key_up(combo)

    def key_down(self, combo: str):
        """Press a combo and keep it held (until key_up)."""
        parts = [p.strip() for p in combo.split("+") if p.strip()]
        vks = [_vk_from_str(p) for p in parts]
        if not vks or any(vk == 0 for vk in vks):
            if self.log:
                self.log.warning(f"[KEYMAPPER] Unknown key combo: {combo}")
            return

        # press all in order
        for vk in vks:
            self._send_vk(vk, down=True)

        if self.log:
            self.log.debug(f"[KEYMAPPER] DOWN combo: {combo}")

    def key_up(self, combo: str):
        """Release a combo that was held with key_down()."""
        parts = [p.strip() for p in combo.split("+") if p.strip()]
        vks = [_vk_from_str(p) for p in parts]
        if not vks or any(vk == 0 for vk in vks):
            if self.log:
                self.log.warning(f"[KEYMAPPER] Unknown key combo: {combo}")
            return

        # release all in reverse order
        for vk in reversed(vks):
            self._send_vk(vk, down=False)

        if self.log:
            self.log.debug(f"[KEYMAPPER] UP combo: {combo}")

    def send_key(self, combo: str):
        """Legacy: tap a key combo immediately (for compatibility)."""
        self.tap(combo, hold_ms=30)

    def _send_vk(self, vk: int, down=True):
        flags = 0 if down else KEYEVENTF_KEYUP
        ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
        inp = INPUT(type=INPUT_KEYBOARD, ki=ki)
        n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if n == 0:
            err = ctypes.get_last_error()
            if self.log:
                self.log.error(f"[KEYMAPPER] SendInput failed, err={err}")
        else:
            if self.log:
                self.log.debug(f"[KEYMAPPER] {'DOWN' if down else 'UP'} vk=0x{vk:02X}")
