# DCSMouseController

# Joystick/Throttle → Mouse Position Repeater

Pin your mouse cursor to a chosen position using a joystick/throttle button, with optional hold-to-nudge controls. Windows-friendly (SendInput), pygame-based, single-threaded.

> **1-based indices:** All button numbers in the INI are **1-based** (Windows-style). The program converts them internally to 0-based for pygame.

---

## Downloads

- **Portable EXE (Windows)**: grab the prebuilt binary from the **Releases** page.  
  Place `joystick_mouse.ini` next to the `.exe`.

- **Source (Python)**: clone/download this repo and run with Python 3.9+.

---

## Features

- Lists connected game controllers (index, GUID, button count)
- Device selection by **GUID** (preferred) or fallback **index**
- Optional **modifier** button (can be on a second device); require it per action using the `M` suffix (e.g., `28M`)
- Target positions by **fractions** of a monitor (0–1) or fixed **pixels** within that monitor
- **Toggle ON/OFF**; ON recenters to INI base each time; OFF does **not** restore cursor by default (configurable)
- **Hold-based** continuous X/Y adjust at pixels/second velocity
- Reapply cursor every `repeat_ms` while active; optional **1px wiggle**
- Clamp target to **selected monitor** or **entire virtual desktop**
- Windows: absolute cursor moves via **SendInput** across the virtual desktop

---

## Quick Start (EXE)

1. Download the `.exe` from **Releases** and place it together with `joystick_mouse.ini` in the same folder.
2. Edit the INI to match your setup (see template below).
3. Double-click the `.exe`. A console window will print:
    - Controller list (index, GUID, buttons)
    - Monitor list (index, geometry)
    - Base target position and repeat interval

**Tips**
- Prefer selecting your device by **GUID** so the correct controller is picked even if OS indices shift.
- If your AV flags the unsigned EXE, allow/whitelist it or build locally from source.

---

## Quick Start (Python)

```bash
pip install pygame pyautogui
python joystick_mouse.py
