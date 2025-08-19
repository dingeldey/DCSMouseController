# DCSMouseController — Joystick/Throttle → Mouse

A Windows‑friendly, single‑file Python tool (also available as a compiled `.exe`) that lets you control and **pin** the mouse cursor using one or more game controllers. It supports per‑binding device routing (mix sticks/throttles), a global modifier, analog & “axis‑as‑button” inputs, mouse clicks & wheel, and optional window focusing/centering for sims.

> Ideal for HOTAS/cockpit setups where you want a repeatable cursor position or analog/step nudging inside a specific game window.

---

## Highlights

- **Mix multiple controllers, per binding**
  - Reference a device by **index** (`devIdx:<n>`) or exact **GUID** (`dev:<GUID>`).
- **Flexible bindings**
  - Buttons are **1‑based**; axes are **0‑based** (as printed at startup).
  - Require a held **modifier** by appending `M` **or** `:M` to any binding.
  - Use **axis values as buttons** (`pos|neg|abs` + threshold + hysteresis).
  - Use **axes as analog mouse motion** with per‑axis deadzones & invert.
- **Mouse actions**
  - Left/right click (press & hold).
  - Mouse wheel (via buttons or axis thresholds; continuous scrolling while held).
- **Pin & repeat cursor**
  - Toggle ON recenters to a base position; while ACTIVE, cursor is periodically re‑applied to keep it “pinned”.
- **Clamp target area**
  - `monitor` (selected monitor), `virtual` (whole Windows virtual desktop), or `window` (target window **client** area).
- **Window targeting (Windows)**
  - Optionally **focus** a window on toggle‑ON and/or center within its **client** area.
  - Match by exact **class** (preferred) or by **title substring**.
  - **Enforced**: if `clamp_space = window`, you **must** set either `focus_window_class` or `focus_window_title`.
- **Robust on Windows**
  - Uses `SendInput` for precise, low‑latency moves & clicks.
  - DPI‑aware and multi‑monitor‑safe client→screen conversions.
- **Debugging helpers**
  - Startup prints device indices, GUIDs, and axis counts.
  - `debug_buttons`, `debug_io`, `debug_window` for live tracing.

---

## Download & Run

- **Compiled**: use the release `DCSMouseController.exe` (no Python needed).
- **From source**: install Python 3.9+ and:
  ```bash
  pip install pygame pyautogui
  python DCSMouseController.py
  ```

### Use a different INI
You can point to a custom configuration file:
```bash
# EXE
DCSMouseController.exe --config myprofile.ini
# or short
DCSMouseController.exe -c myprofile.ini

# Python
python DCSMouseController.py --config myprofile.ini
```

By default, the program loads `joystick_mouse.ini` from the same folder.

---

## Binding Syntax (quick reference)

You can mix devices **per binding**. Use either `devIdx:<index>` or an exact `dev:<GUID>` as printed at startup.

- **Button** (1‑based):  
  `devIdx:<dev>:button:<btn>[M|:M]` or `dev:<GUID>:button:<btn>[M|:M]`
- **Axis as button** (thresholded):  
  `devIdx:<dev>:axis:<axis>:<pos|neg|abs>:<thr>[M|:M]`  
  `dev:<GUID>:axis:<axis>:<pos|neg|abs>:<thr>[M|:M]`
- **Analog axis (for X/Y movement)**:  
  `devIdx:<dev>:axis:<axis>[M|:M]` or `dev:<GUID>:axis:<axis>[M|:M]`

Append `M` (or `:M`) if that binding should only work while the **global modifier** button is held.

**Note:** Buttons are **1‑based** (Windows style). Axes are **0‑based**.

---

## Example `joystick_mouse.ini`

```ini
[input]
; --- Global modifier (advanced) ---
; Choose device by index or GUID, and the 1-based button number:
;   modifier = devIdx:1:button:6
;   modifier = dev:03000000b50700001572000011010000:button:6
modifier = dev:0:button:1

; --- Toggle (OFF binding removed; toggle handles both states) ---
button_toggle = devIdx:1:button:5

; --- Movement nudges (buttons or axis-thresholds) ---
button_inc_x = devIdx:0:button:12:M
button_dec_x = devIdx:0:button:11:M
button_inc_y = devIdx:0:button:9:M
button_dec_y = devIdx:0:button:10:M

nudge_velocity_px_s = 4000
wiggle_one_pixel = true

; --- Analog cursor movement (axes) ---
axis_x = devIdx:1:axis:0
axis_y = devIdx:1:axis:1
axis_deadzone_x = 0.01
axis_deadzone_y = 0.01
axis_invert_x = false
axis_invert_y = false
axis_velocity_px_s = 800
axis_button_hysteresis = 0.10

; --- Mouse buttons & wheel ---
button_mouse_left  = devIdx:0:button:2
button_mouse_right = devIdx:0:button:4
button_wheel_up    = devIdx:0:button:8
button_wheel_down  = devIdx:0:button:7
wheel_ticks_per_second = 30

; --- Monitor & target (when not centering in a window) ---
monitor_index = 1
x_frac = 0.5
y_frac = 0.5

; Clamp target to: monitor | virtual | window
; If 'window', you MUST also set either 'focus_window_class' or 'focus_window_title' below.
clamp_space = monitor

; --- Optional window targeting (Windows only) ---
focus_on_toggle = true
focus_window_title = 132-388th-BVR Handbook WIP.docx  ; title substring (case-insensitive)
focus_window_class =                                  ; exact window class (preferred)
window_restore_if_minimized = true
window_force_foreground = true

center_in_window_on_toggle = false
window_x_frac = 0.5
window_y_frac = 0.5

; --- Loop/engine ---
repeat_ms = 3500
poll_hz = 250
startup_grace_ms = 200
use_sendinput = true

; --- Debug ---
toggle_feedback = false
log_apply = false
debug_buttons = false
debug_io = false
debug_window = true
```

---

## Window Targeting Notes (Windows)

- **Class vs Title**: prefer `focus_window_class` if you know it—it’s more stable than title text.
- **Finding class names**: use a small enumerator to print visible windows (or Spy++). The project can also log the chosen window when `debug_window = true`.
- **Enforcement**: if `clamp_space = window` and neither `focus_window_class` nor `focus_window_title` is set, the program will **abort** with an error to avoid wrong‑screen positioning.

---

## Troubleshooting

- **Cursor centers on wrong monitor/edge**  
  Use `clamp_space = window`, verify the chosen window (enable `debug_window = true`), and confirm the **client rect** looks correct in the logs.
- **Bindings don’t fire with `:M`**  
  Ensure `modifier = devIdx:…:button:<btn>` (or GUID form) is set and that you’re holding that modifier button.
- **Which axis/button is which?**  
  Watch the startup device print for axis counts and indices. Turn on `debug_buttons` / `debug_io` to see live edges/values.

---

## License

MIT (or your preferred license). Contributions welcome!
