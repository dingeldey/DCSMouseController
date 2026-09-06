#!/usr/bin/env python3
"""
keynames.py - Pure key-name -> Windows virtual-key lookup, with no ctypes
dependency, so it can be imported from platform-independent code (like
bindings.py's config parsing) without dragging in keymapper.py's
Windows-only ctypes.WinDLL("user32") module-level call.
"""

_NAMED_KEYS = {
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "LCTRL": 0xA2,
    # RCTRL deliberately omitted: keymapper._send_vk sends wVk with no
    # KEYEVENTF_EXTENDEDKEY/scancode, and Windows needs that flag to tell
    # VK_RCONTROL apart from VK_LCONTROL (they share a scancode) - without
    # it this would silently deliver as LCtrl instead of rejecting cleanly.
    "ALT": 0x12,
    "LALT": 0xA4,
    # RALT omitted for the same reason (shares a scancode with LAlt).
    "SHIFT": 0x10,
    "LSHIFT": 0xA0,
    "RSHIFT": 0xA1,
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

    "CAPSLOCK": 0x14,
    "SCROLLLOCK": 0x91,
    # NUMLOCK omitted: also an extended key (see RCTRL note above).

    # Numpad operator keys (NUMPAD0-9 handled in vk_from_str)
    "MULTIPLY": 0x6A,
    "ADD": 0x6B,
    "SEPARATOR": 0x6C,
    "SUBTRACT": 0x6D,
    "DECIMAL": 0x6E,
    # DIVIDE omitted: also an extended key (see RCTRL note above).

    # Common US-layout punctuation (VK_OEM_*). Note ',' and '\\' can't
    # actually appear in an INI binding string - IniReader.get_list() uses
    # them as its list separator / line-continuation marker respectively -
    # so they're left out here rather than advertising a dead option.
    ";": 0xBA,
    "=": 0xBB,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "]": 0xDD,
    "'": 0xDE,
}


def vk_from_str(key: str) -> int:
    """Map a string like 'A', 'F1', 'Ctrl' to a Windows virtual-key code, or 0 if unknown."""
    k = key.upper()

    # single letters A-Z
    if len(k) == 1 and "A" <= k <= "Z":
        return ord(k)

    # digits 0-9
    if len(k) == 1 and "0" <= k <= "9":
        return ord(k)

    # function keys F1-F24
    if k.startswith("F") and k[1:].isdigit():
        n = int(k[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)

    # numpad digits NUMPAD0-NUMPAD9
    if k.startswith("NUMPAD") and k[6:].isdigit():
        n = int(k[6:])
        if 0 <= n <= 9:
            return 0x60 + n

    return _NAMED_KEYS.get(k, 0)


def is_valid_combo(combo: str) -> bool:
    """True if every '+'-separated part of combo resolves to a known key.

    Used at config-load time to catch a typo'd action verb (e.g.
    'FocusWndow') before it silently falls through to being sent as a
    keyboard shortcut - see _parse_mapping_entries in bindings.py.
    """
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    return bool(parts) and all(vk_from_str(p) != 0 for p in parts)
