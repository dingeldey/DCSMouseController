import ctypes, ctypes.wintypes as wt

u = ctypes.windll.user32
GetWindowTextW = u.GetWindowTextW
GetWindowTextLengthW = u.GetWindowTextLengthW
GetClassNameW = u.GetClassNameW
IsWindowVisible = u.IsWindowVisible
GetWindow = u.GetWindow
GetWindowLongW = u.GetWindowLongW

GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080

EnumWindows = u.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

def is_top_level_app(hwnd):
    if not IsWindowVisible(hwnd): return False
    if GetWindow(hwnd, GW_OWNER): return False          # has owner → skip
    ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW: return False              # tool window → skip
    return True

def enum_cb(hwnd, lParam):
    if not is_top_level_app(hwnd):
        return True
    length = GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(max(1, length + 1))
    GetWindowTextW(hwnd, title_buf, len(title_buf))
    class_buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, class_buf, 256)
    print(f"HWND=0x{hwnd:08X}  CLASS='{class_buf.value}'  TITLE='{title_buf.value}'")
    return True

EnumWindows(EnumWindowsProc(enum_cb), 0)
