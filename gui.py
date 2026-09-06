#!/usr/bin/env python3
"""Desktop profile editor and launcher for DCS Mouse Controller."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from utils.app_paths import app_dir, is_frozen
from utils.config_editor import ConfigDocument, MappingRow
from utils.controller.devices import ControllerDevice, ControllerService
from utils.output_actions import ACTION_TYPES, ActionSpec, describe_action, parse_action, render_action


APP_DIR = app_dir()


class Palette:
    BG = "#0b1220"
    SURFACE = "#111b2e"
    SURFACE_2 = "#17243b"
    BORDER = "#263754"
    TEXT = "#e9eff9"
    MUTED = "#91a2bb"
    ACCENT = "#4f8cff"
    ACCENT_HOVER = "#6ba0ff"
    SUCCESS = "#35c78a"
    WARNING = "#f4b75e"
    DANGER = "#ef6a78"


def compact_device(token: str) -> str:
    if len(token) <= 34:
        return token
    if re.fullmatch(r"[0-9a-fA-F-]{20,}", token):
        return f"{token[:10]}…{token[-8:]}"
    return token[:31] + "…"


def controller_matches(token: str, devices: list[ControllerDevice]) -> bool:
    folded = token.strip().casefold()
    for device in devices:
        if folded in {str(device.index).casefold(), device.guid.casefold(), device.name.casefold()}:
            return True
    return False


def list_open_windows() -> list[tuple[int, str, str]]:
    """Return (hwnd, class_name, title) for real top-level app windows.

    Excludes owned windows and WS_EX_TOOLWINDOW ones (tooltips, tray icons,
    etc.) so the picker isn't dominated by blank-title system noise.
    Window enumeration is a Windows-only ctypes API, so the import is kept
    lazy here rather than at module load - this keeps the GUI importable
    (e.g. for tests) on platforms that don't have it.
    """
    try:
        import ctypes
        from utils.controller.mousecontroller import MouseController
    except Exception as exc:
        raise RuntimeError(f"Window listing is only available on Windows ({exc}).") from exc

    user32 = ctypes.windll.user32
    GW_OWNER = 4
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080

    def is_real_app_window(hwnd) -> bool:
        if user32.GetWindow(hwnd, GW_OWNER):
            return False
        return not (user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)

    return [w for w in MouseController.list_windows() if is_real_app_window(w[0])]


class KeyCaptureDialog(tk.Toplevel):
    KEY_NAMES = {
        "Return": "Enter", "Escape": "Esc", "Prior": "PgUp", "Next": "PgDn",
        "BackSpace": "Backspace", "Delete": "Del", "Insert": "Ins", "space": "Space",
        "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down",
        "Home": "Home", "End": "End", "Tab": "Tab",
    }
    MODIFIERS = {"Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Super_L", "Super_R"}

    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.title("Capture keyboard shortcut")
        self.geometry("430x200")
        self.resizable(False, False)
        self.configure(bg=Palette.SURFACE)
        self.transient(parent)
        self.grab_set()
        tk.Label(self, text="Press a shortcut", bg=Palette.SURFACE, fg=Palette.TEXT,
                 font=("Segoe UI Semibold", 18)).pack(pady=(34, 8))
        self.hint = tk.Label(self, text="Modifiers + one key · Esc cancels", bg=Palette.SURFACE,
                             fg=Palette.MUTED, font=("Segoe UI", 10))
        self.hint.pack()
        self.bind("<KeyPress>", self._capture)
        self.after(80, self.focus_force)

    def _capture(self, event):
        if event.keysym in self.MODIFIERS:
            return "break"
        if event.keysym == "Escape":
            self.destroy()
            return "break"
        parts = []
        if event.state & 0x4:
            parts.append("Ctrl")
        if event.state & (0x8 | 0x20000):
            parts.append("Alt")
        if event.state & 0x1:
            parts.append("Shift")
        key = self.KEY_NAMES.get(event.keysym, event.keysym)
        if len(key) == 1:
            key = key.upper()
        parts.append(key)
        self.callback("+".join(parts))
        self.destroy()
        return "break"


class WindowPickerDialog(tk.Toplevel):
    """Lets a binding target a live window instead of guessing its class/title.

    Matching (CenterMouse/FocusWindow) is case-insensitive and accepts a
    partial match, so whichever string is picked here doesn't need to be
    the whole class/title - but a window's title can change at runtime
    (e.g. a sim showing FPS or the current mission), while its class
    almost never does, so class is the safer default.
    """

    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        self.title("Pick a window")
        self.geometry("640x420")
        self.configure(bg=Palette.BG)
        self.transient(parent)
        self.grab_set()

        tk.Label(self, text="Select an open window, then choose whether to match it by class or by title.\n"
                             "Tip: class is usually more stable than title for game windows.",
                 bg=Palette.BG, fg=Palette.MUTED, justify="left", wraplength=600).pack(fill="x", padx=16, pady=(16, 8))

        table = tk.Frame(self, bg=Palette.BG)
        table.pack(fill="both", expand=True, padx=16)
        self.tree = ttk.Treeview(table, columns=("class", "title"), show="headings", selectmode="browse")
        self.tree.heading("class", text="Class")
        self.tree.heading("title", text="Title")
        self.tree.column("class", width=220, anchor="w")
        self.tree.column("title", width=360, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self._use(prefer_title=False))

        footer = tk.Frame(self, bg=Palette.BG)
        footer.pack(fill="x", padx=16, pady=16)
        ttk.Button(footer, text="Refresh", command=self._refresh).pack(side="left")
        ttk.Button(footer, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Use class", command=lambda: self._use(prefer_title=False)).pack(side="right", padx=(0, 10))
        ttk.Button(footer, text="Use title", command=lambda: self._use(prefer_title=True)).pack(side="right", padx=(0, 10))

        self._refresh()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        try:
            windows = list_open_windows()
        except Exception as exc:
            messagebox.showerror("Can't list windows", str(exc), parent=self)
            return
        for hwnd, class_name, title in sorted(windows, key=lambda w: (w[2] or "").lower()):
            self.tree.insert("", "end", iid=str(hwnd), values=(class_name, title))

    def _use(self, prefer_title: bool):
        selection = self.tree.selection()
        if not selection:
            return
        class_name, title = self.tree.item(selection[0], "values")
        if prefer_title and not title:
            messagebox.showinfo("No title", "This window has no title - use its class instead.", parent=self)
            return
        if prefer_title:
            self.callback("WindowName", title)
        else:
            self.callback("WindowClass", class_name)
        self.destroy()


class BindingDialog(tk.Toplevel):
    def __init__(self, parent, devices, row: MappingRow | None, on_save, controller_service):
        super().__init__(parent)
        self.devices = devices
        self.row = row
        self.on_save = on_save
        self.controller_service = controller_service
        self.listen_baseline = None
        self.listen_after = None
        self.title("Edit binding" if row else "Add binding")
        self.geometry("700x760")
        self.minsize(660, 700)
        self.configure(bg=Palette.BG)
        self.transient(parent)
        self.grab_set()

        self.device_var = tk.StringVar()
        self.input_type_var = tk.StringVar(value="Button")
        self.input_id_var = tk.StringVar(value="1")
        self.axis_mode_var = tk.StringVar(value="pos")
        self.threshold_var = tk.StringVar(value="0.60")
        self.modified_var = tk.BooleanVar(value=False)
        self.output_type_var = tk.StringVar(value="Keyboard key")
        defaults = {
            "shortcut": "", "key_mode": "single", "duration": "30", "button": "MB1 · Left",
            "button_mode": "single", "wheel_direction": "WheelUp", "wheel_mode": "single",
            "initial": "5", "maximum": "30", "ramp": "1000", "mouse_axis": "x",
            "target_type": "Virtual", "target": "", "coordinate_mode": "frac", "x": "0.5", "y": "0.5",
            "wiggle_mode": "relative", "pixels": "5", "period": "1000",
            "increment_direction": "Increase", "increment_axis": "x", "increment_mode": "relative", "raw": "",
        }
        self.output_vars = {name: tk.StringVar(value=value) for name, value in defaults.items()}

        self._build()
        self._load_row()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _section(self, parent, title, subtitle):
        frame = tk.Frame(parent, bg=Palette.SURFACE, highlightbackground=Palette.BORDER, highlightthickness=1)
        frame.pack(fill="x", pady=(0, 14))
        tk.Label(frame, text=title, bg=Palette.SURFACE, fg=Palette.TEXT,
                 font=("Segoe UI Semibold", 12)).grid(row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 1))
        tk.Label(frame, text=subtitle, bg=Palette.SURFACE, fg=Palette.MUTED,
                 font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=4, sticky="w", padx=18, pady=(0, 12))
        return frame

    def _build(self):
        body = tk.Frame(self, bg=Palette.BG)
        body.pack(fill="both", expand=True, padx=20, pady=20)
        source = self._section(body, "Controller input", "Choose a device manually or press Listen and move a control.")
        source.columnconfigure(1, weight=1)
        tk.Label(source, text="Device", bg=Palette.SURFACE, fg=Palette.MUTED).grid(row=2, column=0, sticky="w", padx=(18, 8), pady=7)
        values = [device.label for device in self.devices]
        self.device_box = ttk.Combobox(source, textvariable=self.device_var, values=values, state="readonly")
        self.device_box.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(0, 18), pady=7)

        tk.Label(source, text="Input", bg=Palette.SURFACE, fg=Palette.MUTED).grid(row=3, column=0, sticky="w", padx=(18, 8), pady=7)
        self.input_box = ttk.Combobox(source, textvariable=self.input_type_var,
                                      values=("Button", "Axis (analog)", "Axis as button"), state="readonly", width=18)
        self.input_box.grid(row=3, column=1, sticky="ew", pady=7)
        self.input_box.bind("<<ComboboxSelected>>", lambda _event: self._input_changed())
        tk.Label(source, text="Number", bg=Palette.SURFACE, fg=Palette.MUTED).grid(row=3, column=2, padx=(16, 6), pady=7)
        ttk.Spinbox(source, from_=0, to=255, textvariable=self.input_id_var, width=8).grid(row=3, column=3, sticky="ew", padx=(0, 18), pady=7)

        self.axis_frame = tk.Frame(source, bg=Palette.SURFACE)
        self.axis_frame.grid(row=4, column=0, columnspan=4, sticky="ew", padx=18, pady=4)
        tk.Label(self.axis_frame, text="Direction", bg=Palette.SURFACE, fg=Palette.MUTED).pack(side="left")
        ttk.Combobox(self.axis_frame, textvariable=self.axis_mode_var, values=("pos", "neg", "abs"),
                     state="readonly", width=8).pack(side="left", padx=(8, 18))
        tk.Label(self.axis_frame, text="Threshold", bg=Palette.SURFACE, fg=Palette.MUTED).pack(side="left")
        ttk.Entry(self.axis_frame, textvariable=self.threshold_var, width=10).pack(side="left", padx=8)

        controls = tk.Frame(source, bg=Palette.SURFACE)
        controls.grid(row=5, column=0, columnspan=4, sticky="ew", padx=18, pady=(7, 16))
        ttk.Checkbutton(controls, text="Modifier layer (M)", variable=self.modified_var).pack(side="left")
        self.listen_button = ttk.Button(controls, text="●  Listen for input", style="Accent.TButton", command=self._listen)
        self.listen_button.pack(side="right")

        output = self._section(body, "Output action", "Choose what should happen. The INI ':' syntax is generated for you.")
        output.columnconfigure(1, weight=1)
        tk.Label(output, text="Action type", bg=Palette.SURFACE, fg=Palette.MUTED).grid(row=2, column=0, sticky="w", padx=(18, 8), pady=7)
        self.output_type_box = ttk.Combobox(output, textvariable=self.output_type_var, values=ACTION_TYPES, state="readonly")
        self.output_type_box.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=7)
        self.output_type_box.bind("<<ComboboxSelected>>", lambda _event: self._output_type_changed())
        self.output_options = tk.Frame(output, bg=Palette.SURFACE)
        self.output_options.grid(row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(2, 7))
        self.output_options.columnconfigure(1, weight=1)
        self.output_help = tk.Label(output, text="", justify="left", wraplength=610, bg=Palette.SURFACE_2,
                                    fg=Palette.MUTED, font=("Segoe UI", 9), padx=10, pady=8)
        self.output_help.grid(row=4, column=0, columnspan=3, sticky="ew", padx=18, pady=(2, 16))

        footer = tk.Frame(body, bg=Palette.BG)
        footer.pack(fill="x")
        ttk.Button(footer, text="Cancel", command=self._close).pack(side="right")
        ttk.Button(footer, text="Save binding", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 10))

    def _output_field(self, row, label, variable, values=None, width=None):
        tk.Label(self.output_options, text=label, bg=Palette.SURFACE, fg=Palette.MUTED).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        if values:
            widget = ttk.Combobox(self.output_options, textvariable=variable, values=values, state="readonly", width=width)
        else:
            widget = ttk.Entry(self.output_options, textvariable=variable, width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        return widget

    def _output_type_changed(self):
        for child in self.output_options.winfo_children():
            child.destroy()
        kind, v = self.output_type_var.get(), self.output_vars
        help_text = ""
        if kind == "Keyboard key":
            self._output_field(0, "Shortcut", v["shortcut"])
            ttk.Button(self.output_options, text="⌨  Capture", command=self._capture_key).grid(row=0, column=2, padx=(8, 0))
            mode_widget = self._output_field(1, "Behavior", v["key_mode"], ("single", "hold", "toggle"))
            mode_widget.bind("<<ComboboxSelected>>", lambda _event: self._output_type_changed())
            if v["key_mode"].get() == "single":
                self._output_field(2, "Press duration (ms)", v["duration"])
            help_text = "Single presses once. Hold keeps the key down while the controller input is held. Toggle switches it on/off. Duration applies to Single."
        elif kind == "Mouse button":
            self._output_field(0, "Button", v["button"], ("MB1 · Left", "MB2 · Right", "MB3 · Middle", "MB4 · Back", "MB5 · Forward"))
            mode_widget = self._output_field(1, "Behavior", v["button_mode"], ("single", "hold", "toggle"))
            mode_widget.bind("<<ComboboxSelected>>", lambda _event: self._output_type_changed())
            if v["button_mode"].get() == "single":
                self._output_field(2, "Click duration (ms)", v["duration"])
            help_text = "Single clicks once. Hold keeps the mouse button down. Toggle alternates between down and up."
        elif kind == "Mouse wheel":
            self._output_field(0, "Direction", v["wheel_direction"], ("WheelUp", "WheelDown"))
            mode_widget = self._output_field(1, "Behavior", v["wheel_mode"], ("single", "hold"))
            mode_widget.bind("<<ComboboxSelected>>", lambda _event: self._output_type_changed())
            if v["wheel_mode"].get() == "hold":
                self._output_field(2, "Starting ticks / second", v["initial"])
                self._output_field(3, "Maximum ticks / second", v["maximum"])
                self._output_field(4, "Acceleration time (ms)", v["ramp"])
            help_text = "Single sends one wheel tick. Hold repeats and accelerates from the starting rate to the maximum over the selected time."
        elif kind == "Mouse movement axis":
            self._output_field(0, "Cursor axis", v["mouse_axis"], ("x", "y"))
            help_text = "Maps a continuous controller axis directly to horizontal or vertical cursor movement. Use with an analog axis input."
        elif kind == "Center mouse":
            self._output_field(0, "Target type", v["target_type"], ("Virtual", "Monitor", "WindowClass", "WindowName"))
            self._output_field(1, "Target name / monitor", v["target"])
            ttk.Button(self.output_options, text="🪟  Pick window…", command=self._pick_window).grid(row=1, column=2, padx=(8, 0))
            self._output_field(2, "Coordinate units", v["coordinate_mode"], ("frac", "px"))
            self._output_field(3, "X coordinate", v["x"])
            self._output_field(4, "Y coordinate", v["y"])
            help_text = "Fraction coordinates run from 0.0 to 1.0; [0.5, 0.5] is the center. Pixel coordinates are absolute within the target."
        elif kind == "Focus window":
            self._output_field(0, "Match window by", v["target_type"], ("WindowClass", "WindowName"))
            self._output_field(1, "Class or title", v["target"])
            ttk.Button(self.output_options, text="🪟  Pick window…", command=self._pick_window).grid(row=1, column=2, padx=(8, 0))
            help_text = "Brings the first matching window to the foreground. Matching is case-insensitive and accepts part of the class or title."
        elif kind == "Wiggle mouse":
            self._output_field(0, "Movement mode", v["wiggle_mode"], ("relative", "absolute"))
            self._output_field(1, "Distance (pixels)", v["pixels"])
            self._output_field(2, "Period (ms)", v["period"])
            help_text = "Toggles a small periodic cursor movement. Press the controller input once to start it and again to stop it."
        elif kind == "Mouse increment":
            self._output_field(0, "Direction", v["increment_direction"], ("Increase", "Decrease"))
            self._output_field(1, "Cursor axis", v["increment_axis"], ("x", "y"))
            self._output_field(2, "Movement mode", v["increment_mode"], ("relative", "absolute"))
            self._output_field(3, "Starting steps / second", v["initial"])
            self._output_field(4, "Maximum steps / second", v["maximum"])
            self._output_field(5, "Acceleration time (ms)", v["ramp"])
            help_text = "Moves the cursor continuously while held and accelerates from the starting rate to the maximum."
        else:
            self._output_field(0, "Raw action", v["raw"])
            help_text = "Advanced mode preserves an action exactly as entered. Colons separate the action's parameters."
        self.output_help.configure(text=help_text)

    def _load_row(self):
        if self.devices:
            self.device_var.set(self.devices[0].label)
        if not self.row:
            self._input_changed()
            self._output_type_changed()
            return
        match = re.match(r"^dev:([^:]+):(button|axis):(.+?)(:M)?$", self.row.input, re.I)
        if match:
            token, kind, detail, modified = match.groups()
            matching = next((d for d in self.devices if token.casefold() in {d.guid.casefold(), d.name.casefold(), str(d.index)}), None)
            self.device_var.set(matching.label if matching else f"Missing device  ·  {token}")
            self.modified_var.set(bool(modified))
            if kind.lower() == "button":
                self.input_type_var.set("Button")
                self.input_id_var.set(detail)
            else:
                axis_match = re.match(r"(\d+)(?::(pos|neg|abs):([0-9.]+))?$", detail)
                if axis_match:
                    axis_id, mode, threshold = axis_match.groups()
                    self.input_id_var.set(axis_id)
                    self.input_type_var.set("Axis as button" if mode else "Axis (analog)")
                    if mode:
                        self.axis_mode_var.set(mode)
                        self.threshold_var.set(threshold)
        self._load_output(self.row.output)
        self._input_changed()

    def _load_output(self, raw):
        spec = parse_action(raw)
        self.output_type_var.set(spec.kind)
        v, values = self.output_vars, spec.values
        mappings = {
            "Keyboard key": {"shortcut": "shortcut", "key_mode": "mode", "duration": "duration"},
            "Mouse button": {"button": "button", "button_mode": "mode", "duration": "duration"},
            "Mouse wheel": {"wheel_direction": "direction", "wheel_mode": "mode", "initial": "initial", "maximum": "maximum", "ramp": "ramp"},
            "Mouse movement axis": {"mouse_axis": "axis"},
            "Center mouse": {"target_type": "target_type", "target": "target", "coordinate_mode": "coordinate_mode", "x": "x", "y": "y"},
            "Focus window": {"target_type": "target_type", "target": "target"},
            "Wiggle mouse": {"wiggle_mode": "mode", "pixels": "pixels", "period": "period"},
            "Mouse increment": {"increment_direction": "direction", "increment_axis": "axis", "increment_mode": "mode", "initial": "initial", "maximum": "maximum", "ramp": "ramp"},
            "Advanced / raw": {"raw": "raw"},
        }
        for variable_name, value_name in mappings[spec.kind].items():
            if value_name in values:
                v[variable_name].set(values[value_name])
        if spec.kind == "Mouse button":
            labels = {"MB1": "MB1 · Left", "MB2": "MB2 · Right", "MB3": "MB3 · Middle", "MB4": "MB4 · Back", "MB5": "MB5 · Forward"}
            v["button"].set(labels.get(values.get("button"), values.get("button", "MB1")))
        self._output_type_changed()

    def _output_spec(self):
        kind, v = self.output_type_var.get(), self.output_vars
        if kind == "Keyboard key":
            values = {"shortcut": v["shortcut"].get(), "mode": v["key_mode"].get(), "duration": v["duration"].get()}
        elif kind == "Mouse button":
            values = {"button": v["button"].get().split()[0], "mode": v["button_mode"].get(), "duration": v["duration"].get()}
        elif kind == "Mouse wheel":
            values = {"direction": v["wheel_direction"].get(), "mode": v["wheel_mode"].get(), "initial": v["initial"].get(), "maximum": v["maximum"].get(), "ramp": v["ramp"].get()}
        elif kind == "Mouse movement axis":
            values = {"axis": v["mouse_axis"].get()}
        elif kind == "Center mouse":
            values = {name: v[name].get() for name in ("target_type", "target", "coordinate_mode", "x", "y")}
        elif kind == "Focus window":
            values = {"target_type": v["target_type"].get(), "target": v["target"].get()}
        elif kind == "Wiggle mouse":
            values = {"mode": v["wiggle_mode"].get(), "pixels": v["pixels"].get(), "period": v["period"].get()}
        elif kind == "Mouse increment":
            values = {"direction": v["increment_direction"].get(), "axis": v["increment_axis"].get(), "mode": v["increment_mode"].get(), "initial": v["initial"].get(), "maximum": v["maximum"].get(), "ramp": v["ramp"].get()}
        else:
            values = {"raw": v["raw"].get()}
        return ActionSpec(kind, values)

    def _selected_device(self):
        label = self.device_var.get()
        return next((device for device in self.devices if device.label == label), None)

    def _input_changed(self):
        input_type = self.input_type_var.get()
        if input_type == "Axis as button":
            self.axis_frame.grid()
        else:
            self.axis_frame.grid_remove()
        if input_type == "Axis (analog)":
            self.output_type_box.configure(values=("Mouse movement axis",))
            if self.output_type_var.get() != "Mouse movement axis":
                self.output_type_var.set("Mouse movement axis")
                self._output_type_changed()
        else:
            allowed = tuple(kind for kind in ACTION_TYPES if kind != "Mouse movement axis")
            self.output_type_box.configure(values=allowed)
            if self.output_type_var.get() == "Mouse movement axis":
                self.output_type_var.set("Keyboard key")
                self._output_type_changed()

    def _capture_key(self):
        self.output_type_var.set("Keyboard key")
        KeyCaptureDialog(self, lambda key: self.output_vars["shortcut"].set(key))

    def _pick_window(self):
        def apply(target_type, target):
            self.output_vars["target_type"].set(target_type)
            self.output_vars["target"].set(target)
            self._output_type_changed()

        WindowPickerDialog(self, apply)

    def _listen(self):
        device = self._selected_device()
        if not device:
            messagebox.showinfo("Choose a controller", "Select a connected controller before listening.", parent=self)
            return
        try:
            self.listen_baseline = self.controller_service.snapshot(device.index)
        except Exception as exc:
            messagebox.showerror("Cannot listen", str(exc), parent=self)
            return
        self.listen_button.configure(text="Listening… move a control", state="disabled")
        self._poll_listen(device)

    def _poll_listen(self, device):
        try:
            result = self.controller_service.detect_change(device.index, self.listen_baseline)
        except Exception as exc:
            self.listen_button.configure(text="●  Listen for input", state="normal")
            messagebox.showerror("Controller disconnected", str(exc), parent=self)
            return
        if result:
            kind, number, mode = result
            self.input_type_var.set("Button" if kind == "button" else "Axis as button")
            self.input_id_var.set(str(number))
            if mode:
                self.axis_mode_var.set(mode)
            self._input_changed()
            self.listen_button.configure(text=f"Captured {kind} {number}", state="normal")
            self.listen_after = None
        else:
            self.listen_after = self.after(35, lambda: self._poll_listen(device))

    def _save(self):
        device = self._selected_device()
        if device:
            device_token = device.guid
        elif self.device_var.get().startswith("Missing device  ·  "):
            device_token = self.device_var.get().split("  ·  ", 1)[1]
        else:
            messagebox.showwarning("Device required", "Choose a controller for this binding.", parent=self)
            return
        try:
            input_id = int(self.input_id_var.get())
            if input_id < 0:
                raise ValueError
            threshold = float(self.threshold_var.get())
        except ValueError:
            messagebox.showwarning("Invalid input", "Input number and threshold must be valid positive numbers.", parent=self)
            return
        kind = self.input_type_var.get()
        if kind == "Button" and input_id < 1:
            messagebox.showwarning("Invalid button", "Button numbers are 1-based, so the first button is 1.", parent=self)
            return
        if kind == "Button":
            lhs = f"dev:{device_token}:button:{input_id}"
            category = "key"
        elif kind == "Axis (analog)":
            lhs = f"dev:{device_token}:axis:{input_id}"
            category = "axis"
        else:
            lhs = f"dev:{device_token}:axis:{input_id}:{self.axis_mode_var.get()}:{threshold:g}"
            category = "key"
        if self.modified_var.get():
            lhs += ":M"

        spec = self._output_spec()
        rhs = render_action(spec)
        missing_target = (
            spec.kind == "Focus window" and not spec.values.get("target", "").strip()
        ) or (
            spec.kind == "Center mouse" and spec.values.get("target_type") != "Virtual"
            and not spec.values.get("target", "").strip()
        )
        if (not rhs or missing_target or
                (spec.kind == "Keyboard key" and not spec.values.get("shortcut", "").strip())):
            messagebox.showwarning("Action required", "Choose an output action and complete its required fields.", parent=self)
            return
        try:
            numeric_fields = []
            if spec.kind in {"Keyboard key", "Mouse button"}:
                numeric_fields = [("Duration", spec.values.get("duration", "30"))]
            elif spec.kind in {"Mouse wheel", "Mouse increment"}:
                numeric_fields = [("Starting rate", spec.values["initial"]), ("Maximum rate", spec.values["maximum"]), ("Acceleration time", spec.values["ramp"])]
            elif spec.kind == "Wiggle mouse":
                numeric_fields = [("Distance", spec.values["pixels"]), ("Period", spec.values["period"])]
            for label, value in numeric_fields:
                if int(value) < 0:
                    raise ValueError(f"{label} cannot be negative")
            if spec.kind == "Center mouse":
                float(spec.values["x"]); float(spec.values["y"])
        except (ValueError, TypeError) as exc:
            messagebox.showwarning("Invalid output option", f"Check the numeric output fields. {exc}", parent=self)
            return
        self.on_save(MappingRow(category, lhs, rhs))
        self._close()

    def _close(self):
        if self.listen_after:
            self.after_cancel(self.listen_after)
        self.destroy()


class ControllerMapperApp:
    def __init__(self, root: tk.Tk, initial_config: str | None = None):
        self.root = root
        self.root.title("Cockpit Mapper")
        self.root.geometry("1180x760")
        self.root.minsize(980, 650)
        self.root.configure(bg=Palette.BG)
        self.document = None
        self.rows: list[MappingRow] = []
        self.devices: list[ControllerDevice] = []
        self.controller_service = ControllerService()
        self.runtime_process = None
        self.dirty = False
        self._loading_settings = False
        self.profile_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.mapping_count_var = tk.StringVar(value="0")
        self.device_count_var = tk.StringVar(value="0")
        self.missing_count_var = tk.StringVar(value="0")
        self.repair_target_var = tk.StringVar()
        self._configure_style()
        self._build()
        self._discover_profiles(initial_config)
        self.refresh_controllers(silent=True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=Palette.BG, foreground=Palette.TEXT, fieldbackground=Palette.SURFACE_2,
                        bordercolor=Palette.BORDER, lightcolor=Palette.BORDER, darkcolor=Palette.BORDER,
                        font=("Segoe UI", 10))
        style.configure("TButton", background=Palette.SURFACE_2, foreground=Palette.TEXT, padding=(13, 8), relief="flat")
        style.map("TButton", background=[("active", Palette.BORDER), ("disabled", Palette.SURFACE)])
        style.configure("Accent.TButton", background=Palette.ACCENT, foreground="white", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", Palette.ACCENT_HOVER)])
        style.configure("Danger.TButton", foreground=Palette.DANGER)
        style.configure("TCombobox", padding=7, arrowsize=15)
        style.map("TCombobox", fieldbackground=[("readonly", Palette.SURFACE_2)], foreground=[("readonly", Palette.TEXT)])
        style.configure("TEntry", padding=7)
        style.configure("Treeview", background=Palette.SURFACE, fieldbackground=Palette.SURFACE,
                        foreground=Palette.TEXT, rowheight=34, borderwidth=0)
        style.configure("Treeview.Heading", background=Palette.SURFACE_2, foreground=Palette.MUTED,
                        font=("Segoe UI Semibold", 9), padding=8, relief="flat")
        style.map("Treeview", background=[("selected", "#254a81")], foreground=[("selected", "white")])
        style.configure("TNotebook", background=Palette.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=Palette.BG, foreground=Palette.MUTED,
                        padding=(16, 10), font=("Segoe UI Semibold", 10))
        style.map("TNotebook.Tab", background=[("selected", Palette.SURFACE)], foreground=[("selected", Palette.TEXT)])
        style.configure("TCheckbutton", background=Palette.SURFACE, foreground=Palette.TEXT)

    def _build(self):
        sidebar = tk.Frame(self.root, bg=Palette.SURFACE, width=232)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="◈", bg=Palette.SURFACE, fg=Palette.ACCENT,
                 font=("Segoe UI Semibold", 30)).pack(anchor="w", padx=24, pady=(24, 0))
        tk.Label(sidebar, text="COCKPIT\nMAPPER", justify="left", bg=Palette.SURFACE, fg=Palette.TEXT,
                 font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=24, pady=(0, 28))
        tk.Label(sidebar, text="PROFILE", bg=Palette.SURFACE, fg=Palette.MUTED,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=24)
        self.profile_box = ttk.Combobox(sidebar, textvariable=self.profile_var, state="readonly")
        self.profile_box.pack(fill="x", padx=24, pady=(7, 9))
        self.profile_box.bind("<<ComboboxSelected>>", self._profile_selected)
        ttk.Button(sidebar, text="Open another profile", command=self.open_profile).pack(fill="x", padx=24)

        tk.Frame(sidebar, bg=Palette.BORDER, height=1).pack(fill="x", padx=24, pady=24)
        self.runtime_button = ttk.Button(sidebar, text="▶  Start mapper", style="Accent.TButton", command=self.toggle_runtime)
        self.runtime_button.pack(fill="x", padx=24)
        ttk.Button(sidebar, text="Refresh controllers", command=self.refresh_controllers).pack(fill="x", padx=24, pady=(9, 0))
        tk.Label(sidebar, textvariable=self.status_var, wraplength=180, justify="left", bg=Palette.SURFACE,
                 fg=Palette.MUTED, font=("Segoe UI", 9)).pack(side="bottom", anchor="w", padx=24, pady=22)

        main = tk.Frame(self.root, bg=Palette.BG)
        main.pack(side="left", fill="both", expand=True, padx=26, pady=22)
        header = tk.Frame(main, bg=Palette.BG)
        header.pack(fill="x")
        title_box = tk.Frame(header, bg=Palette.BG)
        title_box.pack(side="left")
        tk.Label(title_box, text="Controller mappings", bg=Palette.BG, fg=Palette.TEXT,
                 font=("Segoe UI Semibold", 22)).pack(anchor="w")
        self.path_label = tk.Label(title_box, text="Choose an INI profile to begin", bg=Palette.BG, fg=Palette.MUTED,
                                   font=("Segoe UI", 9))
        self.path_label.pack(anchor="w", pady=(2, 0))
        self.save_button = ttk.Button(header, text="Save changes", style="Accent.TButton", command=self.save)
        self.save_button.pack(side="right", pady=4)

        cards = tk.Frame(main, bg=Palette.BG)
        cards.pack(fill="x", pady=18)
        for column, (label, variable, color) in enumerate((
            ("CONNECTED", self.device_count_var, Palette.SUCCESS),
            ("MAPPINGS", self.mapping_count_var, Palette.ACCENT),
            ("NEEDS ATTENTION", self.missing_count_var, Palette.WARNING),
        )):
            cards.columnconfigure(column, weight=1)
            card = tk.Frame(cards, bg=Palette.SURFACE, highlightbackground=Palette.BORDER, highlightthickness=1)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
            tk.Label(card, textvariable=variable, bg=Palette.SURFACE, fg=color,
                     font=("Segoe UI Semibold", 22)).pack(anchor="w", padx=16, pady=(12, 0))
            tk.Label(card, text=label, bg=Palette.SURFACE, fg=Palette.MUTED,
                     font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=16, pady=(0, 12))

        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True)
        self._build_bindings_tab()
        self._build_repair_tab()
        self._build_settings_tab()

    def _tab_frame(self):
        return tk.Frame(self.notebook, bg=Palette.SURFACE, highlightbackground=Palette.BORDER, highlightthickness=1)

    def _build_bindings_tab(self):
        tab = self._tab_frame()
        self.notebook.add(tab, text="Bindings")
        toolbar = tk.Frame(tab, bg=Palette.SURFACE)
        toolbar.pack(fill="x", padx=14, pady=12)
        ttk.Button(toolbar, text="＋ Add binding", style="Accent.TButton", command=self.add_binding).pack(side="left")
        ttk.Button(toolbar, text="Edit", command=self.edit_binding).pack(side="left", padx=7)
        ttk.Button(toolbar, text="Duplicate", command=self.duplicate_binding).pack(side="left")
        ttk.Button(toolbar, text="Delete", style="Danger.TButton", command=self.delete_binding).pack(side="right")
        tree_frame = tk.Frame(tab, bg=Palette.SURFACE)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        columns = ("device", "input", "output", "layer", "status")
        self.binding_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        headings = {"device": "CONTROLLER", "input": "INPUT", "output": "OUTPUT ACTION", "layer": "LAYER", "status": "STATUS"}
        widths = {"device": 235, "input": 135, "output": 310, "layer": 75, "status": 100}
        for column in columns:
            self.binding_tree.heading(column, text=headings[column])
            self.binding_tree.column(column, width=widths[column], minwidth=60, stretch=column in {"device", "output"})
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.binding_tree.yview)
        self.binding_tree.configure(yscrollcommand=scroll.set)
        self.binding_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.binding_tree.bind("<Double-1>", lambda _event: self.edit_binding())
        self.binding_tree.tag_configure("missing", foreground=Palette.WARNING)

    def _build_repair_tab(self):
        tab = self._tab_frame()
        self.notebook.add(tab, text="Device repair")
        tk.Label(tab, text="Reconnect a changed controller", bg=Palette.SURFACE, fg=Palette.TEXT,
                 font=("Segoe UI Semibold", 15)).pack(anchor="w", padx=20, pady=(20, 3))
        tk.Label(tab, text="Select an old device reference, choose the currently connected controller, and update every matching binding.",
                 bg=Palette.SURFACE, fg=Palette.MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 14))
        self.device_tree = ttk.Treeview(tab, columns=("reference", "state"), show="headings", height=8, selectmode="browse")
        self.device_tree.heading("reference", text="PROFILE DEVICE REFERENCE")
        self.device_tree.heading("state", text="STATE")
        self.device_tree.column("reference", width=640)
        self.device_tree.column("state", width=130, anchor="center")
        self.device_tree.pack(fill="both", expand=True, padx=20)
        self.device_tree.tag_configure("missing", foreground=Palette.WARNING)
        repair = tk.Frame(tab, bg=Palette.SURFACE)
        repair.pack(fill="x", padx=20, pady=18)
        tk.Label(repair, text="Replace with", bg=Palette.SURFACE, fg=Palette.MUTED).pack(side="left")
        ttk.Button(repair, text="Remap all references", width=20, style="Accent.TButton",
                   command=self.remap_selected).pack(side="right")
        self.repair_target = ttk.Combobox(repair, textvariable=self.repair_target_var, state="readonly", width=64)
        self.repair_target.pack(side="left", fill="x", expand=True, padx=10)

    def _build_settings_tab(self):
        tab = self._tab_frame()
        self.notebook.add(tab, text="Profile settings")
        form = tk.Frame(tab, bg=Palette.SURFACE)
        form.pack(fill="x", padx=24, pady=24)
        form.columnconfigure(1, weight=1)
        self.setting_vars = {
            "axis_mode": tk.StringVar(value="relative"), "axis_deadzone": tk.StringVar(value="0.05"),
            "axis_speed": tk.StringVar(value="400"), "axis_poll_hz": tk.StringVar(value="250"),
            "modifier": tk.StringVar(), "wiggle_initially_on": tk.StringVar(value="false:5:1000"),
        }
        for variable in self.setting_vars.values():
            variable.trace_add("write", self._settings_changed)
        fields = (
            ("Axis mode", "axis_mode", ("relative", "absolute")),
            ("Axis deadzone", "axis_deadzone", None), ("Axis speed", "axis_speed", None),
            ("Polling rate (Hz)", "axis_poll_hz", None), ("Global modifier", "modifier", None),
            ("Wiggle startup", "wiggle_initially_on", None),
        )
        for row, (label, key, choices) in enumerate(fields):
            tk.Label(form, text=label, bg=Palette.SURFACE, fg=Palette.MUTED).grid(row=row, column=0, sticky="w", padx=(0, 22), pady=8)
            if choices:
                widget = ttk.Combobox(form, textvariable=self.setting_vars[key], values=choices, state="readonly")
            else:
                widget = ttk.Entry(form, textvariable=self.setting_vars[key])
            widget.grid(row=row, column=1, sticky="ew", pady=8)
        tk.Label(form, text="Settings are applied when you click Save changes.", bg=Palette.SURFACE,
                 fg=Palette.MUTED, font=("Segoe UI", 9)).grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _discover_profiles(self, initial_config):
        paths = sorted(APP_DIR.glob("*.ini"), key=lambda path: path.name.casefold())
        if initial_config:
            initial = Path(initial_config).resolve()
            if initial not in paths:
                paths.append(initial)
        self.profile_paths = {path.name: path for path in paths}
        self.profile_box.configure(values=list(self.profile_paths))
        if paths:
            chosen = Path(initial_config).name if initial_config else paths[0].name
            self.profile_var.set(chosen)
            self.load_profile(self.profile_paths[chosen])

    def _profile_selected(self, _event=None):
        path = self.profile_paths.get(self.profile_var.get())
        if path:
            self.load_profile(path)

    def open_profile(self):
        filename = filedialog.askopenfilename(title="Open controller profile", filetypes=(("INI profiles", "*.ini"), ("All files", "*.*")))
        if not filename:
            return
        path = Path(filename).resolve()
        label = path.name if path.name not in self.profile_paths else str(path)
        self.profile_paths[label] = path
        self.profile_box.configure(values=list(self.profile_paths))
        self.profile_var.set(label)
        self.load_profile(path)

    def load_profile(self, path):
        if self.dirty and not messagebox.askyesno("Discard unsaved changes?", "This profile has unsaved changes. Open another profile anyway?", parent=self.root):
            return
        try:
            self.document = ConfigDocument(path)
            self.rows = self.document.mappings()
        except Exception as exc:
            messagebox.showerror("Could not open profile", str(exc), parent=self.root)
            return
        self.dirty = False
        self.path_label.configure(text=str(path))
        self._loading_settings = True
        try:
            for key, variable in self.setting_vars.items():
                defaults = {"axis_mode": "relative", "axis_deadzone": "0.05", "axis_speed": "400", "axis_poll_hz": "250", "wiggle_initially_on": "false:5:1000"}
                variable.set(self.document.get(key, defaults.get(key, "")))
        finally:
            self._loading_settings = False
        self._render_all()
        self.status_var.set(f"Loaded {path.name}")

    def refresh_controllers(self, silent=False):
        try:
            self.devices = self.controller_service.refresh()
            self.status_var.set(f"Found {len(self.devices)} connected controller{'s' if len(self.devices) != 1 else ''}")
        except Exception as exc:
            self.devices = []
            if not silent:
                messagebox.showerror("Controller scan failed", str(exc), parent=self.root)
            self.status_var.set(str(exc))
        self.repair_target.configure(values=[device.label for device in self.devices])
        if self.devices:
            self.repair_target_var.set(self.devices[0].label)
        self._render_all()

    def _render_all(self):
        for item in self.binding_tree.get_children():
            self.binding_tree.delete(item)
        missing = 0
        for index, row in enumerate(self.rows):
            connected = controller_matches(row.device, self.devices)
            if not connected:
                missing += 1
            self.binding_tree.insert("", "end", iid=str(index), values=(
                compact_device(row.device), row.input_label, describe_action(row.output),
                "Modified" if row.modified else "Base", "Connected" if connected else "Missing",
            ), tags=(() if connected else ("missing",)))
        self.mapping_count_var.set(str(len(self.rows)))
        self.device_count_var.set(str(len(self.devices)))
        self.missing_count_var.set(str(missing))

        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        if self.document:
            for index, ref in enumerate(self.document.referenced_devices(self.rows)):
                connected = controller_matches(ref, self.devices)
                self.device_tree.insert("", "end", iid=f"device-{index}", values=(ref, "Connected" if connected else "Missing"),
                                        tags=(() if connected else ("missing",)))

    def _selected_row_index(self):
        selected = self.binding_tree.selection()
        return int(selected[0]) if selected else None

    def add_binding(self):
        BindingDialog(self.root, self.devices, None, self._append_row, self.controller_service)

    def _append_row(self, row):
        self.rows.append(row)
        self._mark_dirty()

    def edit_binding(self):
        index = self._selected_row_index()
        if index is None:
            return
        BindingDialog(self.root, self.devices, self.rows[index], lambda row: self._replace_row(index, row), self.controller_service)

    def _replace_row(self, index, row):
        self.rows[index] = row
        self._mark_dirty()

    def duplicate_binding(self):
        index = self._selected_row_index()
        if index is None:
            return
        row = self.rows[index]
        self.rows.insert(index + 1, MappingRow(row.category, row.input, row.output))
        self._mark_dirty()

    def delete_binding(self):
        index = self._selected_row_index()
        if index is None:
            return
        del self.rows[index]
        self._mark_dirty()

    def _mark_dirty(self):
        self.dirty = True
        self.save_button.configure(text="Save changes  •")
        self._render_all()

    def _settings_changed(self, *_args):
        if not self._loading_settings and self.document is not None:
            self._mark_dirty()

    def remap_selected(self):
        selection = self.device_tree.selection()
        target_label = self.repair_target_var.get()
        target = next((device for device in self.devices if device.label == target_label), None)
        if not selection or not target or not self.document:
            messagebox.showinfo("Select devices", "Select a profile reference and a connected replacement controller.", parent=self.root)
            return
        old = self.device_tree.item(selection[0], "values")[0]
        if old == target.guid:
            return
        count = self.document.remap_device(old, target.guid, self.rows)
        if count:
            self._mark_dirty()
            self.status_var.set(f"Remapped {count} reference{'s' if count != 1 else ''} to {target.name}; save to apply")

    def save(self):
        if not self.document:
            return
        try:
            self.document.set_mappings(self.rows)
            for key, variable in self.setting_vars.items():
                self.document.set_option(key, variable.get().strip())
            backup = self.document.save(make_backup=True)
        except Exception as exc:
            messagebox.showerror("Could not save profile", str(exc), parent=self.root)
            return
        self.dirty = False
        self.save_button.configure(text="Save changes")
        self.status_var.set(f"Saved {self.document.path.name} · backup: {backup.name if backup else 'none'}")

    def _terminate_runtime(self):
        """Stop the mapper child process.

        A one-file build runs the mapper as a bootloader parent plus a real
        child process, so terminating only the parent would leave the mapper
        alive and still grabbing input. Kill the whole tree instead.
        """
        process = self.runtime_process
        if not process or process.poll() is not None:
            return
        if is_frozen():
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                               capture_output=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return
            except Exception:
                pass  # fall through to a plain terminate
        process.terminate()

    def toggle_runtime(self):
        if self.runtime_process and self.runtime_process.poll() is None:
            self._terminate_runtime()
            self.runtime_process = None
            self.runtime_button.configure(text="▶  Start mapper")
            self.status_var.set("Mapper stopped")
            return
        if not self.document:
            return
        if self.dirty:
            self.save()
            if self.dirty:
                return
        try:
            if is_frozen():
                # The mapper lives in this same executable; re-launch it via the sentinel.
                command = [sys.executable, "--run-mapper", "--config", str(self.document.path)]
            else:
                command = [sys.executable, str(APP_DIR / "main.py"), "--config", str(self.document.path)]
            self.runtime_process = subprocess.Popen(command, cwd=APP_DIR)
        except Exception as exc:
            messagebox.showerror("Could not start mapper", str(exc), parent=self.root)
            return
        self.runtime_button.configure(text="■  Stop mapper")
        self.status_var.set(f"Mapper running with {self.document.path.name}")
        self.root.after(750, self._check_runtime)

    def _check_runtime(self):
        if self.runtime_process and self.runtime_process.poll() is None:
            self.root.after(750, self._check_runtime)
        elif self.runtime_process:
            code = self.runtime_process.returncode
            self.runtime_process = None
            self.runtime_button.configure(text="▶  Start mapper")
            self.status_var.set(f"Mapper exited with code {code}")

    def _on_close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel("Unsaved changes", "Save changes before closing?", parent=self.root)
            if answer is None:
                return
            if answer:
                self.save()
                if self.dirty:
                    return
        if self.runtime_process and self.runtime_process.poll() is None:
            self._terminate_runtime()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="GUI profile editor for DCS Mouse Controller")
    parser.add_argument("--config", "-c", help="INI profile to open")
    args = parser.parse_args()
    root = tk.Tk()
    ControllerMapperApp(root, args.config)
    root.mainloop()


if __name__ == "__main__":
    main()
