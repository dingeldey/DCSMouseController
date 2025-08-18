# DCS Mouse Controller

Turn any joystick/throttle into a precise mouse-position controller for sims (e.g., DCS).  
Windows is fully supported via low-latency **SendInput**; other platforms use `pyautogui`.

**Highlights**
- Toggle ON/OFF with a joystick button (1-based indices, Windows-style)
- Optional **modifier** button to gate actions (append `M` in INI)
- Position the cursor at a monitor-relative target (fractions or pixels)
- Move the target with **buttons** (nudges) and/or **axes** (analog)
- **Per-axis deadzone & invert** for analog movement
- Map joystick **buttons** or **axis-thresholds** to **left/right click** and **mouse wheel**
- Clamp movement to the selected monitor or the entire virtual desktop
- Verbose **debug I/O** logging

---

## Table of Contents
- [Download (prebuilt EXE)](#download-prebuilt-exe)
- [Install (from source)](#install-from-source)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Configuration (INI Reference)](#configuration-ini-reference)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [License](#license)

---

## Download (prebuilt EXE)
Releases include:
- `DCSMouseController.exe`
- `joystick_mouse.ini` (template)
- `README.md` (this file)

Just edit the INI and run the EXE.

---

## Install (from source)

**Requirements**
- Python 3.9+
- `pygame`, `pyautogui`

```bash
pip install pygame pyautogui
python DCSMouseController.py
```

> Windows users: keep `use_sendinput = true` for the most robust behavior in fullscreen sims.

---

## Quick Start

1. **Run the program** (EXE or `python DCSMouseController.py`).
2. Watch the startup log:
   - Connected controllers (index, GUID, name)
   - Button count, **axis count**, hats
   - **Axis indices (`0..N-1`)** you’ll use in the INI
   - Available **monitors** and their indices
3. Edit `joystick_mouse.ini` to match your device and mappings.
4. Use your `button_toggle` to turn the controller **ACTIVE**. It will **recenter** to your configured target each time.

---

## How It Works

The program maintains a **target mouse position**. While **ACTIVE**, it repeatedly pins the system cursor to that target every `repeat_ms`. You control the target by:

- **Buttons**: continuous **nudges** while held (velocity in `px/s`)
- **Axes**: **analog movement** (velocity scales with axis deflection)
- **Clicks & Wheel**: map to joystick **buttons** or **axis-thresholds** (“axis-as-button”)

> **Conventions**  
> - **Buttons** in the INI are **1-based** (Windows-style).  
> - **Axes** in the INI are **0-based** (as printed by the program).

---

## Configuration (INI Reference)

All settings live in `joystick_mouse.ini` under the `[input]` section.

```ini
[input]
; --- Device selection ---
device_guid =
device_index = 0

; Optional separate modifier device (else primary is used)
modifier_device_guid =
modifier_device_index =
modifier_button = 6        ; 1-based! held as a gate for entries marked with 'M'

; --- Toggle & button nudges (1-based; append 'M' to require modifier) ---
button_toggle = 5
button_off    =            ; optional dedicated OFF

button_inc_x = 12M         ; hold to nudge right
button_dec_x = 11M         ; hold to nudge left
button_inc_y = 9M          ; hold to nudge down
button_dec_y = 10M         ; hold to nudge up

nudge_velocity_px_s = 400
wiggle_one_pixel = true     ; optional 1px wiggle to keep OS from idling the cursor

; --- Axis-based analog movement (0-based; append 'M' to require modifier) ---
axis_x = 0M
axis_y = 1M
axis_deadzone_x = 0.01      ; per-axis deadzone (0..1)
axis_deadzone_y = 0.01
axis_invert_x = false
axis_invert_y = false
axis_velocity_px_s = 800    ; px/s at |axis| = 1.0

; --- Mouse buttons via joystick buttons (1-based; optional 'M') ---
button_mouse_left  = 2
button_mouse_right = 4

; --- Mouse wheel via buttons (hold to scroll) ---
button_wheel_up   = 8
button_wheel_down = 7
wheel_ticks_per_second = 30

; --- Axis-as-button (thresholded) for clicks / wheel (0-based axes) ---
; Format:  axis:<index>:<pos|neg|abs>:<threshold>[M]
; Example: axisbtn_mouse_left = axis:2:pos:0.65M   ; press LMB when axis 2 >= +0.65 with modifier
;          axisbtn_wheel_down = axis:3:neg:0.50    ; hold wheel down when axis 3 <= -0.50
axisbtn_mouse_left  =
axisbtn_mouse_right =
axisbtn_wheel_up    =
axisbtn_wheel_down  =
axis_button_hysteresis = 0.10  ; press at thr, release at (thr - hyst) to avoid flicker

; --- Monitor selection & target position ---
monitor_index = 1            ; printed on startup
x_frac = 0.5                 ; preferred: fractions within the monitor (0..1)
y_frac = 0.5
; x,y are used only if x_frac/y_frac are omitted
x = 1280
y = 720

; --- Timing ---
repeat_ms = 1000             ; re-apply cursor while ACTIVE
poll_hz = 250
startup_grace_ms = 200

; --- Windows input path (recommended for sims) ---
use_sendinput = true

; Clamp space: 'monitor' (selected monitor only) or 'virtual' (all monitors)
clamp_space = virtual

; --- Logging / behavior ---
toggle_feedback = false
log_apply = false
debug_buttons = false
debug_io = false             ; print monitored inputs and generated outputs

; Optional:
; restore_on_off = false     ; if true, restore the pre-toggle cursor when turning OFF
```

### Axis-as-Button Hysteresis (What `axis_button_hysteresis` Does)
Adds a buffer so axis-threshold “buttons” don’t chatter near the threshold:
- **Press (edge-down)** at `thr`
- **Release (edge-up)** at `thr - hysteresis`  
Example: `thr=0.60`, `hys=0.10` → press at 0.60, release at 0.50.

---

## Examples

### Ministick for analog movement + LB/RB for clicks
```ini
axis_x = 0M
axis_y = 1M
axis_deadzone_x = 0.12
axis_deadzone_y = 0.20
axis_invert_y = true
button_mouse_left  = 2
button_mouse_right = 4
```

### Axis to mouse wheel (snap steps)
```ini
axisbtn_wheel_up   = axis:2:pos:0.60
axisbtn_wheel_down = axis:2:neg:0.60
wheel_ticks_per_second = 45
axis_button_hysteresis = 0.10
```

### Digital nudges only with modifier
```ini
button_inc_x = 20M
button_dec_x = 22M
button_inc_y = 21M
button_dec_y = 19M
nudge_velocity_px_s = 600
```

---

## Troubleshooting

- **Nothing moves / no input**  
  - Run the app and check the startup list: are your devices detected?  
  - Ensure the **right device** is selected (`device_guid` or `device_index`).  
  - Use `debug_io = true` to see axis values, steps, and outputs.

- **Buttons don’t match numbers**  
  - INI **buttons are 1-based**. Pygame uses 0-based internally; the app converts for you.

- **Axis moving in the wrong direction**  
  - Set `axis_invert_x` / `axis_invert_y = true`.

- **Cursor not changing in fullscreen**  
  - Keep `use_sendinput = true` on Windows.  
  - Some sims may need you to run the tool **before** launching the sim.

- **Chatter around threshold for axis-as-button**  
  - Increase `axis_button_hysteresis` or raise the threshold.

---

## FAQ

**Q: Do I need admin rights?**  
A: Typically no. `SendInput` works fine without elevation in most sims.

**Q: Can I combine button nudges and axes?**  
A: Yes—per frame, the button velocity and axis velocity are **summed**.

**Q: Why does it “recentre” on toggle ON?**  
A: By design: every ON begins from your INI target anchor (fractions or pixels).

**Q: What is `wiggle_one_pixel` for?**  
A: Some environments stop updating the cursor if it never changes; a tiny 1px wiggle keeps it “alive”.

---

## License


